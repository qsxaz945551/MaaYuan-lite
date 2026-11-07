"""MaaYuan Lite initial local control panel."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent
RUN_STATES = (
    "idle",
    "starting",
    "running",
    "checking",
    "completed",
    "completed_with_errors",
    "cancelled",
    "error",
    "interrupted",
)
TASK_STATES = ("pending", "running", "succeeded", "failed", "timed_out", "skipped", "cancelled")
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lite.daily_plan import build_plan, load_profile
from lite.http_body import read_body
from lite.run_service import RunService
from lite.settings import (
    SHUTDOWN_ACTIONS,
    STARTUP_ACTIONS,
    from_wire,
    load_settings,
    save_settings,
    to_wire,
)
from lite.version import API_VERSION, VERSION

APP_VERSION = VERSION
from lite.task_options_service import (
    DEFAULT_INPUTS,
    DEFAULT_SELECTION,
    OptionError,
    apply_change,
    describe_tasks,
    load_inputs,
    load_selection,
    write_json,
)


UI_FILE = ROOT / "lite" / "ui" / "index.html"
CONFIG_FILE = ROOT / "lite" / "runtime-config.json"
INTERFACE_FILE = ROOT / "build" / "generated" / "interface.json"
OPTION_LOCK = threading.Lock()


_HEALTH_CACHE: dict[str, object] = {"at": 0.0, "data": None}


def _managed_resource_root(config: dict) -> Path:
    value = str(config.get("resource_root") or "").strip()
    return Path(value) if value else ROOT / "assets" / "resource" / "base"


def _bundle_owns_resources(config: dict) -> bool:
    """True when the running resources are the bundle's own copy.

    A dev checkout points ``resource_root`` at ``vendor/MaaYuan-src``; swapping
    ``assets/`` there would update a tree the runtime never reads, so the
    updater refuses instead of pretending to work.
    """
    try:
        return _managed_resource_root(config).resolve() == (
            ROOT / "assets" / "resource" / "base"
        ).resolve()
    except OSError:
        return False


def _apply_staged_resources(config: dict) -> tuple[str, str] | None:
    """Switch to a downloaded resource tree before anything opens the pipeline.

    Returns ``(message, level)`` for the run log: this happens before the
    service exists, so the shell only sees it after the fact. Without that line
    the resource tree silently changes under the user between two launches.
    """
    from lite.update_applier import apply_staged, cleanup_partial, has_staged

    cleanup_partial(ROOT)
    if not has_staged(ROOT):
        return None
    if not _bundle_owns_resources(config):
        message = "检测到待生效资源，但当前配置指向开发目录，已跳过自动切换（用 devtools/sync_repo.py --update）。"
        print(message, file=sys.stderr)
        return message, "warn"

    result = apply_staged(ROOT, str(config.get("interface_source", "")))
    if not result.get("ok"):
        problems = result.get("problems") or []
        detail = f"（{'；'.join(str(item) for item in problems[:3])}）" if problems else ""
        message = f"资源切换失败，继续使用旧版本：{result.get('error')}{detail}"
        print(message, file=sys.stderr)
        return message, "warn"

    ok, detail = _rebuild_interface()
    if not ok:
        # The gate checked the tree, but a broken interface still means the new
        # resources cannot be used. Go back rather than run on half a bundle.
        from lite.update_applier import rollback

        restored = rollback(ROOT)
        _rebuild_interface()
        message = (
            f"新资源无法生成 interface（{detail}），"
            f"{'已回滚到旧版本' if restored else '回滚失败，请手动恢复 assets.prev'}"
        )
        print(message, file=sys.stderr)
        return message, "error"

    extras = result.get("restoredExtras") or []
    message = (
        f"已切换到新资源（agent {'已' if result.get('agentSwapped') else '未'}替换），"
        f"interface 重建成功"
        f"{f'，补回 {len(extras)} 个本地文件' if extras else ''}。"
    )
    print(message, flush=True)
    return message, "info"


def _ensure_interface(config: dict) -> None:
    """Rebuild the scoped interface when the source is newer than the output.

    The WPF shell starts app.py directly, so this cannot live in a .bat file:
    an update or a manual resource refresh must not leave a stale task list.
    """
    generated = ROOT / "build" / "generated" / "interface.json"
    source_value = str(config.get("interface_source") or "").strip()
    source = Path(source_value) if source_value else ROOT / "assets" / "interface.json"
    try:
        if generated.is_file() and (
            not source.is_file() or generated.stat().st_mtime >= source.stat().st_mtime
        ):
            return
    except OSError:
        pass
    ok, detail = _rebuild_interface()
    if not ok:
        print(f"interface 重建失败：{detail}", file=sys.stderr)


def _rebuild_interface() -> tuple[bool, str]:
    """Regenerate build/generated/interface.json after resources changed."""
    try:
        result = subprocess.run(
            [sys.executable, str(ROOT / "lite" / "apply_scope.py")],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
        )
    except (OSError, subprocess.SubprocessError) as error:
        return False, str(error)
    if result.returncode != 0:
        return False, (result.stderr or result.stdout).strip()[:400]
    return True, result.stdout.strip()[:400]


def load_config() -> dict:
    with CONFIG_FILE.open("r", encoding="utf-8-sig") as handle:
        config = json.load(handle)
    # Relative paths are resolved against the project root, not the current
    # working directory: the bundle must behave the same when started from
    # Explorer, a shortcut, or the WPF shell.
    for key in (
        "runtime_root",
        "adb_path",
        "resource_path",
        "resource_root",
        "agent_root",
        "interface_source",
    ):
        value = str(config.get(key) or "").strip()
        if not value:
            continue
        path = Path(value)
        config[key] = str(path if path.is_absolute() else (ROOT / path).resolve())

    from lite.adb_finder import find_adb

    adb, source = find_adb(str(config.get("adb_path") or ""), ROOT)
    if adb is not None:
        config["adb_path"] = str(adb)
        config["adb_source"] = source
    return config


def load_interface() -> dict:
    return json.loads(INTERFACE_FILE.read_text(encoding="utf-8"))


def daily_task_names() -> list[str]:
    """Every task that can appear in the daily chain, including all training types."""
    names: list[str] = []
    for item in load_profile()["daily_order"]:
        kind = item.get("type")
        if kind == "task":
            names.append(item["name"])
        elif kind == "choice":
            names.extend(item.get("options", []))
        elif kind == "optional_task":
            names.append(item["name"])
    return names


def seasonal_default_enabled() -> bool:
    """Read the seasonal-daily default from the profile instead of hardcoding."""
    try:
        profile = load_profile()
    except Exception:
        return False
    for item in profile.get("daily_order", []):
        if item.get("type") == "optional_task":
            return bool(item.get("default_enabled", False))
    return False


def _auto_start(service: RunService, settings: dict, delay: float) -> None:
    import time

    time.sleep(delay)
    if service.snapshot().get("busy"):
        return
    service.start_daily(
        training=str(settings.get("last_training") or "修为"),
        include_dungeon=bool(settings.get("last_dungeon")),
    )


def _close_app_window(title: str = "MaaYuan Lite") -> None:
    """Ask the Edge app window to close (used by the "结束后关闭MAA" action)."""
    import ctypes
    import ctypes.wintypes as wt

    user32 = ctypes.windll.user32
    handles: list[int] = []
    callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)

    def callback(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        buffer = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(hwnd, buffer, 256)
        if buffer.value == title:
            handles.append(hwnd)
        return True

    entry = callback_type(callback)
    user32.EnumWindows(entry, 0)
    for hwnd in handles:
        user32.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE


def open_ui(url: str) -> None:
    """Open the legacy web console in the default browser.

    Only ``start-lite.bat --legacy`` reaches this: the WPF shell owns its own
    window, so there is no Edge app mode or window sizing to manage here.
    """
    webbrowser.open(url)


class LiteHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    # Windows lets several processes bind the same port when address reuse is
    # enabled, which silently splits requests across stale control-panel
    # instances. Refuse the second bind instead.
    allow_reuse_address = False


def make_handler(service: RunService, server_ref: list[LiteHTTPServer]):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            return

        def _json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK):
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _error(self, code: str, message: str, status: HTTPStatus) -> None:
            """Stable machine code + human message.

            ``error`` keeps its string form so the existing HTML console keeps
            working; ``code`` is what the WPF client branches on.
            """
            self._json({"ok": False, "error": message, "code": code}, status)

        def _sse(self, service: RunService) -> None:
            """Server-sent events: status + new log lines, one event per second.

            The JSON payload mirrors /api/state for the fields a client needs to
            update live; tasks are still fetched from /api/state because they
            change rarely and the array is large.
            """
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            cursor = service.log_cursor()
            last_ping = time.monotonic()
            try:
                while True:
                    snapshot = service.snapshot(cursor)
                    logs = snapshot.get("logs") or []
                    payload = {
                        "status": snapshot.get("status"),
                        "currentTask": snapshot.get("currentTask"),
                        "summary": snapshot.get("summary"),
                        "logSeq": snapshot.get("logSeq"),
                        "logs": logs,
                    }
                    body = json.dumps(payload, ensure_ascii=False)
                    self.wfile.write(f"event: state\ndata: {body}\n\n".encode("utf-8"))
                    self.wfile.flush()
                    if logs:
                        cursor = int(snapshot.get("logSeq") or cursor)
                    if time.monotonic() - last_ping > 15:
                        self.wfile.write(b": ping\n\n")
                        self.wfile.flush()
                        last_ping = time.monotonic()
                    time.sleep(1.0)
            except (BrokenPipeError, ConnectionResetError, OSError):
                return
            finally:
                self.close_connection = True

        def _read_json(self) -> dict:
            raw = read_body(self.rfile, self.headers)
            if not raw:
                return {}
            try:
                return json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise ValueError(f"请求体不是合法 JSON：{error}") from error

        def do_GET(self):
            parsed = urlparse(self.path)
            if parsed.path == "/":
                body = UI_FILE.read_bytes()
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
                return
            if parsed.path == "/api/state":
                query = parse_qs(parsed.query)
                raw_since = query.get("since", ["0"])[0]
                if raw_since == "latest":
                    since = service.log_cursor()
                else:
                    try:
                        since = int(raw_since)
                    except ValueError:
                        since = 0
                self._json(service.snapshot(since))
                return
            if parsed.path == "/api/plan":
                query = parse_qs(parsed.query)
                training = query.get("training", ["修为"])[0]
                dungeon_raw = query.get("dungeon")
                dungeon = (
                    seasonal_default_enabled()
                    if dungeon_raw is None
                    else dungeon_raw[0] != "0"
                )
                try:
                    plan = build_plan(
                        load_profile(), training=training, include_seasonal=dungeon
                    )
                    self._json(plan)
                except Exception as error:
                    self._error("PLAN_FAILED", str(error), HTTPStatus.BAD_REQUEST)
                return
            if parsed.path == "/api/events":
                self._sse(service)
                return
            if parsed.path == "/api/updates":
                query = parse_qs(parsed.query)
                force = query.get("refresh", ["0"])[0] == "1"
                from lite import downloader
                from lite.update_applier import has_staged
                from lite.updater import check_updates

                data = check_updates(ROOT, force=force)
                data["download"] = downloader.state()
                data["staged"] = has_staged(ROOT)
                self._json(data)
                return
            if parsed.path == "/api/health":
                query = parse_qs(parsed.query)
                force = query.get("refresh", ["0"])[0] == "1"
                now = time.time()
                if force or _HEALTH_CACHE["data"] is None or now - float(_HEALTH_CACHE["at"]) > 30:
                    from lite.selftest import collect

                    _HEALTH_CACHE["data"] = collect(ROOT, service.config)
                    _HEALTH_CACHE["at"] = now
                self._json(_HEALTH_CACHE["data"])
                return
            if parsed.path == "/api/meta":
                self._json(
                    {
                        "version": APP_VERSION,
                        "apiVersion": API_VERSION,
                        "runStates": list(RUN_STATES),
                        "taskStates": list(TASK_STATES),
                        "startupActions": list(STARTUP_ACTIONS),
                        "shutdownActions": list(SHUTDOWN_ACTIONS),
                        "trainingTypes": ["修为", "铜钱", "经验"],
                        # 稳定性脚本（devtools/stability_run.py）用它给自己的
                        # 进程采句柄与内存，省掉从 netstat 反查 PID 的脆弱路径。
                        "pid": os.getpid(),
                    }
                )
                return
            if parsed.path == "/api/settings":
                self._json(to_wire(load_settings()))
                return
            if parsed.path == "/api/task-options":
                query = parse_qs(parsed.query)
                scope = query.get("scope", ["daily"])[0]
                try:
                    interface = load_interface()
                    profile = load_profile()
                    hidden = list(profile.get("hidden_in_library") or [])
                    pinned = list(profile.get("pinned_in_library") or [])
                    if scope == "all":
                        names = [
                            task["name"]
                            for task in interface["task"]
                            if task.get("entry") != "stop"
                        ]
                    else:
                        scope = "daily"
                        names = daily_task_names()
                    self._json(
                        {
                            "scope": scope,
                            "tasks": describe_tasks(
                                interface, names, load_selection(), load_inputs()
                            ),
                            "hidden": hidden,
                            "pinned": pinned,
                        }
                    )
                except Exception as error:
                    self._error("OPTIONS_FAILED", str(error), HTTPStatus.BAD_REQUEST)
                return
            if parsed.path == "/api/screenshot":
                if service._last_screenshot.is_file():
                    body = service._last_screenshot.read_bytes()
                    self.send_response(HTTPStatus.OK)
                    self.send_header("Content-Type", "image/png")
                    self.send_header("Content-Length", str(len(body)))
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    self.wfile.write(body)
                else:
                    self._error("NO_SCREENSHOT", "还没有截图", HTTPStatus.NOT_FOUND)
                return
            self._error("NOT_FOUND", "接口不存在", HTTPStatus.NOT_FOUND)

        def do_POST(self):
            parsed = urlparse(self.path)
            try:
                payload = self._read_json()
                if parsed.path == "/api/note":
                    # 即时提示行会被下一次操作覆盖；失败提示要留一条运行日志，
                    # 前缀「界面：」用来和运行事件区分开。
                    message = str(payload.get("message") or "").strip()
                    level = str(payload.get("level") or "warn")
                    if level not in {"info", "warn", "error"}:
                        level = "warn"
                    if message:
                        service.note(f"界面：{message}", level)
                    self._json({"ok": bool(message)})
                    return
                if parsed.path == "/api/task-options":
                    with OPTION_LOCK:
                        interface = load_interface()
                        selection = load_selection()
                        inputs = load_inputs()
                        selection, inputs = apply_change(
                            interface, payload, selection, inputs
                        )
                        write_json(DEFAULT_SELECTION, selection)
                        group = interface.get("option", {}).get(
                            payload.get("group"), {}
                        )
                        if group.get("type") == "input":
                            write_json(DEFAULT_INPUTS, inputs)
                        updated = describe_tasks(
                            interface, [payload.get("task")], selection, inputs
                        )
                    self._json({"ok": True, "task": updated[0] if updated else None})
                    return
                if parsed.path == "/api/settings":
                    patch = from_wire(payload) if isinstance(payload, dict) else {}
                    self._json({"ok": True, "settings": to_wire(save_settings(patch))})
                    return
                if parsed.path == "/api/run-task":
                    names = payload.get("names")
                    if not isinstance(names, list):
                        names = [str(payload.get("name", ""))]
                    names = [str(name) for name in names if str(name).strip()]
                    try:
                        started = service.run_sequence(names)
                    except ValueError as error:
                        self._error("TASK_UNKNOWN", str(error), HTTPStatus.BAD_REQUEST)
                        return
                    if not started:
                        self._error("BUSY", "已有任务在运行", HTTPStatus.CONFLICT)
                        return
                    self._json({"ok": True})
                    return
                if parsed.path == "/api/start":
                    dungeon_value = payload.get("dungeon")
                    # 界面可以只跑勾选的子集；不传 names 就是整条日常（旧行为）。
                    raw_names = payload.get("names")
                    names = (
                        [str(name) for name in raw_names if str(name).strip()]
                        if isinstance(raw_names, list)
                        else None
                    )
                    # 「其他任务」的勾选：和日常一起提交，接在计划末尾执行。
                    raw_extra = payload.get("extra")
                    extra = (
                        [str(name) for name in raw_extra if str(name).strip()]
                        if isinstance(raw_extra, list)
                        else None
                    )
                    try:
                        started = service.start_daily(
                            training=str(payload.get("training", "修为")),
                            include_dungeon=(
                                seasonal_default_enabled()
                                if dungeon_value is None
                                else bool(dungeon_value)
                            ),
                            resume=bool(payload.get("resume", False)),
                            names=names,
                            extra=extra,
                        )
                    except ValueError as error:
                        self._error("BAD_SELECTION", str(error), HTTPStatus.BAD_REQUEST)
                        return
                    if started and not payload.get("resume"):
                        save_settings(
                            {
                                "last_training": str(payload.get("training", "修为")),
                                "last_dungeon": bool(dungeon_value),
                            }
                        )
                    if not started:
                        self._error("BUSY", "已有任务在运行", HTTPStatus.CONFLICT)
                        return
                    self._json({"ok": True})
                    return
                if parsed.path == "/api/updates/download":
                    from lite.downloader import start as start_download

                    result = start_download(ROOT, sha=str(payload.get("sha") or ""))
                    self._json(result, HTTPStatus.OK if result.get("started") else HTTPStatus.CONFLICT)
                    return
                if parsed.path == "/api/updates/apply":
                    from lite.update_applier import apply_staged

                    if not _bundle_owns_resources(service.config):
                        self._error(
                            "DEV_MANAGED",
                            "当前资源来自开发目录，自动切换只对发布包生效",
                            HTTPStatus.CONFLICT,
                        )
                        return
                    if service.snapshot().get("busy"):
                        self._error("BUSY", "任务运行中，停止后再切换资源", HTTPStatus.CONFLICT)
                        return
                    result = apply_staged(ROOT, str(service.config.get("interface_source", "")))
                    if result.get("ok"):
                        built, detail = _rebuild_interface()
                        result["interfaceRebuilt"] = built
                        if not built:
                            from lite.update_applier import rollback

                            result = {
                                "ok": False,
                                "error": f"新资源无法生成 interface，已回滚：{detail}",
                                "code": "APPLY_REJECTED",
                                "rolledBack": rollback(ROOT),
                            }
                            _rebuild_interface()
                    if not result.get("ok"):
                        result.setdefault("code", "APPLY_FAILED")
                    self._json(
                        result, HTTPStatus.OK if result.get("ok") else HTTPStatus.BAD_REQUEST
                    )
                    return
                if parsed.path == "/api/updates/rollback":
                    from lite.update_applier import rollback

                    if not _bundle_owns_resources(service.config):
                        self._error(
                            "DEV_MANAGED", "当前资源来自开发目录，无需回滚", HTTPStatus.CONFLICT
                        )
                        return
                    if service.snapshot().get("busy"):
                        self._error("BUSY", "任务运行中，停止后再回滚", HTTPStatus.CONFLICT)
                        return
                    ok = rollback(ROOT)
                    if not ok:
                        self._error("ROLLBACK_FAILED", "没有可回滚的备份", HTTPStatus.BAD_REQUEST)
                        return
                    _rebuild_interface()
                    self._json({"ok": True})
                    return
                if parsed.path == "/api/check":
                    started = service.check_connection()
                    if not started:
                        self._error("BUSY", "已有任务在运行，无法检查连接", HTTPStatus.CONFLICT)
                        return
                    self._json({"ok": True})
                    return
                if parsed.path == "/api/stop":
                    service.stop()
                    self._json({"ok": True})
                    return
                if parsed.path == "/api/exit":
                    self._json({"ok": True})
                    threading.Thread(target=server_ref[0].shutdown, daemon=True).start()
                    return
                self._error("NOT_FOUND", "接口不存在", HTTPStatus.NOT_FOUND)
            except json.JSONDecodeError as error:
                self._error("BAD_JSON", f"请求体不是合法 JSON：{error}", HTTPStatus.BAD_REQUEST)
            except Exception as error:
                self._error("BAD_REQUEST", str(error), HTTPStatus.BAD_REQUEST)

    return Handler


def running_instance(host: str, port: int) -> bool:
    """True when a Lite console already answers on this port."""
    import urllib.request

    try:
        with urllib.request.urlopen(f"http://{host}:{port}/api/state", timeout=1.5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return False
    return isinstance(data, dict) and "logSeq" in data and "status" in data


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--port", type=int)
    parser.add_argument("--parent-pid", type=int, help="父进程退出时自动关闭")
    parser.add_argument("--selftest", action="store_true", help="检查运行环境后退出")
    args = parser.parse_args()

    # Native crashes (MaaFramework is C++) leave no Python traceback and no
    # Windows event if WER is off, so a dying service used to be unattributable.
    # faulthandler writes the faulting stack to runtime/crash.log instead.
    import faulthandler

    crash_path = ROOT / "runtime" / "crash.log"
    crash_path.parent.mkdir(parents=True, exist_ok=True)
    crash_file = crash_path.open("a", encoding="utf-8")
    faulthandler.enable(file=crash_file, all_threads=True)

    config = load_config()

    if args.selftest:
        from lite.selftest import run_selftest

        return run_selftest(ROOT, config)

    staged_note = _apply_staged_resources(config)
    _ensure_interface(config)

    if not (ROOT / "build" / "generated" / "interface.json").is_file():
        print("Generated interface missing. Run: python lite/apply_scope.py", file=sys.stderr)
        return 1

    # 旧版本只存了选项索引。趁现在这份 interface 还认得这个索引，把所选值的名字
    # 一并记下来；以后上游重排 cases 时，光靠索引就会静默选到别的值。
    from lite.task_options_service import backfill_labels

    try:
        interface_data = json.loads(
            (ROOT / "build" / "generated" / "interface.json").read_text(encoding="utf-8")
        )
        filled = backfill_labels(interface_data)
        if filled:
            print(f"已为 {filled} 个选项选择补记名称（task-options.json）", flush=True)
    except (OSError, ValueError) as error:
        print(f"选项名称补记失败（不影响启动）：{error}", file=sys.stderr)

    # Housekeeping before anything opens a socket: an agent orphaned by a crash
    # would otherwise steal the adb connection from this run.
    from lite import agent_guard

    for action in agent_guard.reap_orphans(ROOT):
        print(action, flush=True)
    agent_guard.rotate_logs(ROOT)

    port = args.port or int(config.get("port", 8765))
    host = config.get("host", "127.0.0.1")
    if not args.no_browser and running_instance(host, port):
        print("控制台已在运行，直接打开窗口。", flush=True)
        open_ui(f"http://{host}:{port}")
        return 0
    service = RunService(ROOT, config)
    if staged_note is not None:
        # 资源在启动前就换掉了，把这行补进日志，界面第一次轮询就能看到。
        service.note(*staged_note)
    server_ref: list[LiteHTTPServer] = []
    handler = make_handler(service, server_ref)
    try:
        server = LiteHTTPServer((config.get("host", "127.0.0.1"), port), handler)
    except OSError:
        server = LiteHTTPServer((config.get("host", "127.0.0.1"), 0), handler)
    server_ref.append(server)
    actual_port = server.server_address[1]
    url = f"http://{config.get('host', '127.0.0.1')}:{actual_port}"
    print(f"MaaYuan Lite 控制台: {url}", flush=True)

    # The shell reads this instead of parsing stdout; it also makes the real
    # port visible when 8765 was busy and the server fell back to a random one.
    port_file = ROOT / "runtime" / "port.txt"
    port_file.parent.mkdir(parents=True, exist_ok=True)
    port_file.write_text(str(actual_port), encoding="utf-8")
    settings = load_settings()
    startup = settings.get("startup_action", "none")

    def _shutdown(reason: str = "界面请求关闭") -> None:
        # A self-kill without a log line is indistinguishable from a crash.
        service.note(f"服务即将退出：{reason}", "warn")
        _close_app_window()
        server.shutdown()

    service.set_shutdown_hook(_shutdown)

    if args.parent_pid:
        from lite.process_guard import watch_parent

        watch_parent(args.parent_pid, _shutdown, logger=service.note)

    # Resource freshness is checked after the port is open: an offline or slow
    # network must never delay the window.
    from lite.downloader import auto_check

    auto_check(
        ROOT,
        enabled=bool(settings.get("auto_update_resources", True)),
        log=service.note,
    )

    if not args.no_browser:
        threading.Timer(0.6, lambda: open_ui(url)).start()

    # WPF starts the service with --no-browser, so auto-run must not live inside
    # that branch: "启动时自动运行日常" is an automation setting, not a UI one.
    if startup in ("auto_run", "auto_run_minimized"):
        delay = 6.0 if startup == "auto_run_minimized" else 4.0
        threading.Thread(
            target=_auto_start,
            args=(service, settings, delay),
            daemon=True,
        ).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        service.stop()
        server.server_close()
        port_file.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
