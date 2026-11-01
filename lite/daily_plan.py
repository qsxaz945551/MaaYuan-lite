"""Build a concrete daily task sequence from the Lite profile."""

from __future__ import annotations

import argparse
import json
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


def build_plan(
    profile: dict[str, Any],
    *,
    training: str | None = None,
    include_seasonal: bool = True,
) -> dict[str, Any]:
    tasks: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

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
            if item.get("group") == "seasonal_daily" and not include_seasonal:
                skipped.append(
                    {
                        "name": item["name"],
                        "reason": "seasonal_daily_disabled",
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
