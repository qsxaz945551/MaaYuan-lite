"""Reap agent processes left behind by a crashed run, and cap log growth.

A normal shutdown stops the agent through ``LiteSession.stop``. A crash does not,
so the next start would end up with two agents fighting over the same adb
socket. We record the PID at launch and check it on the next start.

Safety rule: a PID alone is not proof of ownership (Windows recycles PIDs), so
the process image path must match our own interpreter before we terminate it.
"""

from __future__ import annotations

import ctypes
import json
import time
from ctypes import wintypes
from datetime import datetime
from pathlib import Path
from typing import Any

PID_FILE = Path("runtime") / "agent.json"
LOG_KEEP = 40
DEBUG_KEEP = 40
CACHE_KEEP = 3

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PROCESS_TERMINATE = 0x0001
SYNCHRONIZE = 0x00100000


def _kernel32() -> Any:
    return ctypes.WinDLL("kernel32", use_last_error=True)


def _image_path(pid: int) -> str:
    """Full exe path of a process, or empty when it is gone/inaccessible."""
    k32 = _kernel32()
    handle = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return ""
    try:
        buffer = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
        size = wintypes.DWORD(wintypes.MAX_PATH)
        if not k32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return ""
        return buffer.value
    finally:
        k32.CloseHandle(handle)


def _alive(pid: int) -> bool:
    k32 = _kernel32()
    handle = k32.OpenProcess(SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return False
    try:
        return k32.WaitForSingleObject(handle, 0) == 0x00000102  # WAIT_TIMEOUT
    finally:
        k32.CloseHandle(handle)


def _terminate(pid: int) -> bool:
    k32 = _kernel32()
    handle = k32.OpenProcess(PROCESS_TERMINATE, False, pid)
    if not handle:
        return False
    try:
        return bool(k32.TerminateProcess(handle, 1))
    finally:
        k32.CloseHandle(handle)


def record(project_root: Path, pid: int, port: int | None = None) -> None:
    path = project_root / PID_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "pid": pid,
                "port": port,
                "python": str(_interpreter(project_root)),
                "startedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def clear(project_root: Path) -> None:
    try:
        (project_root / PID_FILE).unlink()
    except OSError:
        pass


def _interpreter(project_root: Path) -> Path:
    import sys

    exe = Path(sys.executable)
    if exe.is_file():
        return exe
    return project_root / "runtime_env" / "python" / "python.exe"


def reap_orphans(project_root: Path, log: Any = None) -> list[str]:
    """Kill the agent recorded by a previous crashed run. Returns actions taken."""
    path = project_root / PID_FILE
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        clear(project_root)
        return []

    pid = int(data.get("pid", 0))
    actions: list[str] = []
    if pid and _alive(pid):
        recorded = Path(data.get("python", ""))
        actual = _image_path(pid)
        ours = actual and recorded and Path(actual).name == recorded.name
        # Compare by filename, not full path: the bundle may have moved.
        if ours and Path(actual).stem.lower() == "python":
            _terminate(pid)
            actions.append(f"清理遗留 agent 进程 PID {pid}")
        else:
            actions.append(f"PID {pid} 仍在运行但不是我们的 agent，未处理")
    clear(project_root)
    if log:
        for line in actions:
            log(line)
    return actions


def rotate_logs(project_root: Path) -> dict[str, int]:
    """Keep the newest N files in the log/debug/cache folders."""
    removed = {"agentLogs": 0, "debug": 0, "cache": 0}
    removed["agentLogs"] = _trim(project_root / "runtime" / "logs", LOG_KEEP)
    # Error frames follow the framework log dir (runtime/debug/on_error). The
    # project-root debug/on_error path is what older builds wrote; trim it too
    # so an upgraded install does not keep a stale folder forever.
    removed["debug"] = _trim(project_root / "runtime" / "debug" / "on_error", DEBUG_KEEP)
    removed["debug"] += _trim(project_root / "debug" / "on_error", DEBUG_KEEP)
    removed["cache"] = _trim(project_root / "runtime" / "cache", CACHE_KEEP)
    return removed


def _trim(folder: Path, keep: int) -> int:
    if not folder.is_dir():
        return 0
    files = sorted(
        (p for p in folder.iterdir() if p.is_file()),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    removed = 0
    for path in files[keep:]:
        try:
            path.unlink()
            removed += 1
        except OSError:
            pass
    return removed


def summarize(project_root: Path) -> dict[str, Any]:
    """Sizes used by the health endpoint to spot unbounded growth."""
    result: dict[str, Any] = {}
    for name, folder in (
        ("agentLogs", project_root / "runtime" / "logs"),
        ("debug", project_root / "runtime" / "debug"),
        ("cache", project_root / "runtime" / "cache"),
    ):
        if folder.is_dir():
            files = [p for p in folder.rglob("*") if p.is_file()]
            result[name] = {
                "files": len(files),
                "mb": round(sum(p.stat().st_size for p in files) / 1048576, 1),
            }
    result["checkedAt"] = time.time()
    return result
