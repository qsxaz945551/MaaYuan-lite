"""Resolve interface task options into a MaaFramework pipeline override."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from .deepmerge import deep_merge
from .task_options_service import resolve_index


ROOT = Path(__file__).resolve().parents[1]


def merge_pipeline(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    """Thin alias kept for call sites; see ``lite.deepmerge``."""
    return deep_merge(base, patch, copy_values=True)


def _case_index(
    group: dict[str, Any],
    selected: dict[str, Any],
    name: str,
    notes: list[str] | None = None,
) -> int:
    """按名字优先解析（见 task_options_service.resolve_index）。

    只有一份实现：UI 显示和实际执行必须用同一套规则，否则界面显示 A、
    跑的是 B —— 这正是「两处解析各写一遍」会带来的问题。
    """
    return resolve_index(
        group, selected, name, note=(notes.append if notes is not None else None)
    )


def _substitute(value: Any, values: dict[str, str]) -> Any:
    if isinstance(value, str):
        for key, raw in values.items():
            value = value.replace("{" + key + "}", str(raw))
        return value
    if isinstance(value, list):
        return [_substitute(item, values) for item in value]
    if isinstance(value, dict):
        return {key: _substitute(item, values) for key, item in value.items()}
    return value


def _apply_option_group(
    group_name: str,
    interface: dict[str, Any],
    selected: dict[str, Any],
    override: dict[str, Any],
    visiting: set[str],
    inputs: dict[str, dict[str, str]] | None = None,
    notes: list[str] | None = None,
) -> dict[str, Any]:
    if group_name in visiting:
        raise ValueError(f"Recursive option group: {group_name}")
    group = interface.get("option", {}).get(group_name)
    if not isinstance(group, dict):
        raise ValueError(f"Unknown option group: {group_name}")

    if group.get("type") == "input":
        saved = (inputs or {}).get(group_name, {})
        values = {
            field.get("name"): str(saved.get(field.get("name"), field.get("default", "")))
            for field in group.get("inputs", [])
        }
        patch = _substitute(copy.deepcopy(group.get("pipeline_override", {})), values)
        return merge_pipeline(override, patch)

    index = _case_index(group, selected, group_name, notes)
    case = group["cases"][index]
    override = merge_pipeline(override, case.get("pipeline_override", {}))

    visiting = visiting | {group_name}
    for child_name in case.get("option", []) or []:
        override = _apply_option_group(
            child_name, interface, selected, override, visiting, inputs, notes
        )
    return override


def build_task_override(
    interface: dict[str, Any],
    task: dict[str, Any],
    selected: dict[str, Any] | None = None,
    inputs: dict[str, dict[str, str]] | None = None,
    notes: list[str] | None = None,
) -> dict[str, Any]:
    """``notes`` 收集解析过程中值得告诉用户的偏差（如选项值已不存在）。"""
    selected = selected or {}
    override = copy.deepcopy(task.get("pipeline_override", {}))
    visiting: set[str] = set()
    for group_name in task.get("option", []) or []:
        override = _apply_option_group(
            group_name, interface, selected, override, visiting, inputs, notes
        )
    return override


def load_options_snapshot(path: Path | None = None) -> dict[str, dict[str, int]]:
    path = path or ROOT / "lite" / "task-options.json"
    with path.open("r", encoding="utf-8-sig") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("task-options.json must contain an object")
    return data
