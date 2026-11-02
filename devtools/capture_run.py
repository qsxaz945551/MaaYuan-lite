"""Capture one MaaYuan (original) run: process-tree memory/CPU plus task events.

Writes a CSV that can be analysed afterwards, and prints a compact live line so
the caller can follow progress. Sampling is intentionally cheap: one PowerShell
call per interval, same process-tree semantics as ``measure_tree.py``.

Usage:
    python devtools/capture_run.py --duration 1500 --interval 5
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "devtools"))

from proc_tree import snapshot  # noqa: E402

MIB = 1048576.0
TASK_START = re.compile(r"\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\.\d+\]\[INF\] 开始任务: (.+)$")
TASK_DONE = re.compile(r"\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\.\d+\]\[INF\] (?:>>> )?(?:任务|队列任务).*?(已完成|完成)")


def log_path(base: Path, day: datetime) -> Path:
    return base / f"log-{day.strftime('%Y%m%d')}.log"


def read_events(path: Path) -> list[tuple[str, str]]:
    if not path.is_file():
        return []
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []
    events: list[tuple[str, str]] = []
    for line in text.splitlines()[-400:]:
        match = TASK_START.search(line)
        if match:
            events.append((match.group(1), match.group(2).strip()))
    return events


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe", default="MaaYuan")
    parser.add_argument("--interval", type=float, default=5.0)
    parser.add_argument("--duration", type=float, default=1500.0)
    parser.add_argument("--log-root", default="D:/Apps Game/MaaYuan-win-x86_64-v2.1.1-beta.6/logs")
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    started = datetime.now()
    out = Path(args.out) if args.out else ROOT / "build" / "spike" / f"orig-run-{started:%Y%m%d-%H%M%S}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    log_root = Path(args.log_root)

    names = {args.exe.lower()}
    seen: set[tuple[str, str]] = set()
    last_cpu = None
    last_wall = None
    start_mono = time.monotonic()
    deadline = start_mono + args.duration

    with out.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerow(["time", "elapsed_s", "procs", "private_mib", "ws_mib", "cpu_s", "cpu_pct", "event"])

        while time.monotonic() < deadline:
            wall = time.monotonic()
            data = snapshot(names)
            now = datetime.now()

            if data["procs"] == 0:
                writer.writerow([now.strftime("%H:%M:%S"), f"{wall - start_mono:.0f}",
                                 0, 0, 0, "", "", "process gone"])
                print(f"[{now:%H:%M:%S}] process gone, stop", flush=True)
                break

            cpu = data["cpu"]
            pct = ""
            if last_cpu is not None and last_wall is not None and wall > last_wall:
                pct = f"{(cpu - last_cpu) / (wall - last_wall) * 100:.0f}"
            last_cpu, last_wall = cpu, wall

            events = [item for item in read_events(log_path(log_root, now)) if item not in seen]
            for item in events:
                seen.add(item)

            elapsed = wall - start_mono
            writer.writerow([
                now.strftime("%H:%M:%S"),
                f"{elapsed:.0f}",
                data["procs"],
                f"{data['private'] / MIB:.1f}",
                f"{data['ws'] / MIB:.1f}",
                f"{cpu:.1f}",
                pct,
                " | ".join(f"{ts[11:]} {name}" for ts, name in events),
            ])
            handle.flush()

            line = (f"[{now:%H:%M:%S}] procs={data['procs']} "
                    f"priv={data['private'] / MIB:.0f}M ws={data['ws'] / MIB:.0f}M cpu={cpu:.0f}s")
            if pct:
                line += f" ({pct}%)"
            if events:
                line += "  -> " + "; ".join(name for _, name in events)
            print(line, flush=True)

            time.sleep(max(0.2, args.interval - (time.monotonic() - wall)))

    print(f"csv: {out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
