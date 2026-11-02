"""Read a Windows process tree's memory and CPU without PowerShell.

The environment blocks spawning powershell.exe from Python, so this module talks
to kernel32/psapi through ctypes instead. Same semantics as ``measure_tree.py``:
roots are matched by exe name, then all descendants are added through parent
links.

Usage:
    python devtools/proc_tree.py MaaYuan [seconds]
"""

from __future__ import annotations

import ctypes
import sys
import time
from ctypes import wintypes
from pathlib import Path

MIB = 1048576.0
TH32CS_SNAPPROCESS = 0x00000002
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
MAX_PATH = 260

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
psapi = ctypes.WinDLL("psapi", use_last_error=True)


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * MAX_PATH),
    ]


class PROCESS_MEMORY_COUNTERS_EX(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("PageFaultCount", wintypes.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
        ("PrivateUsage", ctypes.c_size_t),
    ]


def _processes() -> list[tuple[int, int, str]]:
    snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snapshot in (-1, 0xFFFFFFFFFFFFFFFF):
        return []
    entry = PROCESSENTRY32W()
    entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
    rows: list[tuple[int, int, str]] = []
    try:
        if not kernel32.Process32FirstW(snapshot, ctypes.byref(entry)):
            return rows
        while True:
            rows.append((int(entry.th32ProcessID), int(entry.th32ParentProcessID), entry.szExeFile))
            if not kernel32.Process32NextW(snapshot, ctypes.byref(entry)):
                break
    finally:
        kernel32.CloseHandle(snapshot)
    return rows


def _stats(pid: int) -> tuple[int, int, float]:
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return 0, 0, 0.0
    try:
        counters = PROCESS_MEMORY_COUNTERS_EX()
        counters.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS_EX)
        private = ws = 0
        if psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
            private = int(counters.PrivateUsage)
            ws = int(counters.WorkingSetSize)

        creation = wintypes.FILETIME()
        exit_time = wintypes.FILETIME()
        kernel = wintypes.FILETIME()
        user = wintypes.FILETIME()
        cpu = 0.0
        if kernel32.GetProcessTimes(
            handle, ctypes.byref(creation), ctypes.byref(exit_time),
            ctypes.byref(kernel), ctypes.byref(user),
        ):
            ticks = (kernel.dwHighDateTime << 32 | kernel.dwLowDateTime) + (
                user.dwHighDateTime << 32 | user.dwLowDateTime
            )
            cpu = ticks / 1e7
        return private, ws, cpu
    finally:
        kernel32.CloseHandle(handle)


def _matches(name: str, names: set[str]) -> bool:
    low = name.lower()
    return low in names or low.removesuffix(".exe") in names


def snapshot(names: set[str]) -> dict:
    rows = _processes()
    roots = {pid for pid, _, name in rows if _matches(name, names)}
    ids = set(roots)
    changed = True
    while changed:
        changed = False
        for pid, ppid, _ in rows:
            if ppid in ids and pid not in ids:
                ids.add(pid)
                changed = True

    private = ws = 0
    cpu = 0.0
    for pid in ids:
        p, w, c = _stats(pid)
        private += p
        ws += w
        cpu += c
    return {"procs": len(ids), "private": private, "ws": ws, "cpu": cpu}


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    names = {item.strip().lower() for item in sys.argv[1].split(",")}
    seconds = float(sys.argv[2]) if len(sys.argv) > 2 else 10.0
    first = snapshot(names)
    if first["procs"] == 0:
        print(f"no running process named {sorted(names)}")
        return 1
    print(f"settling {seconds:.0f}s ...")
    time.sleep(seconds)
    last = snapshot(names)
    print(
        f"procs={last['procs']}  private={last['private'] / MIB:.1f} MiB  "
        f"workingSet={last['ws'] / MIB:.1f} MiB  cpu={last['cpu'] - first['cpu']:.2f}s/{seconds:.0f}s"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
