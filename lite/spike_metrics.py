"""Sample MaaYuan memory/CPU while the original client runs a daily chain."""

from __future__ import annotations

import csv
import ctypes
import ctypes.wintypes as wt
import subprocess
import time
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "build" / "spike" / f"orig-metrics-{datetime.now():%Y%m%d-%H%M}.csv"
DURATION = 45 * 60
INTERVAL = 3

k32 = ctypes.windll.kernel32
psapi = ctypes.windll.psapi


class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("cb", wt.DWORD),
        ("PageFaultCount", wt.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


def find_pid() -> int | None:
    try:
        out = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq MaaYuan.exe", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            encoding="gbk",
            errors="ignore",
        )
    except OSError:
        return None
    for line in out.stdout.splitlines():
        parts = [part.strip('"') for part in line.split('","')]
        if len(parts) >= 2 and parts[0].lower().startswith("maayuan"):
            try:
                return int(parts[1])
            except ValueError:
                continue
    return None


def sample(pid: int) -> dict[str, float] | None:
    handle = k32.OpenProcess(0x0410, False, pid)
    if not handle:
        return None
    try:
        counters = PROCESS_MEMORY_COUNTERS()
        counters.cb = ctypes.sizeof(counters)
        if not psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
            return None
        created, exited, kernel, user = (wt.FILETIME() for _ in range(4))
        k32.GetProcessTimes(
            handle,
            ctypes.byref(created),
            ctypes.byref(exited),
            ctypes.byref(kernel),
            ctypes.byref(user),
        )
        cpu = (
            (kernel.dwHighDateTime << 32 | kernel.dwLowDateTime)
            + (user.dwHighDateTime << 32 | user.dwLowDateTime)
        ) / 1e7
        return {
            "ws_mb": round(counters.WorkingSetSize / 1048576, 1),
            "priv_mb": round(counters.PagefileUsage / 1048576, 1),
            "peak_ws_mb": round(counters.PeakWorkingSetSize / 1048576, 1),
            "cpu_s": round(cpu, 2),
        }
    finally:
        k32.CloseHandle(handle)


def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["time", "pid", "working_set_mb", "private_mb", "peak_ws_mb", "cpu_s"])
        handle.flush()
        started = time.monotonic()
        last_seen = None
        while time.monotonic() - started < DURATION:
            pid = find_pid()
            if pid:
                last_seen = time.monotonic()
                data = sample(pid)
                if data:
                    writer.writerow(
                        [
                            datetime.now().strftime("%H:%M:%S"),
                            pid,
                            data["ws_mb"],
                            data["priv_mb"],
                            data["peak_ws_mb"],
                            data["cpu_s"],
                        ]
                    )
                    handle.flush()
            elif last_seen and time.monotonic() - last_seen > 90:
                writer.writerow([datetime.now().strftime("%H:%M:%S"), "", "", "", "", ""])
                handle.flush()
                break
            time.sleep(INTERVAL)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
