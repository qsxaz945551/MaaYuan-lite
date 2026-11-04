"""Exit when the parent process disappears.

The WPF shell starts the Python service as a child. If the shell crashes or is
killed, the service must not stay behind holding the port. Watching with
OpenProcess/WaitForSingleObject avoids os.kill, which would terminate the
parent on Windows.

Two details matter and both were wrong once:

* HANDLE is pointer-sized. Without ``restype`` ctypes truncates it to 32 bits,
  so the wait ran against a garbage handle.
* ``OpenProcess`` returns NULL both when the process is gone and when it is
  merely inaccessible (different integrity level). Treating "cannot open" as
  "parent died" kills a perfectly healthy service.
"""

from __future__ import annotations

import ctypes
import threading
import time
from typing import Callable

SYNCHRONIZE = 0x00100000
WAIT_OBJECT_0 = 0x00000000
WAIT_TIMEOUT = 0x00000102

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

_kernel32.OpenProcess.restype = ctypes.c_void_p
_kernel32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
_kernel32.WaitForSingleObject.restype = ctypes.c_ulong
_kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
_kernel32.CloseHandle.restype = ctypes.c_int
_kernel32.CloseHandle.argtypes = [ctypes.c_void_p]

ERROR_INVALID_PARAMETER = 87


def parent_alive(pid: int) -> bool:
    """False only when we are sure the process is gone.

    A handle we cannot open is treated as alive: refusing to shut down is
    recoverable (the port probe and agent cleanup handle it), killing a
    healthy service is not.
    """
    handle = _kernel32.OpenProcess(SYNCHRONIZE, False, pid)
    if not handle:
        # ERROR_INVALID_PARAMETER means the PID does not exist — that is a
        # real death. Anything else is a permission problem.
        return ctypes.get_last_error() != ERROR_INVALID_PARAMETER
    try:
        return _kernel32.WaitForSingleObject(handle, 0) == WAIT_TIMEOUT
    finally:
        _kernel32.CloseHandle(handle)


def watch_parent(
    pid: int,
    on_exit: Callable[[], None],
    interval: float = 2.0,
    logger: Callable[[str, str], None] | None = None,
) -> threading.Thread:
    """Poll the parent and shut down when it is gone.

    ``logger`` matters: a self-kill with no log line is indistinguishable from
    a crash, and that ambiguity once cost an evening of guessing ("服务自己消失
    了"). Every exit decision is written down, together with the evidence.
    """

    def report(message: str) -> None:
        if logger is not None:
            try:
                logger(message, "warn")
            except Exception:  # noqa: BLE001 - logging must not block exit
                pass

    def loop() -> None:
        while True:
            time.sleep(interval)
            if not parent_alive(pid):
                # Include the Win32 error so a future false positive is
                # diagnosable instead of mysterious.
                report(
                    f"父进程 {pid} 已不在（OpenProcess/WaitForSingleObject 判定，"
                    f"last_error={ctypes.get_last_error()}），服务随之关闭。"
                )
                try:
                    on_exit()
                finally:
                    return

    thread = threading.Thread(target=loop, name="parent-guard", daemon=True)
    thread.start()
    return thread
