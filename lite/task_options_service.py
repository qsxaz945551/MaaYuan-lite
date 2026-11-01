"""Describe and edit per-task option selections for the local control panel."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SELECTION = ROOT / "lite" / "task-options.json"
DEFAULT_INPUTS = ROOT / "lite" / "task-inputs.json"


class OptionError(ValueError):
    pass


def load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    with path.open("r", encoding="utf-8-sig") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise OptionError(f"{path.name} must contain an object")
    return data


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    os.replace(temp, path)


def load_selection(path: Path | None = None) -> dict[str, dict[str, int]]:
    return load_json(path or DEFAULT_SELECTION)


def load_inputs(path: Path | None = None) -> dict[str, dict[str, dict[str, str]]]:
    return load_json(path or DEFAULT_INPUTS)


def default_index(group: dict[str, Any]) -> int:
    cases = group.get("cases") or []
    name = group.get("default_case")
    if name is not None:
        names = [case.get("name") for case in cases]
        if name in names:
            return names.index(name)
    return 0


def resolve_index(group: dict[str, Any], selected: dict[str, int] | None, name: str) -> int:
    cases = group.get("cases") or []
    if not cases:
        return 0
    value = (selected or {}).get(name)
    index = default_index(group) if value is None else int(value)
    if index < 0 or index >= len(cases):
        index = default_index(group)
    return index


def group_index_map(interface: dict[str, Any], task: dict[str, Any]) -> dict[str, str]:
    """Map every reachable option group of a task to its parent group."""
    groups = interface.get("option", {})
    parents: dict[str, str] = {}
    visiting: set[str] = set()

    def walk(name: str, parent: str | None) -> None:
        if name in visiting or name in parents:
            return
        group = groups.get(name)
        if not isinstance(group, dict):
            return
        visiting.add(name)
        parents[name] = parent or ""
        for case in group.get("cases", []):
            for child in case.get("option") or []:
                walk(child, name)
        visiting.discard(name)

    for name in task.get("option") or []:
        walk(name, None)
    return parents


def describe_task(
    interface: dict[str, Any],
    task: dict[str, Any],
    selected: dict[str, int] | None,
    inputs: dict[str, dict[str, str]] | None = None,
) -> list[dict[str, Any]]:
    """Flatten a task's option tree following the currently selected cases."""
    groups = interface.get("option", {})
    inputs = inputs or {}
    described: list[dict[str, Any]] = []
    visiting: set[str] = set()

    def walk(name: str, depth: int) -> None:
        group = groups.get(name)
        if not isinstance(group, dict) or name in visiting:
            return
        visiting.add(name)
        kind = group.get("type", "select")

        if kind == "input":
            saved = inputs.get(name, {})
            fields = []
            for field in group.get("inputs", []):
                field_name = field.get("name", "")
                fields.append(
                    {
                        "name": field_name,
                        "label": field.get("label", field_name),
                        "description": field.get("description", ""),
                        "default": str(field.get("default", "")),
                        "value": str(saved.get(field_name, field.get("default", ""))),
                    }
                )
            described.append(
                {
                    "group": name,
                    "type": "input",
                    "depth": depth,
                    "label": group.get("label", name),
                    "fields": fields,
                }
            )
            visiting.discard(name)
            return

        cases = group.get("cases") or []
        if not cases:
            visiting.discard(name)
            return
        index = resolve_index(group, selected, name)
        case = cases[index]
        described.append(
            {
                "group": name,
                "type": kind,
                "depth": depth,
                "description": group.get("description", ""),
                "cases": [case_item.get("name", "") for case_item in cases],
                "selected": index,
            }
        )
        for child in case.get("option") or []:
            walk(child, depth + 1)
        visiting.discard(name)

    for name in task.get("option") or []:
        walk(name, 0)
    return described


def describe_tasks(
    interface: dict[str, Any],
    task_names: Iterable[str],
    selection: dict[str, dict[str, int]] | None = None,
    inputs: dict[str, dict[str, dict[str, str]]] | None = None,
) -> list[dict[str, Any]]:
    selection = selection or {}
    inputs = inputs or {}
    by_name = {task.get("name"): task for task in interface.get("task", [])}
    result = []
    for name in task_names:
        task = by_name.get(name)
        if task is None:
            continue
        result.append(
            {
                "name": name,
                "entry": task.get("entry", ""),
                "groups": describe_task(
                    interface, task, selection.get(name, {}), inputs.get(name, {})
                ),
            }
        )
    return result


def _validate_group_index(group: dict[str, Any], index: Any, name: str) -> int:
    cases = group.get("cases") or []
    if not isinstance(cases, list) or not cases:
        raise OptionError(f"Option {name!r} has no cases")
    if isinstance(index, bool) or not isinstance(index, int):
        raise OptionError(f"Option {name!r} index must be an integer")
    if index < 0 or index >= len(cases):
        raise OptionError(f"Option {name!r} index out of range: {index}")
    return index


def apply_change(
    interface: dict[str, Any],
    payload: dict[str, Any],
    selection: dict[str, dict[str, int]],
    inputs: dict[str, dict[str, dict[str, str]]],
) -> tuple[dict[str, dict[str, int]], dict[str, dict[str, dict[str, str]]]]:
    """Validate one UI change and return updated (selection, inputs)."""
    task_name = payload.get("task")
    group_name = payload.get("group")
    if not isinstance(task_name, str) or not isinstance(group_name, str):
        raise OptionError("task and group are required")

    task = next(
        (item for item in interface.get("task", []) if item.get("name") == task_name),
        None,
    )
    if task is None:
        raise OptionError(f"Unknown task: {task_name}")

    reachable = group_index_map(interface, task)
    if group_name not in reachable:
        raise OptionError(f"Option {group_name!r} does not belong to task {task_name!r}")

    group = interface["option"][group_name]
    kind = group.get("type", "select")

    if kind == "input":
        values = payload.get("inputs")
        if not isinstance(values, dict):
            raise OptionError("inputs object is required for input options")
        allowed = {field.get("name") for field in group.get("inputs", [])}
        unknown = sorted(set(values) - allowed)
        if unknown:
            raise OptionError(f"Unknown input fields: {unknown}")
        merged = dict(inputs.get(task_name, {}).get(group_name, {}))
        for key, value in values.items():
            merged[key] = str(value)
        inputs.setdefault(task_name, {})[group_name] = merged
        return selection, inputs

    index = _validate_group_index(group, payload.get("index"), group_name)
    selection.setdefault(task_name, {})[group_name] = index
    return selection, inputs
