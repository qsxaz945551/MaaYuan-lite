"""MaaYuan Lite initial local control panel."""

from __future__ import annotations

import os

# 必须在任何第三方 import 之前设置：onnxruntime / numpy / opencv 在 import 时
# 就按 OMP_NUM_THREADS 建好线程池与缓冲区，之后再 setdefault 已经晚了。
# 2026-11-09 同条件 5 轮实测（观星，游戏内，check 后 python 私有提交 / 任务耗时）：
#   16 线程 561.3 MB / 15.7 s   8 线程 303.6 MB / 15.4 s   4 线程 174.9 MB / 18.2 s
# 4 线程为多省 128 MB 牺牲了 18% 耗时，属过度优化；8 线程在耗时上不输 16 线程，
# 且省 258 MB，故取 8。
os.environ.setdefault("OMP_NUM_THREADS", str(min(8, os.cpu_count() or 8)))

import argparse
import json
import sys
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

# 组合根：只负责把各个模块装起来并启动服务。路由在 lite/http_api.py，
# 资源切换与 interface 重建在 lite/resource_boot.py。
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lite.constants import DEFAULT_PORT
from lite.http_api import make_handler
from lite.resource_boot import apply_staged_resources, ensure_interface, load_config
from lite.run_service import RunService
from lite.settings import load_settings


_HEALTH_CACHE: dict[str, object] = {"at": 0.0, "data": None}


def _auto_start(service: RunService, settings: dict, delay: float) -> None:
    import time

    time.sleep(delay)
    if service.snapshot().get("busy"):
        return
    try:
        service.start_daily(
            training=str(settings.get("last_training") or DEFAULT_TRAINING),
            include_dungeon=bool(settings.get("last_dungeon")),
        )
    except Exception as error:  # noqa: BLE001 - background thread, nobody to raise to
        # 「启动时自动运行」失败曾经完全静默：线程里抛了就没了，界面只看到空闲。
        service.note(f"启动时自动运行失败：{error}", "error")


def _close_app_window(title: str = "MaaYuan Lite") -> None:
    """Ask the WPF window to close (used by the "结束后关闭MAA" action)."""
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


class LiteHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    # Windows lets several processes bind the same port when address reuse is
    # enabled, which silently splits requests across stale control-panel
    # instances. Refuse the second bind instead.
    allow_reuse_address = False


def main() -> int:
    parser = argparse.ArgumentParser()
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

    staged_note = apply_staged_resources(config)
    ensure_interface(config)

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
            print(f"已为 {filled} 个选项选择补记名称（runtime/task-options.json）", flush=True)
    except (OSError, ValueError) as error:
        print(f"选项名称补记失败（不影响启动）：{error}", file=sys.stderr)

    # Housekeeping before anything opens a socket: an agent orphaned by a crash
    # would otherwise steal the adb connection from this run.
    from lite import agent_guard

    for action in agent_guard.reap_orphans(ROOT):
        print(action, flush=True)
    agent_guard.rotate_logs(ROOT)

    port = args.port or int(config.get("port", DEFAULT_PORT))
    host = config.get("host", "127.0.0.1")
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
    print(f"MaaYuan Lite 服务: {url}", flush=True)

    # The shell reads this instead of parsing stdout; it also makes the real
    # port visible when the default was busy and the server fell back to a random one.
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
        # 启动时就自动跑日常时，下载等这一轮结束再开始，别和 OCR 抢资源。
        wait_while=lambda: bool(service.snapshot().get("busy")),
    )

    # 「启动时自动运行日常」是自动化设置，和界面形态无关。
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
