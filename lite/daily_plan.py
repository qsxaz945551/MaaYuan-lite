"""Build a concrete daily task sequence from the Lite profile."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROFILE = ROOT / "lite" / "daily-profile.json"


def load_profile(path: Path = DEFAULT_PROFILE) -> dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as handle:
        profile = json.load(handle)
    if profile.get("schema_version") != 2:
        raise ValueError("Unsupported daily-profile schema")
    return profile


def _resolve_choice(choice: dict[str, Any], selection: str | None) -> str:
    value = selection or choice["default"]
    if value in choice["options"]:
        return value
    matches = [option for option in choice["options"] if value in option]
    if len(matches) == 1:
        return matches[0]
    raise ValueError(
        f"Unknown choice {value!r}; expected one of {choice['options']}"
    )


def window_open(activity: dict[str, Any], now: datetime) -> bool:
    """Whether a time-gated activity is open right now (local clock).

    每日进膳 16:00 开放、24:00 结束，所以「开没开」完全由本机时间决定，
    不需要用户手动开关。跨夜窗口（如 22:00–02:00）也支持。
    """
    start = int(activity.get("start_hour", 0))
    end = int(activity.get("end_hour", 24))
    hour = now.hour
    if start <= end:
        return start <= hour < end
    return hour >= start or hour < end


def build_plan(
    profile: dict[str, Any],
    *,
    training: str | None = None,
    include_seasonal: bool = True,
    now: datetime | None = None,
) -> dict[str, Any]:
    tasks: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    moment = now or datetime.now()

    for item in profile["daily_order"]:
        item_type = item["type"]
        if item_type == "task":
            tasks.append({"name": item["name"], "kind": "daily"})
        elif item_type == "choice":
            name = _resolve_choice(item, training)
            tasks.append(
                {
                    "name": name,
                    "kind": "daily",
                    "slot": item["id"],
                }
            )
        elif item_type == "optional_task":
            group = item.get("group")
            if group == "seasonal_daily" and not include_seasonal:
                skipped.append(
                    {
                        "name": item["name"],
                        "reason": "seasonal_daily_disabled",
                    }
                )
                continue
            if group == "time_window" and not window_open(
                item.get("activity") or {}, moment
            ):
                skipped.append(
                    {
                        "name": item["name"],
                        "reason": "time_window_closed",
                    }
                )
                continue
            task = {
                "name": item["name"],
                "kind": "seasonal_daily",
                "on_unavailable": item.get("on_unavailable", "skip"),
                "timeout_sec": item.get("timeout_sec"),
                "retries": item.get("retries", 0),
            }
            if item.get("probe"):
                task["probe"] = item["probe"]
            tasks.append(task)
        else:
            raise ValueError(f"Unknown daily_order item type: {item_type}")

    names = [task["name"] for task in tasks]
    if len(names) != len(set(names)):
        raise ValueError(f"Daily plan contains duplicate tasks: {names}")
    return {"tasks": tasks, "skipped": skipped, "count": len(tasks)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", type=Path, default=DEFAULT_PROFILE)
    parser.add_argument(
        "--training",
        choices=["修为", "铜钱", "经验"],
        default=None,
        help="历练三选一；默认取 profile 中的 default",
    )
    parser.add_argument(
        "--without-dungeon",
        action="store_true",
        help="地宫活动关闭时跳过该任务",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    profile = load_profile(args.profile)
    plan = build_plan(
        profile,
        training=args.training,
        include_seasonal=not args.without_dungeon,
    )
    payload = json.dumps(plan, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
        print(f"Wrote {args.output}")
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
