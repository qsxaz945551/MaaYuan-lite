"""Threaded run service used by the lightweight local UI."""

from __future__ import annotations

import json
import subprocess
import threading
import time
from collections import deque
from datetime import datetime
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
        self._logs: deque[dict[str, Any]] = deque(maxlen=2000)
        self._log_seq = 0
        # Stable per process; clients use a change to resync after a restart.
        self._run_id = int(time.time_ns() % 1_000_000_000)
        self._status = "idle"
        self._current_task = ""
        self._tasks: list[dict[str, Any]] = []
        self._plan: dict[str, Any] | None = None
        self._single: dict[str, Any] | None = None
        self._summary: dict[str, Any] = {}
        self._preview: list[dict[str, Any]] | None = None
        self._started_at = ""
        self._finished_at = ""
        self._last_screenshot = self.project_root / "runtime" / "last-screen.png"
        self._state_file = self.project_root / "runtime" / "last-run.json"
        self._shutdown_hook: Any = None
        self._load_last_run()

    def set_shutdown_hook(self, hook: Any) -> None:
        self._shutdown_hook = hook

    def _log(self, message: str, level: str = "info") -> None:
        with self._lock:
            self._log_seq += 1
            self._logs.append(
                {
                    "seq": self._log_seq,
                    "time": datetime.now().strftime("%H:%M:%S"),
                    "level": level,
                    "message": message,
                }
            )

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
                training=str(settings.get("last_training", "修为")),
                include_seasonal=bool(settings.get("last_dungeon", False)),
            )
            preview = []
            for item in plan["tasks"]:
                timeout = item.get("timeout_sec")
                if timeout is None:
                    timeout = DEFAULT_TIMEOUTS.get(item["name"], 1800)
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
        self, training: str, include_dungeon: bool, resume: bool = False
    ) -> bool:
        if self._busy():
            return False
        if training not in {"修为", "铜钱", "经验"}:
            raise ValueError("Invalid training choice")
        if resume and not self.can_resume():
            return False
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
            args=(training, include_dungeon, resume),
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

    def run_single(self, task_name: str, timeout_sec: float = 1800) -> bool:
        return self.run_sequence([task_name], timeout_sec)

    def run_sequence(self, task_names: list[str], timeout_sec: float = 1800) -> bool:
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
            override = build_task_override(
                interface, task, options.get(task_name, {}), inputs.get(task_name, {})
            )
            jobs.append(
                {
                    "name": task_name,
                    "entry": task["entry"],
                    "override": apply_pipeline_fixes(task["entry"], override),
                    "timeout": (
                        DEFAULT_TIMEOUTS[task_name]
                        if task_name in DEFAULT_TIMEOUTS
                        else timeout_sec
                    ),
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

    def _run_sequence(self, jobs: list[dict[str, Any]]) -> None:
        session = self._make_session()
        with self._lock:
            self._session = session
            self._status = "running"
            self._single["status"] = "running"
        total = len(jobs)
        failures = 0
        aborted = False
        try:
            session.start()
            if self._warn_if_landscape(session):
                with self._lock:
                    self._status = "error"
                    self._single["status"] = "failed"
                self._log("已中止：改正模拟器分辨率后重新开始。", "error")
                return
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
                self._log(f"单独运行{suffix}：{name}")
                started = time.monotonic()
                session.set_node_callback(self._make_round_handler(job["entry"]))
                self._start_guard(session, job["entry"])
                try:
                    result = session.run_task(
                        entry=job["entry"],
                        pipeline_override=job["override"],
                        timeout_sec=job["timeout"],
                        retries=0,
                        should_stop=self._guard_stop,
                        agent_check=session.agent_alive,
                    )
                finally:
                    session.set_node_callback(None)
                    session.set_node_start_callback(None)
                duration = round(time.monotonic() - started, 1)
                outcome = self._classify_result(session, name, result, duration)
                status = outcome["status"]
                restart_failed = outcome["restart_failed"]
                if status in {"failed", "timed_out"}:
                    failures += 1
                with self._lock:
                    self._single["results"].append(
                        {"name": name, "status": status, "duration": duration}
                    )
                    self._single["duration"] = round(
                        sum(item["duration"] for item in self._single["results"]), 1
                    )
                    self._single["status"] = status
                if status == "cancelled" or restart_failed:
                    aborted = aborted or restart_failed
                    break

            with self._lock:
                if aborted:
                    self._status = "error"
                elif self._cancel.is_set():
                    self._status = "cancelled"
                elif failures:
                    self._status = "completed_with_errors"
                else:
                    self._status = "completed"
                done = len(self._single["results"])
                if total > 1:
                    self._log(f"批量结束：共 {total} 项，成功 {done - failures} 项，失败 {failures} 项。")
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
        """Log one line per completed round for loop tasks, if configured."""
        labels = marker_labels(entry)
        if not labels:
            return None
        counter = {"n": 0}
        lock = threading.Lock()

        def handle(node_name: str) -> None:
            label = labels.get(node_name)
            if label is None:
                return
            with lock:
                counter["n"] += 1
                count = counter["n"]
            self._log(f"第 {count} 轮完成（{label}）")

        return handle

    def _stamina_exhausted(self, session: LiteSession) -> bool:
        """True when the stamina refill dialog is on screen.

        Farming tasks ("刷到体力耗尽") are supposed to end here; without this
        check the framework reports a recognition failure instead.
        """
        check = getattr(session, "has_stamina_dialog", None)
        if check is None:
            return False
        try:
            return bool(check())
        except Exception:
            return False

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

    def _recover_after_failure(self, session: LiteSession, name: str) -> None:
        try:
            if self._recover_unknown_screen(session):
                self._log(f"「{name}」失败后已退出未知界面，后续任务继续。", "warn")
        except Exception:  # noqa: BLE001
            pass

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
        elif result.get("timed_out"):
            outcome["status"] = "timed_out"
            outcome["reason"] = "超时"
            self._log(f"任务超时：{name}（{duration}s），继续后续任务。", "error")
            self._capture_failure(session, name)
            self._recover_after_failure(session, name)
        elif self._stamina_exhausted(session):
            outcome["status"] = "succeeded"
            outcome["reason"] = "体力耗尽，已结束"
            self._log(f"体力耗尽，任务结束：{name}（{duration}s）")
        else:
            self._log(f"任务失败：{name}（{duration}s），继续后续任务。", "error")
            self._capture_failure(session, name)
            self._recover_after_failure(session, name)

        return outcome

    def _warn_if_landscape(self, session: LiteSession | None = None) -> bool:
        """Upstream ROIs assume a portrait 720x1280 screen.

        A landscape emulator makes every recognition miss while the framework
        only reports ``roi is out of range``, which reads like a bug in Lite.
        Say it plainly once instead of letting eight tasks fail silently.
        """
        path = self._last_screenshot
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
            self._warn_if_landscape()
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

    def _run_daily(
        self, training: str, include_dungeon: bool, resume: bool = False
    ) -> None:
        interface = json.loads(
            (self.project_root / "build" / "generated" / "interface.json").read_text(
                encoding="utf-8"
            )
        )
        options = load_options_snapshot()
        inputs = load_inputs()
        if resume and self._plan is not None and self._tasks:
            plan = self._plan
            with self._lock:
                for task in self._tasks:
                    if task["status"] != "succeeded":
                        task.update({"status": "pending", "duration": 0, "attempts": 0})
            self._log("继续上次未完成的日常：已完成的任务会跳过。", "warn")
        else:
            profile = load_profile()
            plan = build_plan(
                profile, training=training, include_seasonal=include_dungeon
            )
            with self._lock:
                self._tasks = [
                    {
                        "name": item["name"],
                        "kind": item.get("kind", "daily"),
                        "status": "pending",
                        "duration": 0,
                        "attempts": 0,
                        "timeout": (
                            item.get("timeout_sec")
                            if item.get("timeout_sec") is not None
                            else DEFAULT_TIMEOUTS.get(item["name"], 1800)
                        ),
                    }
                    for item in plan["tasks"]
                ]
                self._plan = plan
        by_name = {task["name"]: task for task in interface["task"]}
        for skipped in plan["skipped"]:
            self._log(f"跳过 {skipped['name']}：地宫开放期未开启。", "warn")

        session = self._make_session()
        with self._lock:
            self._session = session
            self._status = "running"
        failures = 0
        cancelled = False
        aborted = False

        try:
            self._log(f"历练选择：{training}；地宫：{'开启' if include_dungeon else '关闭'}")
            self._log("正在连接模拟器并启动 Agent……")
            session.start()
            self._log("连接成功，开始执行日常链。")
            if self._warn_if_landscape(session):
                with self._lock:
                    self._status = "error"
                    self._summary = {"error": "屏幕方向不对（横屏）"}
                self._log("已中止：改正模拟器分辨率后重新开始日常。", "error")
                return

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
                    task_state["status"] = "failed"
                    with self._lock:
                        self._status = "error"
                    aborted = True
                    self._persist()
                    break

                with self._lock:
                    self._current_task = name
                    task_state["status"] = "running"
                started = time.monotonic()
                self._log(f"开始任务：{name}")

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
                        task_state["status"] = "skipped"
                        task_state["duration"] = round(
                            time.monotonic() - started, 1
                        )
                        self._log(
                            f"未检测到{probe.get('label', '活动入口')}"
                            f"（活动可能未开放，或当前不在主界面），已跳过：{name}",
                            "warn",
                        )
                        self._persist()
                        continue

                selected = options.get(name, {})
                override = apply_pipeline_fixes(
                    task_def["entry"],
                    build_task_override(
                        interface, task_def, selected, inputs.get(name, {})
                    ),
                )
                timeout = task_state["timeout"]
                retries = int(item.get("retries", 0))
                session.set_node_callback(
                    self._make_round_handler(task_def["entry"])
                )
                self._start_guard(session, task_def["entry"])
                try:
                    result = session.run_task(
                        entry=task_def["entry"],
                        pipeline_override=override,
                        timeout_sec=timeout,
                        retries=retries,
                        should_stop=self._guard_stop,
                        agent_check=session.agent_alive,
                    )
                finally:
                    session.set_node_callback(None)
                    session.set_node_start_callback(None)
                duration = round(time.monotonic() - started, 1)
                task_state["duration"] = duration
                task_state["attempts"] = result.get("attempt", 1)

                outcome = self._classify_result(session, name, result, duration)
                task_state["status"] = outcome["status"]
                if outcome["status"] in {"failed", "timed_out"}:
                    failures += 1
                if outcome["status"] == "cancelled":
                    cancelled = True
                    self._persist()
                    break
                if outcome["restart_failed"]:
                    with self._lock:
                        self._status = "error"
                    aborted = True
                    self._persist()
                    break
                self._persist()

            if self._cancel.is_set() and not aborted:
                # Stop was requested while the last task was still running; the
                # loop has no next iteration to notice it.
                cancelled = True

            if aborted:
                succeeded = sum(
                    1 for task in self._tasks if task["status"] == "succeeded"
                )
                failed = sum(
                    1 for task in self._tasks
                    if task["status"] in {"failed", "timed_out"}
                )
                self._status = "error"
                self._summary = {"succeeded": succeeded, "failed": failed}
            elif cancelled:
                succeeded = sum(
                    1 for task in self._tasks if task["status"] == "succeeded"
                )
                failed = sum(1 for task in self._tasks if task["status"] in {"failed", "timed_out"})
                self._status = "cancelled"
                self._summary = {"succeeded": succeeded, "failed": failed}
                self._log("本次运行已停止。", "warn")
            else:
                succeeded = sum(
                    1 for task in self._tasks if task["status"] == "succeeded"
                )
                failed = sum(1 for task in self._tasks if task["status"] in {"failed", "timed_out"})
                self._status = "completed_with_errors" if failed else "completed"
                self._summary = {"succeeded": succeeded, "failed": failed}
                self._log(
                    f"日常链结束：成功 {succeeded} 项，失败 {failed} 项。",
                    "warn" if failed else "info",
                )
                if load_settings().get("shutdown_action", "none") == "none":
                    self._log("程序保持运行，不会自动关闭。")
        except Exception as error:
            self._status = "error"
            self._summary = {"error": str(error)}
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
