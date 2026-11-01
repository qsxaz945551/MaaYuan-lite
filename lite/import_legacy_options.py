"""Import task option selections from a legacy MaaYuan config.

This is a one-time migration helper. The generated snapshot is committed so
the Lite app does not depend on the old installation at runtime.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def flatten_options(items: list[dict[str, Any]]) -> dict[str, int]:
    result: dict[str, int] = {}
    for item in items:
        name = item.get("name")
        if name:
            result[name] = int(item.get("index", 0))
        for child in item.get("sub_options", []) or []:
            result.update(flatten_options([child]))
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("legacy_config", type=Path)
    parser.add_argument("--interface", type=Path, default=ROOT / "build" / "generated" / "interface.json")
    parser.add_argument("--output", type=Path, default=ROOT / "lite" / "task-options.json")
    args = parser.parse_args()

    legacy = json.loads(args.legacy_config.read_text(encoding="utf-8-sig"))
    interface = json.loads(args.interface.read_text(encoding="utf-8"))
    allowed = {task["name"] for task in interface["task"]}
    option_groups = interface.get("option", {})

    snapshot: dict[str, dict[str, int]] = {}
    unknown_options: dict[str, list[str]] = {}
    for task in legacy.get("Instance.default.TaskItems", []):
        name = task.get("name")
        if name not in allowed:
            continue
        selected = flatten_options(task.get("option", []))
        valid = {key: value for key, value in selected.items() if key in option_groups}
        snapshot[name] = valid
        missing = sorted(set(selected) - set(valid))
        if missing:
            unknown_options[name] = missing

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Imported options for {len(snapshot)} tasks -> {args.output}")
    if unknown_options:
        print("Ignored unknown option names:")
        for task, names in unknown_options.items():
            print(f"  {task}: {', '.join(names)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
