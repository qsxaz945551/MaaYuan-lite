"""Run the full daily chain once and report it task by task (V3).

The chain takes 8-20 minutes, which is far longer than a shell call survives
here, so the service is spawned as a child of this script and shut down at the
end. Every task transition is printed as it happens — a final summary alone
would hide *when* something went wrong.

Usage:
    python devtools/smoke_daily.py --training 修为
    python devtools/smoke_daily.py --training 铜钱 --dungeon
    python devtools/smoke_daily.py --resume          # 继续上次未完成
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from stability_run import Client, spawn_service, stop_service  # noqa: E402

RUNNING = {"starting", "running"}


def main() -> int:
    parser = argparse.ArgumentParser(description="完整日常实跑（V3）")
    parser.add_argument("--training", default="修为", choices=["修为", "铜钱", "经验"])
    parser.add_argument("--dungeon", action="store_true", help="包含地宫")
    parser.add_argument("--resume", action="store_true", help="继续上次未完成的日常")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--timeout", type=float, default=1800.0)
    args = parser.parse_args()

    service = spawn_service(args.port)
    client = Client(args.port)
    seen: dict[int, str] = {}
    began = time.monotonic()
    code = 1

    try:
        payload = {
            "training": args.training,
            "dungeon": args.dungeon,
            "resume": args.resume,
        }
        print(f"开始日常：{args.training}／地宫 {'开' if args.dungeon else '关'}"
              f"／{'续跑' if args.resume else '新跑'}")
        client.post("/api/start", payload)

        deadline = time.monotonic() + args.timeout
        last_log = 0
        while time.monotonic() < deadline:
            state = client.get("/api/state?since=0")
            for index, task in enumerate(state.get("tasks") or []):
                status = task.get("status")
                if seen.get(index) != status:
                    duration = task.get("duration") or 0
                    print(f"  {index + 1:>2}. {task['name'][:20]:<22} {status:<10} {duration:>6.1f}s")
                    seen[index] = status

            logs = state.get("logs") or []
            for line in logs[last_log:]:
                if line["level"] in ("warn", "error"):
                    print(f"      {line['time']} [{line['level']}] {line['message'][:70]}")
            last_log = len(logs)

            if state.get("status") not in RUNNING:
                break
            time.sleep(4)

        state = client.get("/api/state?since=0")
        spent = time.monotonic() - began
        status = state.get("status")
        summary = state.get("summary") or {}
        tasks = state.get("tasks") or []
        total = sum((task.get("duration") or 0) for task in tasks)

        print(f"\n状态：{status} / {summary}")
        print(f"墙钟 {spent:.0f}s，任务耗时合计 {total:.0f}s")
        ok = [task for task in tasks if task.get("status") == "succeeded"]
        bad = [task for task in tasks if task.get("status") in ("failed", "timed_out")]
        skipped = [task for task in tasks if task.get("status") == "skipped"]
        print(f"成功 {len(ok)} 项，失败 {len(bad)} 项，跳过 {len(skipped)} 项")
        for task in bad:
            print(f"  失败：{task['name']}（{task.get('duration') or 0:.0f}s）")
        code = 0 if status == "completed" and not bad else 1
    finally:
        stop_service(service)
    return code


if __name__ == "__main__":
    sys.exit(main())
