"""Apply the MaaYuan Lite scope to a generated interface file.

The upstream interface stays untouched. Build output goes to
build/generated/interface.json so we can audit every change.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:  # imported as lite.apply_scope
    from .version import VERSION
except ImportError:  # run directly: python lite/apply_scope.py
    from version import VERSION


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SCOPE = ROOT / "lite" / "scope.json"
DEFAULT_SOURCE = ROOT / "assets" / "interface.json"
DEFAULT_OUTPUT = ROOT / "build" / "generated" / "interface.json"
REPORT_OUTPUT = ROOT / "build" / "generated" / "scope-report.json"
DEFAULT_OVERRIDES = ROOT / "lite" / "pipeline-overrides.json"
DEFAULT_CONFIG = ROOT / "lite" / "runtime-config.json"


def resolve_source(config_path: Path = DEFAULT_CONFIG) -> Path:
    """界面定义默认取项目内副本，可由配置指向上游安装以跟随更新。"""
    try:
        config = json.loads(config_path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return DEFAULT_SOURCE
    override = str(config.get("interface_source") or "").strip()
    if not override:
        return DEFAULT_SOURCE
    path = Path(override)
    return path if path.is_absolute() else ROOT / path


def merge_dict(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = merge_dict(result[key], value)
        else:
            result[key] = value
    return result


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return value


def apply_scope(
    interface: dict[str, Any],
    scope: dict[str, Any],
    overrides: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    tasks = interface.get("task")
    if not isinstance(tasks, list):
        raise ValueError("interface.json has no task array")

    exclusions = scope.get("tasks", {}).get("exclude", [])
    excluded_names = [item["name"] for item in exclusions]
    duplicate_names = sorted({name for name in excluded_names if excluded_names.count(name) > 1})
    if duplicate_names:
        raise ValueError(f"Duplicate exclusions in scope.json: {duplicate_names}")

    source_names = {task.get("name") for task in tasks if isinstance(task, dict)}
    missing = sorted(set(excluded_names) - source_names)
    if missing:
        raise ValueError(f"Scope references tasks missing from upstream interface: {missing}")

    kept_tasks = [task for task in tasks if task.get("name") not in set(excluded_names)]
    removed_tasks = [task for task in tasks if task.get("name") in set(excluded_names)]

    applied_overrides = []
    overrides = overrides or {}
    task_overrides = overrides.get("tasks", {})
    by_name = {task.get("name"): task for task in kept_tasks if isinstance(task, dict)}
    for task_name, patch in task_overrides.items():
        if task_name not in by_name:
            raise ValueError(f"Pipeline override references unavailable task: {task_name}")
        pipeline_patch = patch.get("pipeline_override")
        if not isinstance(pipeline_patch, dict):
            continue
        task = by_name[task_name]
        task["pipeline_override"] = merge_dict(
            task.get("pipeline_override", {}), pipeline_patch
        )
        applied_overrides.append(
            {
                "task": task_name,
                "nodes": sorted(pipeline_patch),
                "reason": patch.get("reason", ""),
            }
        )

    lite_interface = dict(interface)
    lite_interface["name"] = "MaaYuan Lite"
    lite_interface["custom_title"] = "Maa鸢 Lite"
    lite_interface["version"] = VERSION
    lite_interface["task"] = kept_tasks

    report = {
        "source_task_count": len(tasks),
        "kept_task_count": len(kept_tasks),
        "excluded_task_count": len(removed_tasks),
        "excluded_tasks": [
            {
                "name": task.get("name"),
                "entry": task.get("entry"),
                "reason": next(
                    item.get("reason", "")
                    for item in exclusions
                    if item.get("name") == task.get("name")
                ),
            }
            for task in removed_tasks
        ],
        "kept_tasks": [task.get("name") for task in kept_tasks],
        "ui_modules_removed": scope.get("ui", {}).get("remove", []),
        "ocr_model_quantization": scope.get("constraints", {}).get(
            "ocr_model_quantization", "unknown"
        ),
        "pipeline_overrides": applied_overrides,
    }
    return lite_interface, report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scope", type=Path, default=DEFAULT_SCOPE)
    parser.add_argument(
        "--source",
        type=Path,
        default=None,
        help="上游 interface.json；缺省读取 runtime-config.json 的 interface_source",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=REPORT_OUTPUT)
    parser.add_argument("--overrides", type=Path, default=DEFAULT_OVERRIDES)
    args = parser.parse_args()

    scope = load_json(args.scope)
    source = args.source or resolve_source()
    if not source.is_file():
        print(f"上游 interface.json 不存在：{source}", file=sys.stderr)
        return 1
    interface = load_json(source)
    overrides = load_json(args.overrides) if args.overrides.exists() else {}
    lite_interface, report = apply_scope(interface, scope, overrides)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(lite_interface, handle, ensure_ascii=False, indent=2)
        handle.write("\n")

    with args.report.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
        handle.write("\n")

    print(
        f"Generated {args.output} with {report['kept_task_count']} tasks; "
        f"excluded {report['excluded_task_count']} (source: {source})."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
