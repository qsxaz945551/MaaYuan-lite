"""Gate a resource update: reject it before it replaces a working copy.

The checks mirror what ``devtools/check_upstream.py`` reports, but live in the
runtime package so the updater can call them without shipping devtools.

Usage:
    python -m lite.update_gate
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from .daily_plan import load_profile
from .pipeline_fixes import FIXES, NEW_NODES
from .round_progress import ROUND_MARKERS
from .task_options_service import load_selection


def _pipeline_nodes(resource_root: Path) -> set[str]:
    nodes: set[str] = set()
    pipeline = resource_root / "pipeline"
    if not pipeline.is_dir():
        return nodes
    for path in pipeline.rglob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict):
            nodes.update(key for key, value in data.items() if isinstance(value, dict))
    return nodes


def _task_names(interface_path: Path) -> set[str]:
    if not interface_path.is_file():
        return set()
    try:
        data = json.loads(interface_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    return {str(task.get("name", "")) for task in data.get("task", [])}


def validate(project_root: Path, resource_root: Path | None = None) -> list[str]:
    """Return human-readable problems; empty list means the update is safe."""
    resource_root = resource_root or project_root / "assets" / "resource" / "base"
    interface = project_root / "build" / "generated" / "interface.json"
    if not interface.is_file():
        interface = project_root / "assets" / "interface.json"

    problems: list[str] = []
    nodes = _pipeline_nodes(resource_root)
    if len(nodes) < 100:
        problems.append(f"流水线节点过少（{len(nodes)}），资源可能不完整")
        return problems

    names = _task_names(interface)
    if len(names) < 20:
        problems.append(f"interface 任务过少（{len(names)}）")

    try:
        profile = load_profile()
    except Exception as error:  # noqa: BLE001
        problems.append(f"daily-profile 读取失败：{error}")
        profile = {}

    for item in profile.get("daily_order", []):
        name = item.get("name") if isinstance(item, dict) else str(item)
        if name and name not in names:
            problems.append(f"日常链任务不存在：{name}")

    for entry, patch in FIXES.items():
        added = NEW_NODES.get(entry, set())
        for node in patch:
            if node in added:
                # 补丁新增的节点，上游当然没有。
                continue
            if node not in nodes:
                problems.append(f"pipeline_fixes[{entry}] 依赖的节点不存在：{node}")

    for entry, markers in ROUND_MARKERS.items():
        for node in markers:
            if node not in nodes:
                problems.append(f"round_progress[{entry}] 依赖的节点不存在：{node}")

    try:
        selection = load_selection()
    except Exception:  # noqa: BLE001
        selection = {}
    for task_name in selection:
        if task_name not in names:
            problems.append(f"task-options 里的任务不存在：{task_name}")

    return problems


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    problems = validate(root)
    if problems:
        print("兼容性检查未通过：")
        for item in problems:
            print("  -", item)
        return 1
    print("兼容性检查通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
