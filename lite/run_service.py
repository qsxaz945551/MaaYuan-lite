"""Threaded run service used by the lightweight local UI."""

from __future__ import annotations

import json
import subprocess
import threading
import time
from collections import deque
from datetime import datetime, timedelta

from .constants import DEFAULT_TRAINING, TRAINING_TYPES
from pathlib import Path
from typing import Any

from .daily_plan import build_plan, load_profile
from .guards import NodeRepeatGuard
from .pipeline_fixes import apply_pipeline_fixes
from .round_progress import marker_labels
from .session import LiteSession
from .settings import load_settings
from .task_options_service import load_inputs
from .task_overrides import build_task_override, load_options_snapshot


# Only these tasks spend stamina, so only a failure here can mean "ran dry".
# Checking the dialog on every failure cost 1.2 s per failure and could turn an
# unrelated failure into a false "succeeded" when the box happened to be open.
# One file, rotated once at 5 MB: a full day of daily runs is a few hundred KB.
LOG_MAX_BYTES = 5 * 1024 * 1024

STAMINA_TASKS = ("历练", "白鹄", "地宫", "鸢报")


def _consumes_stamina(name: str) -> bool:
    return any(hint in name for hint in STAMINA_TASKS)


# 任务跑完 ≠ 拿到奖励。这两个信号表示「资源不足、主动收手」：
#   · 气力值回复弹窗 —— 历练 / 白鹄 / 地宫 卡在这里；
#   · 节点名含「不吃鸟食」—— 鸢报的鸟食没了，直接收手。
# 命中后任务记 skipped_no_resource，单独计数，不污染成功率（用户 2026-11-07 定）。
RESOURCE_MARKERS = ("不吃鸟食",)

# 这些任务的目标本来就是「把资源刷干」，刷干即完成，不该挂「未领取到资源」。
GRIND_TASKS = ("刷到体力耗尽",)


def _is_grind(name: str) -> bool:
    return any(hint in name for hint in GRIND_TASKS)


# 跨日的分界线不是 00:00 而是 05:00：凌晨还在跑前一天没跑完的日常是常态，
# 用零点切会把刚跑了一半的记录作废（用户 2026-11-07 定）。
DAY_CUTOFF_HOUR = 5


def day_window_start(now: datetime | None = None) -> datetime:
    """Start of the current 日常 day, i.e. the most recent 05:00."""
    moment = now or datetime.now()
    start = moment.replace(hour=DAY_CUTOFF_HOUR, minute=0, second=0, microsecond=0)
    if moment < start:
        start -= timedelta(days=1)
    return start


def parse_stamp(value: str) -> datetime | None:
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return None


# The system ANR dialog, measured on a 720x1280 capture: title around y=478,
# "等待" at (303, 688). ROIs elsewhere in the pipeline use the same baseline.
ANR_KEYWORDS = ("没有响应", "无响应", "没有回應")
ANR_ROI = (0, 400, 720, 300)
ANR_WAIT_POINT = (303, 688)
ANR_WAIT_SECONDS = 20.0

# Close button of the 气力值回复 dialog, measured on a 720x1280 capture.
STAMINA_DIALOG_CLOSE = (577, 259)

# No node finished for this long ⇒ the screen is probably covered by a dialog
# nobody recognises. 150 s is well above the slowest normal step and far below
# the 30-minute task timeout.
STALL_SECONDS = 150.0

# The single source of truth for "how long may this task run".
# None means no limit (邺城 runs until stopped by hand).
DEFAULT_TASK_TIMEOUT = 1800
DEFAULT_TIMEOUTS = {
    "🚀 启动游戏": 300,
    "💰 领月卡福利": 1200,
    "🏯 据点日常": 1800,
    "🔮 观星": 1800,
    "💎 修为历练": 1200,
    "💲 铜钱历练": 1200,
    "⚔️ 经验历练": 1200,
    "🗡 白鹄扫荡": 1200,
    "🗡 地宫助手": 1500,
    "🔄 鸢报四合一": 1800,
    "📜 鸢报四连 - 日常专用": 1800,
    "🔶 日常收尾": 1800,
    "🏰 邺城之战V3": None,  # 无限刷取，无时间上限，靠手动停止
}


def timeout_for(name: str, override: float | None = None) -> float | None:
    """Resolve a task's time limit — the only place that decides this.

    ``override`` (from a plan item or an API call) wins; otherwise the table;
    otherwise ``DEFAULT_TASK_TIMEOUT``. ``None`` means "no limit".
    """
    if override is not None:
        return override
    if name in DEFAULT_TIMEOUTS:
        return DEFAULT_TIMEOUTS[name]
    return DEFAULT_TASK_TIMEOUT


