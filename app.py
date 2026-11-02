"""MaaYuan Lite initial local control panel."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lite.daily_plan import build_plan, load_profile
from lite.run_service import RunService
from lite.settings import load_settings, save_settings
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


def load_config() -> dict:
    with CONFIG_FILE.open("r", encoding="utf-8-sig") as handle:
        return json.load(handle)


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


def find_edge() -> Path | None:
    candidates = [
        Path(os.environ.get("ProgramFiles(x86)", "")) / "Microsoft/Edge/Application/msedge.exe",
        Path(os.environ.get("ProgramFiles", "")) / "Microsoft/Edge/Application/msedge.exe",
    ]
    return next((path for path in candidates if path.is_file()), None)


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


def _minimize_window(title: str = "MaaYuan Lite", delay: float = 2.5) -> None:
    """Minimise the app window once it exists (Edge keeps its own window size)."""
    import ctypes
    import ctypes.wintypes as wt
    import time

    time.sleep(delay)
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
        user32.ShowWindow(hwnd, 6)  # SW_MINIMIZE


def open_ui(url: str, minimized: bool = False) -> None:
    edge = find_edge()
    if edge is not None:
        subprocess.Popen(
            [
                str(edge),
                f"--app={url}",
                "--window-size=1360,880",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if minimized:
            threading.Thread(target=_minimize_window, daemon=True).start()
    else:
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

        def _read_json(self) -> dict:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0:
                return {}
            return json.loads(self.rfile.read(length).decode("utf-8"))

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
                    self._json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
                return
            if parsed.path == "/api/settings":
                self._json(load_settings())
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
                    self._json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
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
                    self._json({"error": "no screenshot"}, HTTPStatus.NOT_FOUND)
                return
            self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)

        def do_POST(self):
            parsed = urlparse(self.path)
            try:
                payload = self._read_json()
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
                    patch = payload if isinstance(payload, dict) else {}
                    self._json({"ok": True, "settings": save_settings(patch)})
                    return
                if parsed.path == "/api/run-task":
                    names = payload.get("names")
                    if not isinstance(names, list):
                        names = [str(payload.get("name", ""))]
                    names = [str(name) for name in names if str(name).strip()]
                    try:
                        started = service.run_sequence(names)
                    except ValueError as error:
                        self._json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
                        return
                    self._json(
                        {"ok": started},
                        HTTPStatus.OK if started else HTTPStatus.CONFLICT,
                    )
                    return
                if parsed.path == "/api/start":
                    dungeon_value = payload.get("dungeon")
                    started = service.start_daily(
                        training=str(payload.get("training", "修为")),
                        include_dungeon=(
                            seasonal_default_enabled()
                            if dungeon_value is None
                            else bool(dungeon_value)
                        ),
                        resume=bool(payload.get("resume", False)),
                    )
                    if started and not payload.get("resume"):
                        save_settings(
                            {
                                "last_training": str(payload.get("training", "修为")),
                                "last_dungeon": bool(dungeon_value),
                            }
                        )
                    self._json({"ok": started}, HTTPStatus.OK if started else HTTPStatus.CONFLICT)
                    return
                if parsed.path == "/api/check":
                    started = service.check_connection()
                    self._json({"ok": started}, HTTPStatus.OK if started else HTTPStatus.CONFLICT)
                    return
                if parsed.path == "/api/stop":
                    service.stop()
                    self._json({"ok": True})
                    return
                if parsed.path == "/api/exit":
                    self._json({"ok": True})
                    threading.Thread(target=server_ref[0].shutdown, daemon=True).start()
                    return
                self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
            except Exception as error:
                self._json({"error": str(error)}, HTTPStatus.BAD_REQUEST)

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
    parser.add_argument("--selftest", action="store_true", help="检查运行环境后退出")
    args = parser.parse_args()

    config = load_config()

    if args.selftest:
        from lite.selftest import run_selftest

        return run_selftest(ROOT, config)

    if not (ROOT / "build" / "generated" / "interface.json").is_file():
        print("Generated interface missing. Run: python lite/apply_scope.py", file=sys.stderr)
        return 1

    port = args.port or int(config.get("port", 8765))
    host = config.get("host", "127.0.0.1")
    if not args.no_browser and running_instance(host, port):
        print("控制台已在运行，直接打开窗口。", flush=True)
        open_ui(f"http://{host}:{port}", False)
        return 0
    service = RunService(ROOT, config)
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
    settings = load_settings()
    startup = settings.get("startup_action", "none")

    def _shutdown() -> None:
        _close_app_window()
        server.shutdown()

    service.set_shutdown_hook(_shutdown)

    if not args.no_browser:
        minimized = startup in ("minimize_only", "auto_run_minimized")
        threading.Timer(0.6, lambda: open_ui(url, minimized)).start()
        if startup in ("auto_run", "auto_run_minimized"):
            threading.Thread(
                target=_auto_start,
                args=(service, settings, 6.0 if minimized else 4.0),
                daemon=True,
            ).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        service.stop()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
