"""Upgrade an installed MaaYuan Lite folder in place.

    python devtools/release/upgrade.py --from dist/MaaYuan-Lite-0.3.0            # dry run
    python devtools/release/upgrade.py --from dist/MaaYuan-Lite-0.3.0 --apply

Keeps user state (lite/*.json, runtime/, debug/, on_error/) and replaces code,
resources, agent and the WPF binaries. Config is backed up first.
"""

from __future__ import annotations

import argparse
import shutil
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# Files and folders that belong to the user, never overwritten by an upgrade.
KEEP = [
    "lite/runtime-config.json",
    "lite/task-options.json",
    "lite/task-inputs.json",
    "runtime",
    "debug",
    "on_error",
    "assets/config",
    "assets/.source.json",
    # Lite 自己加的模板图（上游没有这几张），升级时不能被资源包冲掉。
    "assets/resource/base/image/activity_title.png",
    "assets/resource/base/image/lite_event_icon.png",
    "assets/resource/base/image/lite_special_training.png",
]

# What an upgrade actually replaces.
REPLACE_FILES = ["app.py", "start-lite.bat", "NOTICE.md", "LITE.md", "MANIFEST.md"]
REPLACE_DIRS = ["lite", "agent", "assets/resource", "build/generated", "docs"]


def _files_of(folder: Path) -> list[Path]:
    return [path for path in folder.rglob("*") if path.is_file()]


def _copy_file(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def _kept(relative: str) -> bool:
    return any(relative == item or relative.startswith(item + "/") for item in KEEP)


def _copy_tree(source: Path, target: Path, prefix: str) -> None:
    """Copy a replaced folder while honouring KEEP.

    KEEP used to be consulted by the dry run only, so ``plan()`` promised to
    leave a file alone and ``--apply`` overwrote it anyway. Patch images under
    assets/resource live exactly in that blind spot.
    """
    if not source.is_dir():
        return
    for path in _files_of(source):
        relative = f"{prefix}/{path.relative_to(source).as_posix()}"
        if _kept(relative):
            continue
        _copy_file(path, target / path.relative_to(source))


def plan(source: Path, target: Path) -> list[str]:
    """Return the list of paths that would change, for the dry run."""
    changes: list[str] = []
    for name in REPLACE_FILES:
        src = source / name
        dst = target / name
        if src.is_file() and (not dst.is_file() or src.stat().st_size != dst.stat().st_size):
            changes.append(name)
    for name in REPLACE_DIRS:
        src = source / name
        if not src.is_dir():
            continue
        for path in _files_of(src):
            relative = path.relative_to(source).as_posix()
            if _kept(relative):
                continue
            dst = target / relative
            if not dst.is_file() or dst.stat().st_size != path.stat().st_size:
                changes.append(relative)
    return changes


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--from", dest="source", required=True, help="新版发布目录")
    parser.add_argument("--to", dest="target", default=str(ROOT), help="要升级的安装目录")
    parser.add_argument("--apply", action="store_true", help="真正执行（默认只列出变化）")
    args = parser.parse_args()

    source = Path(args.source).resolve()
    target = Path(args.target).resolve()
    if not (source / "app.py").is_file():
        print(f"[错误] 源目录不是 Lite 发布包：{source}")
        return 2
    if source == target:
        print("[错误] 源目录和目标目录相同")
        return 2

    changes = plan(source, target)
    print(f"源：{source}\n目标：{target}")
    print(f"需要更新 {len(changes)} 个文件")
    for item in changes[:20]:
        print(f"  {item}")
    if len(changes) > 20:
        print(f"  …… 另有 {len(changes) - 20} 个")

    if not args.apply:
        print("\n这是预演。加 --apply 执行。")
        return 0

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = target / "runtime" / f"upgrade-backup-{stamp}"
    backup.mkdir(parents=True, exist_ok=True)
    for relative in ("lite/runtime-config.json", "lite/task-options.json", "lite/task-inputs.json"):
        src = target / relative
        if src.is_file():
            _copy_file(src, backup / relative)
    print(f"配置已备份到 {backup}")

    for name in REPLACE_FILES:
        src = source / name
        if src.is_file():
            _copy_file(src, target / name)
    for name in REPLACE_DIRS:
        src = source / name
        if not src.is_dir():
            continue
        if name == "lite":
            # Copy python modules and UI, keep the user's json files.
            for path in _files_of(src):
                relative = path.relative_to(source).as_posix()
                if relative in KEEP:
                    continue
                if path.suffix in {".json"} and relative.startswith("lite/"):
                    continue
                _copy_file(path, target / relative)
        else:
            _copy_tree(src, target / name, name)

    print("升级完成。建议先运行：runtime_env\\python\\python.exe app.py --selftest")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