def _png_size(path: Path) -> tuple[int, int] | None:
    """Read width/height from a PNG header without loading the image."""
    try:
        with path.open("rb") as handle:
            head = handle.read(24)
    except OSError:
        return None
    if len(head) < 24 or head[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    return (
        int.from_bytes(head[16:20], "big"),
        int.from_bytes(head[20:24], "big"),
    )


class RunService:
    def __init__(self, project_root: Path, config: dict[str, Any]) -> None:
        self.project_root = project_root
        self.config = config
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._session: LiteSession | None = None
        self._cancel = threading.Event()
        self._guard_event = threading.Event()
        self._guard_node = ""
        self._last_node_time = time.monotonic()
        # Set when a node proves the task stopped early for lack of resources
        # (bird food gone). Reset per job, read by _classify_result.
        self._resource_hit = False
        self._logs: deque[dict[str, Any]] = deque(maxlen=2000)
        self._log_seq = 0
        # Stable per process; clients use a change to resync after a restart.
        self._run_id = int(time.time_ns() % 1_000_000_000)
        self._status = "idle"
        self._current_task = ""
        self._tasks: list[dict[str, Any]] = []
        self._plan: dict[str, Any] | None = None
        self._single: dict[str, Any] | None = None
        # The node the task is on right now, with the pipeline's own `focus`
        # text when it has one. Cleared between tasks.
        self._step: dict[str, Any] | None = None
        self._summary: dict[str, Any] = {}
        self._preview: list[dict[str, Any]] | None = None
        self._started_at = ""
        self._finished_at = ""
        self._last_screenshot = self.project_root / "runtime" / "last-screen.png"
        self._state_file = self.project_root / "runtime" / "last-run.json"
        self._shutdown_hook: Any = None
        self._log_path = self.project_root / "runtime" / "lite.log"
        self._rotate_log()
        self._load_last_run()

    def _rotate_log(self) -> None:
        """Keep one previous file; a day of runs is a few hundred KB."""
        try:
            if self._log_path.is_file() and self._log_path.stat().st_size > LOG_MAX_BYTES:
                rotated = self._log_path.with_suffix(".log.1")
                rotated.unlink(missing_ok=True)
                self._log_path.rename(rotated)
        except OSError:
            pass

    def set_shutdown_hook(self, hook: Any) -> None:
        self._shutdown_hook = hook

    def note(self, message: str, level: str = "info") -> None:
        """Public entry for the shell and the parent guard.

        They need to write into the same run log; without it, a service that
        exits on its own leaves no trace and looks like a crash.
        """
        self._log(message, level)

    def _log(self, message: str, level: str = "info") -> None:
        with self._lock:
            self._log_seq += 1
            stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self._logs.append(
                {
                    "seq": self._log_seq,
                    "time": stamp[11:],
                    "level": level,
                    "message": message,
                }
            )
            # Appended per line on purpose: a held handle blocked temp-dir
            # cleanup in tests and would survive a crash without flushing.
            path = getattr(self, "_log_path", None)
            if path is not None:
                try:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    with path.open("a", encoding="utf-8") as handle:
                        handle.write(f"{stamp} [{level}] {message}\n")
                except OSError:
                    pass

    def _reset_logs(self) -> None:
        """Start a new run without discarding the previous log lines."""
        with self._lock:
            if not self._logs:
                return
            self._log_seq += 1
            self._logs.append(
                {
                    "seq": self._log_seq,
                    "time": datetime.now().strftime("%H:%M:%S"),
                    "level": "info",
                    "message": "—— 新的一次运行 ——",
                }
            )

    def _load_last_run(self) -> None:
        """Restore the previous run so unfinished tasks can be resumed."""
        if not self._state_file.is_file():
            return
        try:
            data = json.loads(self._state_file.read_text(encoding="utf-8"))
            tasks = data.get("tasks") or []
            plan = data.get("plan")
        except Exception:
            return
        if not tasks or not isinstance(plan, dict):
            return

        # 昨天的记录不能拿来续跑：跨过 05:00 就作废（见 DAY_CUTOFF_HOUR）。
        stamp = parse_stamp(str(data.get("finishedAt") or "")) or parse_stamp(
            str(data.get("updatedAt") or "")
        )
        if stamp is None or stamp < day_window_start():
            self._log("上次运行记录已跨日（05:00 为界），作废，不再提供续跑。", "warn")
            try:
                self._state_file.unlink()
            except OSError:
                pass
            return

        self._tasks = [dict(task) for task in tasks]
        self._plan = plan
        self._summary = data.get("summary") or {}
        self._finished_at = data.get("finishedAt", "")
        unfinished = any(
            task.get("status") in {"failed", "timed_out", "pending", "cancelled", "running"}
            for task in self._tasks
        )
        if unfinished:
            self._status = "interrupted"
            self._log("检测到上次运行未完成，可点“继续未完成”补跑。", "warn")
        else:
            previous = data.get("status")
            self._status = previous if previous in {
                "completed",
                "completed_with_errors",
                "cancelled",
            } else "idle"
            self._log(f"已载入上次运行记录：{len(self._tasks)} 项，全部结束。")

    def _persist(self) -> None:
        with self._lock:
            if not self._tasks or self._plan is None:
                return
            payload = {
                "updatedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "status": self._status,
                "finishedAt": self._finished_at,
                "tasks": [dict(task) for task in self._tasks],
                "plan": self._plan,
                "summary": dict(self._summary),
            }
        try:
            self._state_file.parent.mkdir(parents=True, exist_ok=True)
            self._state_file.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except OSError:
            pass

    def log_cursor(self) -> int:
        """Latest log sequence; clients start here to skip earlier output."""
        with self._lock:
            return self._log_seq

    def snapshot(self, since: int = 0) -> dict[str, Any]:
        with self._lock:
            if since < 0 or since > self._log_seq:
                # Client is ahead of this process (restart) -> send everything.
                logs = list(self._logs)
            else:
                logs = [item for item in self._logs if item["seq"] > since]
            return {
                "status": self._status,
                "currentTask": self._current_task,
                "tasks": [
                    dict(task)
                    for task in (self._tasks if self._tasks else self._preview_tasks())
                ],
                "summary": dict(self._summary),
                "startedAt": self._started_at,
                "finishedAt": self._finished_at,
                "logs": logs,
                "logSeq": self._log_seq,
                "runId": self._run_id,
                "single": dict(self._single) if self._single else None,
                "step": dict(self._step) if self._step else None,
                "busy": self._thread is not None and self._thread.is_alive(),
                "canResume": bool(self._tasks)
                and any(
                    task["status"] in {"failed", "timed_out", "pending", "cancelled", "running"}
                    for task in self._tasks
                ),
                "config": {
                    "adbSerial": self.config.get("adb_serial"),
                    "resource": self.config.get("resource_path"),
                },
            }

    def _busy(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _preview_tasks(self) -> list[dict[str, Any]]:
        """The plan shown before the first run, so the window is not empty.

        These are display-only: they never enter ``_tasks``, so ``canResume``
        stays false and a fresh install cannot accidentally "resume" a run that
        never happened.
        """
        if self._preview is not None:
            return [dict(task) for task in self._preview]

        try:
            settings = load_settings()
            plan = build_plan(
                load_profile(),
                training=str(settings.get("last_training", DEFAULT_TRAINING)),
                include_seasonal=bool(settings.get("last_dungeon", False)),
            )
            preview = []
            for item in plan["tasks"]:
                timeout = timeout_for(item["name"], item.get("timeout_sec"))
                preview.append(
                    {
                        "name": item["name"],
                        "kind": item.get("kind", "daily"),
                        "status": "pending",
                        "duration": 0,
                        "attempts": 0,
                        "timeout": timeout,
                    }
                )
            self._preview = preview
        except Exception:  # noqa: BLE001 - preview must never break the API
            self._preview = []
        return [dict(task) for task in self._preview]

    def start_daily(
        self,
        training: str,
        include_dungeon: bool,
        resume: bool = False,
        names: list[str] | None = None,
        extra: list[str] | None = None,
    ) -> bool:
        if self._busy():
            return False
        if training not in TRAINING_TYPES:
            raise ValueError("Invalid training choice")
        if resume and not self.can_resume():
            return False
        # names 是今日日常的勾选，extra 是「其他任务」的勾选；两边都空才拒绝。
        if names is not None and not names and not extra:
            raise ValueError("没有选中任何任务")
        self._cancel.clear()
        with self._lock:
            self._status = "starting"
            self._current_task = ""
            self._single = None
            self._summary = {}
            self._started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self._finished_at = ""
            self._reset_logs()
        self._thread = threading.Thread(
            target=self._run_daily,
            args=(training, include_dungeon, resume, names, extra),
            name="maayuan-lite-runner",
            daemon=True,
        )
        self._thread.start()
        return True

    def can_resume(self) -> bool:
        with self._lock:
            if not self._tasks:
                return False
            return any(
                task["status"] in {"failed", "timed_out", "pending", "cancelled", "running"}
                for task in self._tasks
            )

    def check_connection(self) -> bool:
        if self._busy():
            return False
        with self._lock:
            previous_status = self._status
            self._status = "checking"
            self._current_task = ""
        # A connection check must not touch the daily run record: it is what
        # "继续未完成" depends on, and wiping it silently disabled resume.
        self._cancel.clear()
        self._reset_logs()
        self._thread = threading.Thread(
            target=self._check_connection,
            args=(previous_status,),
            name="maayuan-lite-check",
            daemon=True,
        )
        self._thread.start()
        return True

    def stop(self) -> None:
        self._cancel.set()
        with self._lock:
            session = self._session
        if session is not None:
            session.request_stop()
        self._log("收到停止请求，正在结束当前任务……", "warn")

    def run_single(self, task_name: str, timeout_sec: float | None = None) -> bool:
        return self.run_sequence([task_name], timeout_sec)

    def run_sequence(self, task_names: list[str], timeout_sec: float | None = None) -> bool:
        """Run tasks outside the daily chain in order; daily progress stays untouched."""
        if self._busy():
            return False
        names = [name for name in task_names if name]
        if not names:
            raise ValueError("No task given")

        interface = json.loads(
            (self.project_root / "build" / "generated" / "interface.json").read_text(
                encoding="utf-8"
            )
        )
        options = load_options_snapshot()
        inputs = load_inputs()
        jobs: list[dict[str, Any]] = []
        for task_name in names:
            task = next(
                (item for item in interface.get("task", []) if item.get("name") == task_name),
                None,
            )
            if task is None or task.get("entry") == "stop":
                raise ValueError(f"Unknown task: {task_name}")
            notes: list[str] = []
            override = build_task_override(
                interface,
                task,
                options.get(task_name, {}),
                inputs.get(task_name, {}),
                notes,
            )
            self._report_option_notes(task_name, notes)
            jobs.append(
                {
                    "name": task_name,
                    "entry": task["entry"],
                    "override": apply_pipeline_fixes(task["entry"], override),
                    "timeout": timeout_for(task_name, timeout_sec),
                }
            )

        self._cancel.clear()
        with self._lock:
            self._status = "starting"
            self._current_task = names[0]
            self._started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self._finished_at = ""
            self._reset_logs()
        with self._lock:
            self._single = {
                "name": names[0],
                "names": names,
                "index": 0,
                "total": len(names),
                "status": "pending",
                "duration": 0,
                "timeout": jobs[0]["timeout"],
                "results": [],
            }
        self._thread = threading.Thread(
            target=self._run_sequence,
            args=(jobs,),
            name="maayuan-lite-single",
            daemon=True,
        )
        self._thread.start()
        return True

    def _update_task(self, index: int, **fields: Any) -> None:
        """Write several task fields in one lock.

        Writing status, duration and attempts separately let a snapshot land
        between them: the badge flickered to "完成" while the duration still
        read 0, which looked like the task never ran.
        """
        with self._lock:
            if 0 <= index < len(self._tasks):
                self._tasks[index].update(fields)

    def _update_run(
        self,
        *,
        status: str | None = None,
        current_task: str | None = None,
        summary: dict[str, Any] | None = None,
    ) -> None:
        """Publish run-level fields together; ``None`` means "leave alone"."""
        with self._lock:
            if status is not None:
                self._status = status
            if current_task is not None:
                self._current_task = current_task
            if summary is not None:
                self._summary = summary

    def _tally(self) -> tuple[int, int, int]:
        """Count finished tasks by outcome. Reading under the lock keeps the
        numbers consistent with what snapshot() will publish.

        ``skipped_no_resource`` is its own bucket: the task did finish, but it
        stopped early because stamina/bird food ran out, so counting it as a
        success overstates the day and counting it as a failure punishes the
        emulator's resources rather than the code.
        """
        with self._lock:
            succeeded = sum(1 for task in self._tasks if task["status"] == "succeeded")
            failed = sum(
                1 for task in self._tasks if task["status"] in {"failed", "timed_out"}
            )
            skipped = sum(
                1 for task in self._tasks if task["status"] == "skipped_no_resource"
            )
        return succeeded, failed, skipped

    def _finalize_run(
        self,
        *,
        aborted: bool,
        cancelled: bool,
        succeeded: int,
        failed: int,
        skipped: int = 0,
    ) -> str:
        """Decide the terminal status and summary in one place.

        The daily chain and the ad-hoc queue used to compute this separately,
        which is how they ended up disagreeing on whether a stopped run counts
        as an error. Log lines stay with the caller because they differ.
        """
        with self._lock:
            if aborted:
                self._status = "error"
            elif cancelled:
                self._status = "cancelled"
            elif failed:
                self._status = "completed_with_errors"
            else:
                self._status = "completed"
            self._summary = {
                "succeeded": succeeded,
                "failed": failed,
                "skipped": skipped,
            }
            return self._status

    def _execute_job(
        self,
        session: LiteSession,
        *,
        name: str,
        entry: str,
        override: dict[str, Any],
        timeout: float,
        retries: int = 0,
        announce: str = "开始任务",
        started: float | None = None,
    ) -> tuple[dict[str, Any], float, dict[str, Any]]:
        """Run one task and classify the result.

        Both the daily chain and the ad-hoc queue come through here. Keeping
        callback setup, the loop guard, and classification in one place is what
        stopped the two paths from drifting (timeout handling was the last one
        to diverge).
        """
        begin = started if started is not None else time.monotonic()
        self._last_node_time = begin
        self._resource_hit = False
        self._log(f"{announce}：{name}")
        session.set_node_callback(self._make_round_handler(entry))
        session.set_step_callback(self._make_step_handler(name))
        self._start_guard(session, entry)
        try:
            result = session.run_task(
                entry=entry,
                pipeline_override=override,
                timeout_sec=timeout,
                retries=retries,
                should_stop=self._guard_stop,
                agent_check=session.agent_alive,
                stall_check=self._stalled,
            )
        finally:
            session.set_node_callback(None)
            session.set_node_start_callback(None)
            session.set_step_callback(None)
            self._clear_step()
        duration = round(time.monotonic() - begin, 1)
        outcome = self._classify_result(session, name, result, duration)
        return outcome, duration, result

    def _run_sequence(self, jobs: list[dict[str, Any]]) -> None:
        session = self._make_session()
        with self._lock:
            self._session = session
            self._status = "running"
            self._single["status"] = "running"
        total = len(jobs)
        failures = 0
        skipped = 0
        aborted = False
        try:
            session.start()
            for index, job in enumerate(jobs):
                if self._cancel.is_set():
                    break
                name = job["name"]
                if not self._ensure_ready(session):
                    with self._lock:
                        self._status = "error"
                        self._single["status"] = "failed"
                    aborted = True
                    break
                with self._lock:
                    self._single["index"] = index
                    self._single["name"] = name
                    self._single["status"] = "running"
                    self._current_task = name
                suffix = f"（{index + 1}/{total}）" if total > 1 else ""
                outcome, duration, _result = self._execute_job(
                    session,
                    name=name,
                    entry=job["entry"],
                    override=job["override"],
                    timeout=job["timeout"],
                    announce=f"单独运行{suffix}",
                )
                status = outcome["status"]
                restart_failed = outcome["restart_failed"]
                if status in {"failed", "timed_out"}:
                    failures += 1
                elif status == "skipped_no_resource":
                    skipped += 1
                with self._lock:
                    self._single["results"].append(
                        {"name": name, "status": status, "duration": duration}
                    )
                    self._single["duration"] = round(
                        sum(item["duration"] for item in self._single["results"]), 1
                    )
                    self._single["status"] = status
                if status == "cancelled" or restart_failed or outcome.get("aborted"):
                    aborted = aborted or restart_failed or bool(outcome.get("aborted"))
                    break

            done = len(self._single["results"])
            self._finalize_run(
                aborted=aborted,
                cancelled=self._cancel.is_set(),
                succeeded=done - failures - skipped,
                failed=failures,
                skipped=skipped,
            )
            if total > 1:
                extra = f"，未领取 {skipped} 项" if skipped else ""
                self._log(
                    f"批量结束：共 {total} 项，成功 {done - failures - skipped} 项，"
                    f"失败 {failures} 项{extra}。"
                )
        except Exception as error:
            with self._lock:
                self._status = "error"
                self._single["status"] = "failed"
            self._log(f"运行异常：{error}", "error")
        finally:
            session.stop()
            with self._lock:
                self._session = None
                self._current_task = ""
                self._finished_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def _asset_root(self, key: str, fallback: str) -> Path:
        """Resolve a resource/agent root.

        ``resource_root`` / ``agent_root`` in runtime-config.json may point at
        the upstream install so that its updates reach Lite without copying
        the whole tree again. Empty means "use the copy inside this project".
        """
        override = str(self.config.get(key) or "").strip()
        if override:
            path = Path(override)
            return path if path.is_absolute() else self.project_root / path
        return self.project_root / fallback

    def _make_session(self) -> LiteSession:
        return LiteSession(
            logger=self._log,
            project_root=self.project_root,
            maa_root=Path(self.config["runtime_root"]),
            adb_path=Path(self.config["adb_path"]),
            serial=self.config.get("adb_serial", "emulator-5554"),
            resource_path=self._asset_root(
                "resource_root",
                self.config.get("resource_path", "assets/resource/base"),
            ),
            agent_root=self._asset_root("agent_root", "agent"),
        )

    def _guard_stop(self) -> bool:
        """should_stop callback shared by user stop and the loop guard."""
        return self._cancel.is_set() or self._guard_event.is_set()

    def _ensure_ready(self, session: LiteSession) -> bool:
        """Reconnect ADB and restart the Agent before a task if needed."""
        if not session.device_ready():
            self._log("模拟器连接已断开，正在尝试重连……", "warn")
            if not session.reconnect():
                self._log("重连失败，模拟器可能已关闭，本次运行停止。", "error")
                return False
            self._log("已重新连接模拟器，继续执行。")

        if not session.agent_alive():
            self._log("Agent 已退出，正在重启……", "warn")
            if not session.restart_agent():
                self._log("Agent 重启失败，本次运行停止。", "error")
                return False
            self._log("Agent 已重启，继续执行。")
        return True

    def _start_guard(self, session: LiteSession, entry: str) -> None:
        """Watch for a single node looping forever inside this task."""
        self._guard_event.clear()
        self._guard_node = ""
        self._last_node_time = time.monotonic()
        if marker_labels(entry):
            # Farming tasks are supposed to run long; they are bounded by the
            # user's stop request instead of this guard.
            session.set_node_start_callback(None)
            return
        guard = NodeRepeatGuard()

        def handle(node_name: str) -> None:
            if guard.hit(node_name):
                self._guard_node = node_name
                self._guard_event.set()
                self._log(
                    f"节点「{node_name}」重复执行超过 {guard.budget} 次，"
                    "判定为死循环，正在中止任务。",
                    "error",
                )

        session.set_node_start_callback(handle)

    def _make_round_handler(self, entry: str):
        """Count loops for tasks that define markers, and feed the stall watchdog.

        Every task needs the heartbeat: a task stuck behind an unrecognised
        dialog finishes no nodes at all, which is exactly the signal the
        watchdog waits for. Returning None for marker-less tasks would leave it
        blind exactly where it matters most.
        """
        labels = marker_labels(entry)
        counter = {"n": 0}
        lock = threading.Lock()

        def handle(node_name: str) -> None:
            self._last_node_time = time.monotonic()
            # 资源不足的节点要先记下来：鸢报走到「不吃鸟食」等于这轮放弃了，
            # 框架仍报 success，靠这个标记才能改成 skipped_no_resource。
            if any(marker in node_name for marker in RESOURCE_MARKERS):
                self._resource_hit = True
            if not labels:
                return
            label = labels.get(node_name)
            if label is None:
                return
            with lock:
                counter["n"] += 1
                count = counter["n"]
            self._log(f"第 {count} 轮完成（{label}）")

        return handle

    def _make_step_handler(self, task_name: str):
        """Track which node the running task is on, for the console's step line.

        ``focus`` is only present on some nodes, so the raw node name is stored
        next to the display text: a bug report can still quote exactly what the
        pipeline was doing.

        Deliberately does not touch ``_last_node_time`` — that heartbeat is fed
        by *finished* nodes, and a pipeline looping between node starts without
        ever completing one is precisely the stall the watchdog looks for.
        """

        def handle(node_name: str, text: str | None) -> None:
            step = {
                "task": task_name,
                "node": node_name,
                "label": text or node_name,
                "focus": bool(text),
                "at": datetime.now().strftime("%H:%M:%S"),
            }
            with self._lock:
                self._step = step

        return handle

    def _clear_step(self) -> None:
        with self._lock:
            self._step = None

    def _stalled(self) -> bool:
        """True when no node has finished for STALL_SECONDS."""
        return (time.monotonic() - self._last_node_time) > STALL_SECONDS

    def _stamina_exhausted(self, session: LiteSession) -> bool:
        """True when the stamina refill dialog is on screen, and close it.

        Farming tasks ("刷到体力耗尽") are supposed to end here; without this
        check the framework reports a recognition failure instead. The dialog
        also has to be dismissed, otherwise it keeps covering the screen and
        every following task fails on the same overlay.
        """
        check = getattr(session, "has_stamina_dialog", None)
        if check is None:
            return False
        try:
            if not check():
                return False
        except Exception:
            return False

        tap = getattr(session, "tap", None)
        back = getattr(session, "press_back", None)
        if tap is not None:
            tap(*STAMINA_DIALOG_CLOSE)
            time.sleep(1.0)
        try:
            if check():
                if back is not None:
                    back()
                    time.sleep(0.8)
        except Exception:  # noqa: BLE001 - dismissing is best effort
            pass
        return True

    def _capture_failure(self, session: LiteSession, name: str) -> None:
        try:
            stamp = datetime.now().strftime("%m%d-%H%M%S")
            cleaned = name
            for char in '\\/:*?"<>|':
                cleaned = cleaned.replace(char, "_")
            path = (
                self.project_root
                / "runtime"
                / "failures"
                / f"{stamp}-{cleaned[:40]}.png"
            )
            session.capture_png(path)
            self._log(f"已保存错误截图：runtime/failures/{path.name}", "warn")
        except Exception as error:
            self._log(f"错误截图保存失败：{error}", "warn")

    def _handle_anr(self, session: LiteSession) -> bool:
        """Dismiss the system "app isn't responding" dialog by tapping 等待.

        The dialog belongs to Android, not the game, so upstream's popup list
        never matches it: the run spins on the startup task until timeout and
        the log only shows failed recognitions. Only 等待 is tapped — 关闭应用
        would drop the current run's progress, so it stays manual.
        """
        probe = getattr(session, "probe", None)
        tap = getattr(session, "tap", None)
        if probe is None or tap is None:
            return False
        try:
            hit = probe(
                [
                    {
                        "type": "OCR",
                        "param": {
                            "expected": list(ANR_KEYWORDS),
                            "roi": list(ANR_ROI),
                            "threshold": 0.8,
                        },
                    }
                ],
                timeout_ms=1500,
            )
        except Exception:  # noqa: BLE001 - a probe failure is not an ANR
            return False
        if not hit:
            return False

        self._log("检测到系统「无响应」弹窗，点“等待”让游戏继续……", "warn")
        tap(*ANR_WAIT_POINT)
        # The game usually needs a while to finish whatever blocked the UI.
        time.sleep(ANR_WAIT_SECONDS)
        return True

    def _recover_unknown_screen(self, session: LiteSession) -> bool:
        """Try to leave an unknown popup (new event banner, update notice).

        Upstream's popup list is hard-coded, so a brand-new full-screen activity
        page is not recognised and the task keeps retrying until it times out.
        Back key first (no mis-tap risk), then the usual top-right close area.
        """
        probe = getattr(session, "is_main_screen", None)
        back = getattr(session, "press_back", None)
        tap = getattr(session, "tap", None)
        if probe is None or back is None:
            return False
        try:
            if probe():
                return False
            self._log("检测到未知界面，尝试用返回键退出……", "warn")
            for _ in range(2):
                back()
                time.sleep(1.2)
                if probe():
                    self._log("已退出未知界面，回到主界面。", "warn")
                    return True
            if tap is not None:
                self._log("返回键无效，尝试点击右上角关闭区……", "warn")
                tap(690, 40)
                time.sleep(1.2)
                if probe():
                    self._log("已退出未知界面，回到主界面。", "warn")
                    return True
            self._log("未能退出未知界面；如仍有弹窗，请手动处理后点“继续未完成”。", "error")
        except Exception as error:  # noqa: BLE001 - recovery must never abort a run
            self._log(f"未知界面清理失败：{error}", "warn")
        return False

    def _report_option_notes(self, name: str, notes: list[str]) -> None:
        """把选项解析过程中的偏差写进运行日志。

        这些偏差意味着「保存的选择和当前资源对不上」，例如上游重排了可选值，
        老索引指向了别的值。不报出来就只会表现为「任务跑了个别的关卡」。
        """
        for note in notes:
            self._log(f"任务「{name}」的选项有变化：{note}", "warn")

    def _back_to_main(self, session: LiteSession, name: str) -> None:
        """Return to the main screen after a clean stamina stop.

        Farming ends the moment the refill dialog appears, which can leave the
        game on a reward or activity page. The next task assumes the main
        screen, so it would burn its whole stall window failing to recognise
        anything — 日常收尾 did exactly that on 2026-11-05.

        ``_recover_unknown_screen`` probes first and does nothing when the main
        screen is already showing, so a normal finish costs one screenshot.
        """
        try:
            if self._recover_unknown_screen(session):
                self._log(f"「{name}」结束后已退回主界面，下一项可以正常开始。", "warn")
        except Exception as error:  # noqa: BLE001 - never abort a run for this
            self._log(f"「{name}」结束后退回主界面失败（不影响后续）：{error}", "warn")

    def _recover_after_failure(self, session: LiteSession, name: str) -> None:
        try:
            if self._handle_anr(session):
                self._log(f"「{name}」失败时游戏无响应，已点“等待”，后续任务继续。", "warn")
                return
            if self._recover_unknown_screen(session):
                self._log(f"「{name}」失败后已退出未知界面，后续任务继续。", "warn")
        except Exception as error:  # noqa: BLE001 - recovery must never abort a run
            self._log(f"「{name}」的失败恢复流程出错（不影响后续任务）：{error}", "warn")

    def _classify_result(
        self,
        session: LiteSession,
        name: str,
        result: dict[str, Any],
        duration: float,
    ) -> dict[str, Any]:
        """Turn a run_task result into a status plus the side effects it needs.

        Single place for the ordering: stuck-loop guard, agent death, cancel,
        success, timeout, stamina dialog, plain failure. Both run loops call
        this, so a new outcome only has to be handled once.
        """
        outcome: dict[str, Any] = {
            "status": "failed",
            "reason": "失败",
            "restart_failed": False,
        }
        # 体力弹窗 / 鸟食断供都会走到这里，二者都算「资源不足提前收手」。
        resource_short = False

        if self._guard_event.is_set() and not self._cancel.is_set():
            outcome["reason"] = f"疑似死循环（{self._guard_node}）"
            self._log(
                f"任务被中止：{name}（{duration}s），"
                f"节点「{self._guard_node}」重复超限，疑似死循环。",
                "error",
            )
            self._capture_failure(session, name)
        elif result.get("agent_died"):
            outcome["reason"] = "Agent 异常退出"
            self._log(f"Agent 异常退出，任务中止：{name}（{duration}s）。", "error")
            self._capture_failure(session, name)
            if session.restart_agent():
                self._log("Agent 已重启，继续后续任务。")
            else:
                self._log("Agent 重启失败，本次运行停止。", "error")
                outcome["restart_failed"] = True
        elif result.get("cancelled"):
            outcome["status"] = "cancelled"
            outcome["reason"] = "已停止"
            self._log(f"任务已停止：{name}", "warn")
        elif result.get("success"):
            outcome["status"] = "succeeded"
            outcome["reason"] = "完成"
            self._log(f"任务完成：{name}（{duration}s）")
        elif result.get("stalled"):
            # Nothing moved for STALL_SECONDS. Check the stamina dialog first:
            # it is by far the most common cause and ends the task cleanly.
            if _consumes_stamina(name) and self._stamina_exhausted(session):
                outcome["status"] = "succeeded"
                outcome["reason"] = "体力耗尽，已结束"
                resource_short = True
                self._log(f"体力耗尽，任务结束：{name}（{duration}s）")
                self._back_to_main(session, name)
            else:
                # 记录实际停顿秒数：阈值只是下限，真实值能区分「刚好超线」
                # 和「彻底卡死」，复跑对比时有用。
                stalled_for = int(time.monotonic() - self._last_node_time)
                outcome["status"] = "failed"
                outcome["reason"] = f"无响应 {stalled_for} 秒"
                self._log(
                    f"任务已有 {stalled_for} 秒没有任何进展，判定卡住并中止：{name}。"
                    "常见原因是未识别的弹窗盖住了界面，可查看错误截图。",
                    "error",
                )
                # 横屏 + 完全没进展，几乎只有一种情况：模拟器被重启、游戏没了，
                # 界面停在横屏桌面。此时继续跑剩下的任务，只是把 150 秒乘以任务数。
                if self._warn_if_landscape(session):
                    outcome["aborted"] = True
                    outcome["reason"] = "横屏桌面，游戏可能未启动"
                    self._log(
                        "界面停在横屏桌面（游戏未运行），本轮余下任务不再执行。",
                        "error",
                    )
                    self._capture_failure(session, name)
                else:
                    self._capture_failure(session, name)
                    self._recover_after_failure(session, name)
        elif result.get("timed_out"):
            outcome["status"] = "timed_out"
            outcome["reason"] = "超时"
            self._log(f"任务超时：{name}（{duration}s），继续后续任务。", "error")
            self._capture_failure(session, name)
            self._recover_after_failure(session, name)
        elif _consumes_stamina(name) and self._stamina_exhausted(session):
            outcome["status"] = "succeeded"
            outcome["reason"] = "体力耗尽，已结束"
            resource_short = True
            self._log(f"体力耗尽，任务结束：{name}（{duration}s）")
            self._back_to_main(session, name)
        else:
            self._log(f"任务失败：{name}（{duration}s），继续后续任务。", "error")
            # A landscape screen explains a whole run of failures; say it here
            # rather than leaving the user with "recognition failed" x8.
            self._warn_if_landscape(session)
            self._capture_failure(session, name)
            self._recover_after_failure(session, name)

        # 「跑完」和「拿到奖励」是两件事（用户 2026-11-07 定义）：资源不足导致
        # 提前收手的任务单独记一个状态，既不算失败，也不冒充成功。
        #
        # 只认吃体力的任务：`new不吃鸟食` 这个名字密探特训也在用（focus 是
        # 「行动次数已耗尽」），那是"今天已经做过一轮"，不是没拿到资源。
        if (
            outcome["status"] == "succeeded"
            and _consumes_stamina(name)
            and not _is_grind(name)
        ):
            if resource_short or self._resource_hit:
                outcome["status"] = "skipped_no_resource"
                outcome["reason"] = "资源不足，未领取到资源"
                self._log(f"资源不足，未领取到资源：{name}（{duration}s）", "warn")

        return outcome

    def _warn_if_landscape(self, session: LiteSession | None = None) -> bool:
        """Upstream ROIs assume a portrait 720x1280 screen.

        A landscape emulator makes every recognition miss while the framework
        only reports ``roi is out of range``, which reads like a bug in Lite.
        Say it plainly once instead of letting eight tasks fail silently.
        """
        path = getattr(self, "_last_screenshot", None)
        if path is None:
            return False
        if session is not None:
            try:
                session.capture_png(path)
            except Exception:  # noqa: BLE001 - a missing screenshot is not fatal
                return False
        size = _png_size(path)
        if size is None:
            return False
        width, height = size
        if width <= height:
            return False
        self._log(
            f"模拟器当前是横屏 {width}x{height}，资源按竖屏 720x1280 制作，"
            f"识别会全部失败。请把模拟器分辨率改为 720x1280 并重启后再运行。",
            "error",
        )
        return True

    def _check_connection(self, previous_status: str = "idle") -> None:
        session = self._make_session()
        with self._lock:
            self._session = session
        try:
            self._log("正在连接模拟器并启动 Agent……")
            session.start()
            session.capture_png(self._last_screenshot)
            self._log("连接成功，截图已保存：runtime/last-screen.png")
            restored = previous_status
            if restored in {"checking", "starting", "running"}:
                restored = "idle"
            with self._lock:
                self._status = restored
        except Exception as error:
            self._log(f"连接检查失败：{error}", "error")
            with self._lock:
                self._status = "error"
        finally:
            session.stop()
            with self._lock:
                self._session = None
                self._current_task = ""

    def _resume_mismatch(
        self, plan: dict[str, Any], by_name: dict[str, Any]
    ) -> str | None:
        """Why the saved run cannot be resumed, or None when it can.

        The daily chain is addressed by index, so a profile edit (different
        training type, dungeon toggled) shifts every task by one. Resuming then
        silently runs the wrong task with the wrong options.
        """
        planned = plan.get("tasks", [])
        if len(planned) != len(self._tasks):
            return f"任务数量从 {len(self._tasks)} 变成 {len(planned)}"
        for index, item in enumerate(planned):
            saved = self._tasks[index]["name"]
            if saved != item["name"]:
                return f"第 {index + 1} 项由「{saved}」变成「{item['name']}」"
            if item["name"] not in by_name:
                return f"当前资源里没有任务「{item['name']}」"
        return None

    def _run_daily(
        self,
        training: str,
        include_dungeon: bool,
        resume: bool = False,
        names: list[str] | None = None,
        extra: list[str] | None = None,
    ) -> None:
        interface = json.loads(
            (self.project_root / "build" / "generated" / "interface.json").read_text(
                encoding="utf-8"
            )
        )
        options = load_options_snapshot()
        inputs = load_inputs()
        by_name = {task["name"]: task for task in interface["task"]}
        resumed = False
        if resume and self._plan is not None and self._tasks:
            plan = self._plan
            problem = self._resume_mismatch(plan, by_name)
            if problem:
                self._log(
                    f"上次的运行记录与当前任务对不上（{problem}），这次重新开始整条日常。",
                    "warn",
                )
            else:
                with self._lock:
                    for task in self._tasks:
                        if task["status"] != "succeeded":
                            task.update(
                                {"status": "pending", "duration": 0, "attempts": 0}
                            )
                self._log("继续上次未完成的日常：已完成的任务会跳过。", "warn")
                resumed = True
        if not resumed:
            profile = load_profile()
            plan = build_plan(
                profile, training=training, include_seasonal=include_dungeon
            )
            # 界面现在允许勾选今天想做的任务：按 plan 顺序取子集，未选中的直接不跑。
            if names is not None:
                wanted = [name for name in names if name]
                available = {item["name"] for item in plan["tasks"]}
                missing = [name for name in wanted if name not in available]
                if missing:
                    self._log(
                        f"这些任务今天不在计划里，已忽略：{'、'.join(missing)}", "warn"
                    )
                chosen = set(wanted)
                plan = {
                    **plan,
                    "tasks": [item for item in plan["tasks"] if item["name"] in chosen],
                    "count": sum(1 for item in plan["tasks"] if item["name"] in chosen),
                }

            # 「其他任务」的勾选接在日常之后，共用同一个 session：日常链的
            # 探测、档位、超时表照旧，结束动作只在最后执行一次。
            if extra:
                known = {item["name"] for item in plan["tasks"]}
                appended: list[dict[str, Any]] = []
                for name in extra:
                    if not name or name in known:
                        continue
                    task_def = by_name.get(name)
                    if task_def is None or task_def.get("entry") == "stop":
                        self._log(f"其他任务里没有「{name}」，已忽略。", "warn")
                        continue
                    known.add(name)
                    appended.append(
                        {
                            "name": name,
                            "kind": "extra",
                            "on_unavailable": "skip",
                            "timeout_sec": None,
                            "retries": 0,
                        }
                    )
                if appended:
                    self._log(
                        f"日常之后接着执行其他任务：{' → '.join(item['name'] for item in appended)}"
                    )
                    plan = {
                        **plan,
                        "tasks": plan["tasks"] + appended,
                        "count": len(plan["tasks"]) + len(appended),
                    }

            if not plan["tasks"]:
                self._log("没有可执行的任务，本次运行结束。", "warn")

            with self._lock:
                self._tasks = [
                    {
                        "name": item["name"],
                        "kind": item.get("kind", "daily"),
                        "status": "pending",
                        "duration": 0,
                        "attempts": 0,
                        "timeout": timeout_for(item["name"], item.get("timeout_sec")),
                    }
                    for item in plan["tasks"]
                ]
                self._plan = plan
        for skipped in plan["skipped"]:
            reason = {
                "seasonal_daily_disabled": "活动未开启",
                "time_window_closed": "不在开放时段",
            }.get(skipped.get("reason"), skipped.get("reason"))
            self._log(f"跳过 {skipped['name']}：{reason}。", "warn")

        session = self._make_session()
        with self._lock:
            self._session = session
            self._status = "running"
        failures = 0
        cancelled = False
        aborted = False

        try:
            # Fail before touching the emulator: a renamed or missing task means
            # the plan and the resources disagree, and the old code only found
            # out mid-run with "Generated interface is missing task".
            missing = [item["name"] for item in plan["tasks"] if item["name"] not in by_name]
            if missing:
                listed = "、".join(missing[:3]) + ("……" if len(missing) > 3 else "")
                self._update_run(
                    status="error", summary={"error": f"资源缺少任务：{missing[0]}"}
                )
                self._log(
                    f"任务列表与当前资源不匹配，缺少：{listed}。"
                    f"请检查资源是否完整（可用「检查更新」重新获取），或重新生成 interface。",
                    "error",
                )
                return

            self._log(f"历练选择：{training}；地宫：{'开启' if include_dungeon else '关闭'}")
            self._log("正在连接模拟器并启动 Agent……")
            session.start()
            self._log("连接成功，开始执行日常链。")

            for index, item in enumerate(plan["tasks"]):
                if self._cancel.is_set():
                    cancelled = True
                    break
                name = item["name"]
                task_def = by_name.get(name)
                if task_def is None:
                    raise RuntimeError(f"Generated interface is missing task: {name}")

                task_state = self._tasks[index]
                if task_state["status"] == "succeeded":
                    self._log(f"已完成，跳过：{name}")
                    continue

                if not self._ensure_ready(session):
                    self._update_task(index, status="failed")
                    self._update_run(status="error")
                    aborted = True
                    self._persist()
                    break

                with self._lock:
                    self._current_task = name
                    task_state["status"] = "running"
                started = time.monotonic()

                probe = item.get("probe")
                if probe:
                    try:
                        available = session.probe(
                            probe.get("checks", []),
                            int(probe.get("timeout_ms", 1500)),
                        )
                    except Exception as error:
                        self._log(
                            f"入口探测失败（{error}），继续执行 {name}。", "warn"
                        )
                        available = True
                    if not available:
                        # 记一个 note：控制条的地宫开关是持久化的，活动结束后用户
                        # 从界面上看不出来 —— 标出来才好在下次启动前把开关关掉。
                        self._update_task(
                            index,
                            status="skipped",
                            note="本期未开放",
                            duration=round(time.monotonic() - started, 1),
                        )
                        self._log(
                            f"未检测到{probe.get('label', '活动入口')}"
                            f"（活动可能未开放，或当前不在主界面），已跳过：{name}",
                            "warn",
                        )
                        self._persist()
                        continue

                selected = options.get(name, {})
                option_notes: list[str] = []
                override = apply_pipeline_fixes(
                    task_def["entry"],
                    build_task_override(
                        interface, task_def, selected, inputs.get(name, {}), option_notes
                    ),
                )
                self._report_option_notes(name, option_notes)
                timeout = task_state["timeout"]
                retries = int(item.get("retries", 0))
                outcome, duration, result = self._execute_job(
                    session,
                    name=name,
                    entry=task_def["entry"],
                    override=override,
                    timeout=timeout,
                    retries=retries,
                    started=started,
                )
                self._update_task(
                    index,
                    duration=duration,
                    attempts=result.get("attempt", 1),
                    status=outcome["status"],
                )
                if outcome["status"] in {"failed", "timed_out"}:
                    failures += 1
                if outcome["status"] == "cancelled":
                    cancelled = True
                    self._persist()
                    break
                if outcome["restart_failed"] or outcome.get("aborted"):
                    self._update_run(status="error")
                    aborted = True
                    self._persist()
                    break
                self._persist()

            if self._cancel.is_set() and not aborted:
                # Stop was requested while the last task was still running; the
                # loop has no next iteration to notice it.
                cancelled = True

            succeeded, failed, skipped = self._tally()
            self._finalize_run(
                aborted=aborted,
                cancelled=cancelled,
                succeeded=succeeded,
                failed=failed,
                skipped=skipped,
            )
            if not aborted:
                if cancelled:
                    self._log("本次运行已停止。", "warn")
                else:
                    extra = f"，未领取 {skipped} 项" if skipped else ""
                    self._log(
                        f"日常链结束：成功 {succeeded} 项，失败 {failed} 项{extra}。",
                        "warn" if failed else "info",
                    )
                    if load_settings().get("shutdown_action", "none") == "none":
                        self._log("程序保持运行，不会自动关闭。")
        except Exception as error:
            self._update_run(status="error", summary={"error": str(error)})
            self._log(f"运行异常：{error}", "error")
        finally:
            session.stop()
            with self._lock:
                self._session = None
                self._current_task = ""
                self._finished_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                finished_status = self._status
            self._persist()
            if finished_status != "cancelled":
                self._run_exit_actions()

    def _run_exit_actions(self) -> None:
        action = load_settings().get("shutdown_action", "none")
        if action == "close_both":
            self._close_emulator()
        if action in ("close_maa", "close_both"):
            self._log("按设置关闭控制台……", "warn")
            if self._shutdown_hook is not None:
                threading.Timer(4.0, self._shutdown_hook).start()

    def _close_emulator(self) -> None:
        adb = Path(self.config.get("adb_path", ""))
        serial = self.config.get("adb_serial", "emulator-5554")
        if not adb.is_file():
            self._log("找不到 adb，无法关闭模拟器。", "warn")
            return
        try:
            subprocess.run(
                [str(adb), "-s", serial, "emu", "kill"],
                timeout=20,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self._log("已发送关闭模拟器指令（adb emu kill）。", "warn")
        except Exception as error:
            self._log(f"关闭模拟器失败：{error}", "warn")
