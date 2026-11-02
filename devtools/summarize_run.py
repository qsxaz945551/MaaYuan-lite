"""Summarize task timings from an MFAAvalonia (original MaaYuan) daily log.

Usage:
    python devtools/summarize_run.py "D:/Apps Game/.../logs/log-20261102.log"
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path

START = re.compile(r"^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\.\d+\]\[INF\] 开始任务: (.+?)\s*$")
END_OK = re.compile(r"^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\.\d+\]\[INF\] >>> MFA异步任务 队列任务 已完成")
END_BAD = re.compile(
    r"^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\.\d+\]\[INF\] >>> MFA异步任务 队列任务 (失败|已停止|已取消)"
)


def parse(path: Path) -> dict:
    rows: list[dict] = []
    current: dict | None = None
    started_at = None
    ended_at = None

    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        match = START.match(line)
        if match:
            if current:
                current["result"] = "unfinished"
                rows.append(current)
            current = {"name": match.group(2), "start": match.group(1), "result": "running"}
            started_at = started_at or match.group(1)
            continue

        if current is None:
            continue

        ok = END_OK.match(line)
        bad = END_BAD.match(line)
        if ok or bad:
            stamp = (ok or bad).group(1)
            current["end"] = stamp
            current["result"] = "ok" if ok else (bad.group(2) if bad else "unknown")
            current["seconds"] = round(
                (datetime.fromisoformat(stamp) - datetime.fromisoformat(current["start"])).total_seconds(), 1
            )
            ended_at = stamp
            rows.append(current)
            current = None

    if current:
        current["result"] = "unfinished"
        rows.append(current)

    total = 0.0
    if started_at and ended_at:
        total = round(
            (datetime.fromisoformat(ended_at) - datetime.fromisoformat(started_at)).total_seconds(), 1
        )

    return {"tasks": rows, "total_seconds": total, "started": started_at, "ended": ended_at}


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    path = Path(sys.argv[1])
    data = parse(path)

    print(f"{'任务':<28}{'耗时':>8}  结果")
    print("-" * 50)
    for row in data["tasks"]:
        seconds = row.get("seconds")
        print(f"{row['name']:<28}{(f'{seconds:.0f}s' if seconds is not None else '-'):>8}  {row['result']}")
    print("-" * 50)
    print(f"合计 {data['total_seconds']:.0f}s（{data['started']} → {data['ended']}）")

    out = path.with_suffix(".summary.json")
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"json: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
