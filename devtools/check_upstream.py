"""检查 Lite 依赖的上游资源是否与安装目录一致。

游戏更新会带来新的 pipeline / interface。Lite 若继续用旧副本，症状是
"任务失败""点了没反应"，而日志里看不出原因，所以先查一致性再跑日常。

校验三件事：
1. 资源与 Agent 是否与上游安装一致（逐文件比大小）
2. daily-profile / task-options 引用的任务名是否仍然存在
3. pipeline_fixes 与 round_progress 依赖的节点名是否仍然存在

用法： python devtools/check_upstream.py [--verbose]
退出码：0 一致，1 有漂移或引用失效
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lite.pipeline_fixes import FIXES  # noqa: E402
from lite.round_progress import ROUND_MARKERS  # noqa: E402

CONFIG = ROOT / "lite" / "runtime-config.json"
PROFILE = ROOT / "lite" / "daily-profile.json"
OPTIONS = ROOT / "lite" / "task-options.json"


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def tree(root: Path) -> dict[str, int]:
    if not root.is_dir():
        return {}
    return {
        str(p.relative_to(root)).replace("\\", "/"): p.stat().st_size
        for p in root.rglob("*")
        if p.is_file()
    }


def compare(label: str, mine: Path, theirs: Path, verbose: bool) -> int:
    print(f"\n== {label} ==")
    print(f"   Lite: {mine}")
    print(f"   上游: {theirs}")
    if not theirs.is_dir():
        print("   [跳过] 上游目录不存在")
        return 0
    a, b = tree(mine), tree(theirs)
    if not a:
        print("   [跳过] 本地副本不存在（已改为直接跟随上游）")
        return 0
    only_orig = sorted(set(b) - set(a))
    only_mine = sorted(set(a) - set(b))
    changed = sorted(k for k in set(a) & set(b) if a[k] != b[k])
    if not (only_orig or changed):
        print(f"   一致（{len(a)} 个文件）")
        return 0
    print(
        f"   漂移：上游新增 {len(only_orig)}，内容不同 {len(changed)}，本地独有 {len(only_mine)}"
    )
    if verbose:
        for name in (only_orig + changed)[:15]:
            print(f"     - {name}")
    return len(only_orig) + len(changed)


def check_task_names(interface: dict) -> list[str]:
    problems: list[str] = []
    names = {task.get("name", "") for task in interface.get("task", [])}
    entries = {task.get("entry", "") for task in interface.get("task", [])}

    profile = load_json(PROFILE)
    for item in profile.get("daily_order", []):
        kind = item.get("type")
        if kind == "task" and item["name"] not in names:
            problems.append(f"daily-profile 任务不存在：{item['name']}")
        elif kind == "choice":
            problems += [
                f"daily-profile 历练选项不存在：{option}"
                for option in item.get("options", [])
                if option not in names
            ]
        elif kind == "optional_task" and item["name"] not in names:
            problems.append(f"daily-profile 可选任务不存在：{item['name']}")
    for name in profile.get("pinned_in_library", []):
        if name not in names:
            problems.append(f"置顶任务不存在：{name}")
    for name in profile.get("hidden_in_library", []):
        if name not in names:
            problems.append(f"隐藏名单任务不存在：{name}")

    if OPTIONS.is_file():
        problems += [
            f"task-options 里的任务不存在：{name}"
            for name in load_json(OPTIONS)
            if name not in names
        ]

    for entry in ROUND_MARKERS:
        if entry not in entries:
            problems.append(f"轮次标记的 entry 不存在：{entry}")

    return problems


def pipeline_nodes(pipeline_root: Path) -> set[str]:
    nodes: set[str] = set()
    if not pipeline_root.is_dir():
        return nodes
    for path in pipeline_root.rglob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(data, dict):
            nodes.update(key for key, value in data.items() if isinstance(value, dict))
    return nodes


def check_nodes(pipeline_root: Path) -> list[str]:
    """pipeline_fixes / round_progress 依赖的节点是否还在这套流水线里。"""
    available = pipeline_nodes(pipeline_root)
    if not available:
        return [f"流水线目录不可读：{pipeline_root}"]

    problems: list[str] = []
    for entry, patch in FIXES.items():
        for node in patch:
            if node not in available:
                problems.append(f"pipeline_fixes[{entry}] 的节点不存在：{node}")
    for entry, markers in ROUND_MARKERS.items():
        for node in markers:
            if node not in available:
                problems.append(f"round_progress[{entry}] 的节点不存在：{node}")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    config = load_json(CONFIG)
    runtime_root = Path(config["runtime_root"])
    resource_override = str(config.get("resource_root") or "").strip()
    agent_override = str(config.get("agent_root") or "").strip()
    source_override = str(config.get("interface_source") or "").strip()

    print(f"runtime_root : {runtime_root}")
    print(f"resource     : {resource_override or '项目内副本 assets/resource/base'}")
    print(f"agent        : {agent_override or '项目内副本 agent/'}")
    print(f"interface    : {source_override or '项目内副本 assets/interface.json'}")

    resource_root = (
        Path(resource_override)
        if resource_override
        else ROOT / "assets" / "resource" / "base"
    )
    agent_root = Path(agent_override) if agent_override else ROOT / "agent"
    source = (
        Path(source_override) if source_override else ROOT / "assets" / "interface.json"
    )

    drift = 0
    drift += compare(
        "资源 pipeline", resource_root, runtime_root / "resource" / "base", args.verbose
    )
    drift += compare("Agent 脚本", agent_root, runtime_root / "agent", args.verbose)

    print("\n== interface.json ==")
    if not source.is_file():
        print(f"   [错误] 找不到 {source}")
        return 1
    interface = load_json(source)
    upstream_interface = runtime_root / "interface.json"
    if upstream_interface.is_file() and source.resolve() != upstream_interface.resolve():
        same = source.stat().st_size == upstream_interface.stat().st_size
        print(
            f"   本地副本 {source.stat().st_size} 字节 / 上游 {upstream_interface.stat().st_size} 字节"
            f" → {'一致' if same else '不同'}"
        )
        drift += 0 if same else 1
    else:
        print("   直接使用上游文件")

    name_problems = check_task_names(interface)
    print("\n== 任务名引用 ==")
    if name_problems:
        for item in name_problems[:20]:
            print(f"   - {item}")
    else:
        print(f"   全部可解析（{len(interface.get('task', []))} 个任务）")

    node_problems = check_nodes(resource_root / "pipeline")
    print("\n== 节点引用（补丁与轮次标记） ==")
    if node_problems:
        for item in node_problems[:20]:
            print(f"   - {item}")
    else:
        total = sum(len(v) for v in FIXES.values()) + sum(
            len(v) for v in ROUND_MARKERS.values()
        )
        print(f"   全部存在（{total} 个节点）")

    print("\n" + "=" * 46)
    problems = len(name_problems) + len(node_problems)
    if drift or problems:
        print(f"结论：需要处理（漂移 {drift} 处，引用问题 {problems} 处）")
        if drift:
            print("提示：把 lite/runtime-config.json 的 resource_root / agent_root /")
            print("      interface_source 指向上游安装，即可跟随更新而不再复制。")
        return 1
    print("结论：与上游一致")
    return 0


if __name__ == "__main__":
    sys.exit(main())
