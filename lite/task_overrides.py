"""Resolve interface task options into a MaaFramework pipeline override."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from .deepmerge import deep_merge


ROOT = Path(__file__).resolve().parents[1]


def merge_pipeline(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    """Thin alias kept for call sites; see ``lite.deepmerge``."""
    return deep_merge(base, patch, copy_values=True)


def _case_index(group: dict[str, Any], selected: dict[str, int], name: str) -> int:
    if name in selected:
        index = int(selected[name])
    elif "default_case" in group:
        names = [case.get("name") for case in group.get("cases", [])]
        try:
            index = names.index(group["default_case"])
        except ValueError:
            index = 0
    else:
        index = 0
    if index < 0 or index >= len(group.get("cases", [])):
        raise ValueError(f"Option {name!r} index out of range: {index}")
    return index


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
    selected: dict[str, int],
    override: dict[str, Any],
    visiting: set[str],
    inputs: dict[str, dict[str, str]] | None = None,
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

    index = _case_index(group, selected, group_name)
    case = group["cases"][index]
    override = merge_pipeline(override, case.get("pipeline_override", {}))

    visiting = visiting | {group_name}
    for child_name in case.get("option", []) or []:
        override = _apply_option_group(
            child_name, interface, selected, override, visiting, inputs
        )
    return override


def build_task_override(
    interface: dict[str, Any],
    task: dict[str, Any],
    selected: dict[str, int] | None = None,
    inputs: dict[str, dict[str, str]] | None = None,
) -> dict[str, Any]:
    selected = selected or {}
    override = copy.deepcopy(task.get("pipeline_override", {}))
    visiting: set[str] = set()
    for group_name in task.get("option", []) or []:
        override = _apply_option_group(
            group_name, interface, selected, override, visiting, inputs
        )
    return override


def load_options_snapshot(path: Path | None = None) -> dict[str, dict[str, int]]:
    path = path or ROOT / "lite" / "task-options.json"
    with path.open("r", encoding="utf-8-sig") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("task-options.json must contain an object")
    return data
