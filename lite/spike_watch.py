"""Wait for MaaYuan to exit, then summarise this run's task timings from maa.log."""

from __future__ import annotations

import json
import re
import subprocess
import time
from datetime import datetime, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAALOG = Path(r"D:/Apps Game/MaaYuan-win-x86_64-v2.1.1-beta.6/debug/maa.log")
OUT = ROOT / "build" / "spike" / "orig-run.json"

TASK_RE = re.compile(
    r"^\[(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3})\].*"
    r"\[msg=Tasker\.Task\.(?P<kind>Starting|Succeeded|Failed)\].*?"
    r'"entry":"(?P<entry>[^"]+)"'
)


def running() -> bool:
    try:
        out = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq MaaYuan.exe", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            encoding="gbk",
            errors="ignore",
        )
    except OSError:
        return False
    return "maayuan" in out.stdout.lower()


def wait_for_exit(timeout: float = 40 * 60) -> float:
    start = time.monotonic()
    seen = False
    while time.monotonic() - start < timeout:
        if running():
            seen = True
        elif seen:
            return time.monotonic() - start
        elif time.monotonic() - start > 120:
            break
        time.sleep(5)
    return time.monotonic() - start


def parse(since: datetime) -> dict:
    events = []
    text = MAALOG.read_text(encoding="utf-8", errors="replace")
    for line in text.splitlines():
        match = TASK_RE.match(line)
        if not match:
            continue
        stamp = datetime.strptime(match.group("ts"), "%Y-%m-%d %H:%M:%S.%f")
        if stamp < since:
            continue
        events.append(
            {
                "ts": stamp,
                "kind": match.group("kind"),
                "entry": match.group("entry"),
            }
        )

    runs = []
    open_tasks: dict[str, datetime] = {}
    for event in events:
        entry = event["entry"]
        if event["kind"] == "Starting":
            open_tasks[entry] = event["ts"]
        elif entry in open_tasks:
            start = open_tasks.pop(entry)
            runs.append(
                {
                    "entry": entry,
                    "status": "succeeded" if event["kind"] == "Succeeded" else "failed",
                    "start": start.strftime("%H:%M:%S"),
                    "end": event["ts"].strftime("%H:%M:%S"),
                    "seconds": round((event["ts"] - start).total_seconds(), 1),
                }
            )

    total = 0.0
    if runs:
        total = round(
            (
                max(datetime.strptime(run["end"], "%H:%M:%S") for run in runs)
                - min(datetime.strptime(run["start"], "%H:%M:%S") for run in runs)
            ).total_seconds(),
            1,
        )
    return {"runs": runs, "total_seconds": total, "unfinished": list(open_tasks)}


def load_metrics() -> dict:
    path = ROOT / "build" / "spike" / "orig-metrics.csv"
    if not path.is_file():
        return {}
    rows = []
    lines = path.read_text(encoding="utf-8").splitlines()[1:]
    for line in lines:
        parts = line.split(",")
        if len(parts) < 6 or not parts[2]:
            continue
        rows.append(
            {
                "time": parts[0],
                "ws": float(parts[2]),
                "priv": float(parts[3]),
                "peak": float(parts[4]),
                "cpu": float(parts[5]),
            }
        )
    if not rows:
        return {}
    return {
        "samples": len(rows),
        "ws_max": max(row["ws"] for row in rows),
        "priv_max": max(row["priv"] for row in rows),
        "peak_ws": max(row["peak"] for row in rows),
        "cpu_max": max(row["cpu"] for row in rows),
        "first": rows[0],
        "last": rows[-1],
    }


def main() -> int:
    started = datetime.now()
    print("waiting for MaaYuan to finish...", flush=True)
    wait_for_exit()

    result = parse(started.replace(microsecond=0) - timedelta(minutes=3))
    result["metrics"] = load_metrics()
    result["finished_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"tasks={len(result['runs'])} total={result['total_seconds']}s", flush=True)
    for run in result["runs"]:
        print(f"  {run['status']:9} {run['seconds']:7.1f}s {run['entry']}", flush=True)
    metrics = result["metrics"]
    if metrics:
        print(
            f"memory: peak_ws={metrics['peak_ws']}MB ws_max={metrics['ws_max']}MB "
            f"priv_max={metrics['priv_max']}MB cpu={metrics['cpu_max']}s",
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
