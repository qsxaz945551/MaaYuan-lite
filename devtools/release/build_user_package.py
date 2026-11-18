"""Build a user-only copy of an existing release package.

    python devtools/release/build_user_package.py                 # dist/<版本>-user
    python devtools/release/build_user_package.py --source dist/MaaYuan-Lite-0.3.16

和 `build_release.py` 的区别：那个是"能跑的完整包"，会把 LITE.md / MANIFEST.md /
docs / build/generated 一并放进去；这个只拷用户真正需要的东西，给最终用户下载用。

白名单以外的任何东西都不会进包：开发者文档、审查报告、性能采样、运行时日志、
`runtime/` 里累积的 settings/port/last-run 等。
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "lite"))
from version import VERSION  # noqa: E402

# 直接放在包根的文件
ROOT_FILES = [
    "MaaYuanLite.Desktop.exe",
    "MaaYuanLite.Desktop.dll",
    "MaaYuanLite.Desktop.deps.json",
    "MaaYuanLite.Desktop.runtimeconfig.json",
    "start-lite.bat",
    "app.py",
]

# 从仓库根取最新版本（而不是包里的旧副本）
REPO_FILES = ["README.md", "NOTICE.md", "LICENSE"]

# 整目录拷贝
TREES = ["lite", "agent", "assets", "runtime_env", "config", "build"]

# 目录内这些不要
EXCLUDE_DIRS = {"__pycache__", "tests", "logs", "on_error", "failures", ".git"}
EXCLUDE_SUFFIX = {".pyc", ".pyo", ".pdb"}


def ignore(_directory: str, names: list[str]) -> list[str]:
    return [
        name
        for name in names
        if name in EXCLUDE_DIRS or Path(name).suffix in EXCLUDE_SUFFIX
    ]


def human(path: Path) -> str:
    size = sum(p.stat().st_size for p in path.rglob("*") if p.is_file())
    return f"{size / 1048576:.1f} MB"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default=None, help="已构建好的发布包目录")
    parser.add_argument("--out", default="dist")
    parser.add_argument("--name", default=None, help="目标文件夹名，默认 <版本>-user")
    args = parser.parse_args()

    source = Path(args.source) if args.source else ROOT / "dist" / f"MaaYuan-Lite-{VERSION}"
    if not (source / "MaaYuanLite.Desktop.exe").is_file():
        print(f"源包不完整：{source}")
        return 1

    name = args.name or f"MaaYuan-Lite-{VERSION}-user"
    target = ROOT / args.out / name
    if target.exists():
        print(f"清理旧产物：{target}")
        shutil.rmtree(target)
    target.mkdir(parents=True)

    for item in ROOT_FILES:
        shutil.copy2(source / item, target / item)
    for item in REPO_FILES:
        if (ROOT / item).is_file():
            shutil.copy2(ROOT / item, target / item)
        elif (source / item).is_file():
            shutil.copy2(source / item, target / item)

    for tree in TREES:
        origin = source / tree
        if not origin.is_dir():
            print(f"  [跳过] {tree}（源包没有）")
            continue
        shutil.copytree(origin, target / tree, ignore=ignore, dirs_exist_ok=True)

    # README 里引用了 API 契约，带上这一份（其余 docs 是维护者材料）
    contract = ROOT / "docs" / "api-contract.md"
    if contract.is_file():
        (target / "docs").mkdir(exist_ok=True)
        shutil.copy2(contract, target / "docs" / "api-contract.md")

    # 用户包里不该有任何运行期状态：settings / port / 上次结果 / 日志
    for junk in ("runtime", "debug"):
        shutil.rmtree(target / junk, ignore_errors=True)
    for junk in ("lite/tests",):
        shutil.rmtree(target / junk, ignore_errors=True)

    print(f"\n目标：{target}")
    for item in sorted(target.iterdir()):
        size = human(item) if item.is_dir() else f"{item.stat().st_size / 1024:.0f} KB"
        print(f"  {item.name:<34}{size}")
    print(f"\n合计：{human(target)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
