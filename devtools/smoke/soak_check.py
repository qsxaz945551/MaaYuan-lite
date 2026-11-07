"""One-shot soak sample (Q4).

Q4 asks whether a long-running service leaks handles or fills the disk with
logs. That needs many samples over hours, so this script does one sample per
invocation and appends it to ``runtime/soak.csv``; run it from Task Scheduler
(every 15-30 minutes) and read the trend with ``--summary``.

Sampling one process is cheap and does not touch the emulator, so it is safe to
run while the user keeps working.

Usage:
    python devtools/smoke/soak_check.py              # 采一次并追加
    python devtools/smoke/soak_check.py --summary    # 看趋势
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CSV_PATH = ROOT / "runtime" / "soak.csv"
FIELDS = ["time", "pid", "handles", "rss_mb", "lite_log_kb", "maa_log_kb", "status"]

sys.path.insert(0, str(Path(__file__).resolve().parent))
from stability_run import sample_process  # noqa: E402  同一套 Win32 采样


def read_port() -> int:
    pointer = ROOT / "runtime" / "port.txt"
    if pointer.is_file():
        text = pointer.read_text(encoding="utf-8").strip()
        if text.isdigit():
            return int(text)
    return 8765


def fetch_meta(port: int) -> dict | None:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(f"http://127.0.0.1:{port}/api/meta", timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))
    except OSError:
        return None


def size_kb(path: Path) -> int:
    try:
        return int(path.stat().st_size / 1024)
    except OSError:
        return 0


def take_sample() -> int:
    port = read_port()
    meta = fetch_meta(port)
    row = {
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "pid": "",
        "handles": "",
        "rss_mb": "",
        "lite_log_kb": size_kb(ROOT / "runtime" / "lite.log"),
        "maa_log_kb": size_kb(ROOT / "runtime" / "debug" / "maa.log"),
        "status": "down" if meta is None else "up",
    }
    if meta and meta.get("pid"):
        handles, rss = sample_process(int(meta["pid"]))
        row["pid"] = meta["pid"]
        row["handles"] = handles if handles is not None else ""
        row["rss_mb"] = f"{rss:.0f}" if rss is not None else ""

    CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    new_file = not CSV_PATH.is_file()
    with CSV_PATH.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        if new_file:
            writer.writeheader()
        writer.writerow(row)

    print(
        f"{row['time']}  status={row['status']}  handles={row['handles'] or '-'}  "
        f"rss={row['rss_mb'] or '-'} MB  lite.log={row['lite_log_kb']} KB  "
        f"maa.log={row['maa_log_kb']} KB"
    )
    return 0 if meta else 1


def show_summary() -> int:
    if not CSV_PATH.is_file():
        print(f"还没有采样数据：{CSV_PATH}")
        return 1
    with CSV_PATH.open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        print("CSV 是空的")
        return 1

    up = [row for row in rows if row["status"] == "up" and row["handles"]]
    print(f"采样 {len(rows)} 次：服务在线 {len(up)} 次，离线 {len(rows) - len(up)} 次")
    print(f"时间范围：{rows[0]['time']} → {rows[-1]['time']}")
    if len(up) < 2:
        print("在线样本不足，无法看趋势")
        return 0

    handles = [int(row["handles"]) for row in up]
    memory = [int(row["rss_mb"]) for row in up]
    print(f"句柄：{handles[0]} → {handles[-1]}（峰值 {max(handles)}）")
    print(f"内存：{memory[0]} → {memory[-1]} MB（峰值 {max(memory)} MB）")
    print(
        f"日志：lite.log {rows[0]['lite_log_kb']} → {rows[-1]['lite_log_kb']} KB，"
        f"maa.log {rows[0]['maa_log_kb']} → {rows[-1]['maa_log_kb']} KB"
    )

    rising = all(b >= a for a, b in zip(handles, handles[1:]))
    if rising and handles[-1] - handles[0] > 20:
        print("⚠ 句柄持续上涨，疑似泄漏")
    if memory[-1] - memory[0] > 100 or max(memory) > 1200:
        print("⚠ 内存增长偏大，需要复查")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="长稳采样（Q4）")
    parser.add_argument("--summary", action="store_true", help="只看趋势，不采样")
    parser.add_argument("--times", type=int, default=1, help="连续采几次（间隔 30 秒）")
    args = parser.parse_args()

    if args.summary:
        return show_summary()

    code = 0
    for index in range(max(1, args.times)):
        code = take_sample()
        if index + 1 < args.times:
            time.sleep(30)
    return code


if __name__ == "__main__":
    sys.exit(main())
