"""Exit when the parent process disappears.

The WPF shell starts the Python service as a child. If the shell crashes or is
killed, the service must not stay behind holding the port. Watching with
OpenProcess/WaitForSingleObject avoids os.kill, which would terminate the
parent on Windows.
"""

from __future__ import annotations

import ctypes
import threading
import time
from typing import Callable

SYNCHRONIZE = 0x00100000
WAIT_TIMEOUT = 0x00000102

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)


def parent_alive(pid: int) -> bool:
    handle = _kernel32.OpenProcess(SYNCHRONIZE, False, pid)
    if not handle:
        return False
    try:
        return _kernel32.WaitForSingleObject(handle, 0) == WAIT_TIMEOUT
    finally:
        _kernel32.CloseHandle(handle)


def watch_parent(pid: int, on_exit: Callable[[], None], interval: float = 2.0) -> threading.Thread:
    def loop() -> None:
        while True:
            time.sleep(interval)
            if not parent_alive(pid):
                try:
                    on_exit()
                finally:
                    return

    thread = threading.Thread(target=loop, name="parent-guard", daemon=True)
    thread.start()
    return thread
