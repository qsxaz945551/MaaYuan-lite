"""Describe and edit per-task option selections for the local control panel."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]

# 入库的默认值：随代码走，运行时只读。用户勾选写进 runtime/，否则每改一次选项，
# git 工作区就脏一次，换台机器还会把上一个人选过的档位带进新装。
SEED_SELECTION = ROOT / "lite" / "task-options.json"
SEED_INPUTS = ROOT / "lite" / "task-inputs.json"
DEFAULT_SELECTION = ROOT / "runtime" / "task-options.json"
DEFAULT_INPUTS = ROOT / "runtime" / "task-inputs.json"


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
    try:
        os.replace(temp, path)
    except PermissionError:
        # Antivirus / folder redirection can hold the target open; replacing it
        # would fail where overwriting still works. Losing atomicity here is
        # better than losing the user's selection.
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        temp.unlink(missing_ok=True)


def load_selection(path: Path | None = None) -> dict[str, dict[str, int]]:
    if path is not None:
        return load_json(path)
    # 用户还没改过任何选项时没有 runtime/ 文件，此时用入库默认值。
    return load_json(DEFAULT_SELECTION) or load_json(SEED_SELECTION)


def load_inputs(path: Path | None = None) -> dict[str, dict[str, dict[str, str]]]:
    if path is not None:
        return load_json(path)
    return load_json(DEFAULT_INPUTS) or load_json(SEED_INPUTS)


def default_index(group: dict[str, Any]) -> int:
    cases = group.get("cases") or []
    name = group.get("default_case")
    if name is not None:
        names = [case.get("name") for case in cases]
        if name in names:
            return names.index(name)
    return 0


def resolve_index(
    group: dict[str, Any],
    selected: dict[str, Any] | None,
    name: str,
    note: Any = None,
) -> int:
    """Resolve one option group to a case index.

    保存的是索引，而索引的含义由上游 ``interface.json`` 里 ``cases`` 的顺序决定。
    上游一旦增删或重排某个选项的可选值，同一个数字就指向别的值——任务照常开始、
    照常成功，只是选错了（例如「王庭贸易-最高」变成「西域贸易」），日志里看不出来。

    所以新格式同时记下所选值的**名字**：``{"index": 3, "label": "王庭贸易-最高"}``。
    解析时优先按名字找回索引，名字找不到才退回索引，并通过 ``note`` 报告。
    旧格式（纯 int）仍然可读，会在保存时自动升级。
    """
    cases = group.get("cases") or []
    if not cases:
        return 0

    index, label = _split_value((selected or {}).get(name))

    if label is not None:
        found = _label_index(cases, label)
        if found is not None:
            return found
        _say(
            note,
            f"选项「{name}」原先选的是「{label}」，当前资源里找不到这个值，"
            f"已退回索引 {index if index is not None else '默认'}。",
        )

    if index is None:
        return default_index(group)
    if index < 0 or index >= len(cases):
        _say(note, f"选项「{name}」保存的索引 {index} 超出范围，已改用默认值。")
        return default_index(group)
    return index


def _split_value(value: Any) -> tuple[int | None, str | None]:
    """Accept both the new ``{"index", "label"}`` form and a legacy int."""
    if isinstance(value, dict):
        index = value.get("index")
        label = value.get("label")
        return (
            index if isinstance(index, int) and not isinstance(index, bool) else None,
            label if isinstance(label, str) and label else None,
        )
    if isinstance(value, bool):
        return None, None
    if isinstance(value, int):
        return value, None
    return None, None


def _label_index(cases: list[dict[str, Any]], label: str) -> int | None:
    for index, case in enumerate(cases):
        if case.get("name") == label:
            return index
    return None


def _say(note: Any, message: str) -> None:
    if note is None:
        return
    try:
        note(message)
    except Exception:  # noqa: BLE001 - 报告问题不能影响解析
        pass


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
    cases = group.get("cases") or []
    # 索引和名字一起存：上游重排 cases 后，光靠索引会指向别的值（静默选错）。
    label = cases[index].get("name") if index < len(cases) else None
    selection.setdefault(task_name, {})[group_name] = {"index": index, "label": label}
    return selection, inputs


def backfill_labels(
    interface: dict[str, Any], path: Path | None = None
) -> int:
    """给旧格式（纯 int）的条目补上所选值的名字。

    升级到 0.2.2 之前保存的选择只有索引。趁当前 interface 还认得这个索引，
    把名字记下来，以后上游重排就不会指错。只补能确定的条目，其它原样保留。
    """
    target = path or DEFAULT_SELECTION
    selection = load_json(target) if path is not None else load_selection()
    if not selection:
        return 0

    groups = interface.get("option", {})
    changed = 0
    for task_name, options in selection.items():
        if not isinstance(options, dict):
            continue
        for group_name, value in list(options.items()):
            if isinstance(value, dict):
                continue
            group = groups.get(group_name)
            if not isinstance(group, dict):
                continue
            cases = group.get("cases") or []
            index, _label = _split_value(value)
            if index is None or not (0 <= index < len(cases)):
                continue
            options[group_name] = {"index": index, "label": cases[index].get("name")}
            changed += 1

    if changed:
        write_json(target, selection)
    return changed
