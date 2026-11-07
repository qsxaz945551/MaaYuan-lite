"""Measure a process tree (root exe + descendants) memory and CPU.

Usage: measure_tree.py <exe-name>[,<exe-name>] [seconds]

The tree is resolved through Win32_Process parent links, so WebView2 child
processes (msedgewebview2.exe) are counted together with their host.
"""

import json
import subprocess
import sys
import time

MIB = 1048576.0

PS_TREE = (
    "Get-CimInstance Win32_Process | "
    "Select-Object ProcessId,ParentProcessId,Name | ConvertTo-Json -Compress"
)
PS_STATS = (
    "Get-Process | Select-Object Id,PrivateMemorySize64,WorkingSet64,CPU | "
    "ConvertTo-Json -Compress"
)


def _ps(command: str):
    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="ignore",
    )
    text = out.stdout.strip()
    if not text:
        return []
    data = json.loads(text)
    return data if isinstance(data, list) else [data]


def snapshot(names: set[str]) -> dict:
    tree = _ps(PS_TREE)
    stats = {int(row["Id"]): row for row in _ps(PS_STATS)}

    roots = {int(r["ProcessId"]) for r in tree if str(r["Name"]).lower() in names}
    ids = set(roots)
    changed = True
    while changed:
        changed = False
        for row in tree:
            pid, ppid = int(row["ProcessId"]), int(row["ParentProcessId"])
            if ppid in ids and pid not in ids:
                ids.add(pid)
                changed = True

    private = sum(float(stats.get(pid, {}).get("PrivateMemorySize64") or 0) for pid in ids)
    ws = sum(float(stats.get(pid, {}).get("WorkingSet64") or 0) for pid in ids)
    cpu = sum(float(stats.get(pid, {}).get("CPU") or 0) for pid in ids)
    return {
        "procs": len(ids),
        "private": private,
        "ws": ws,
        "cpu": cpu,
        "detail": [(pid, stats.get(pid, {}).get("Id") and str(pid)) for pid in ids],
    }


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
    if last["procs"] == 0:
        print("process exited during measurement")
        return 1
    print(
        f"procs={last['procs']}  "
        f"private={last['private'] / MIB:.1f} MiB  "
        f"workingSet={last['ws'] / MIB:.1f} MiB  "
        f"cpu={last['cpu'] - first['cpu']:.2f}s/{seconds:.0f}s"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
