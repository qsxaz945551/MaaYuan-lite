"""Switch between built releases without rebuilding or copying files.

Q3 asks for "keep the previous full directory, switch back within a minute".
That rules out both extremes: re-running build_release (minutes) and shipping
two launchers the user has to keep straight. Instead every release keeps its
own directory and ``dist/active.txt`` names the one to start.

The switch itself is a single atomic file write, so the wall clock cost is
whatever the launcher takes to boot — normally ten to twenty seconds.

Usage:
    python devtools/release/release_switch.py list
    python devtools/release/release_switch.py switch previous
    python devtools/release/release_switch.py switch 0.2.0
    python devtools/release/release_switch.py prune --keep 2
"""

from __future__ import annotations

import argparse
import os
import shutil
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
POINTER = "active.txt"
PREFIX = "MaaYuan-Lite-"


def versions(dist: Path) -> list[Path]:
    """Release directories, newest first.

    Sorting by name as text puts ``0.2.10`` *before* ``0.2.9``, which made
    ``prune --keep 2`` try to delete the current release. Compare the numeric
    parts instead; the raw name is only a tiebreaker for odd directory names.
    """
    if not dist.is_dir():
        return []
    found = [
        path
        for path in dist.iterdir()
        if path.is_dir() and path.name.startswith(PREFIX)
    ]
    return sorted(found, key=_version_key, reverse=True)


def version_of(path: Path) -> str:
    return path.name[len(PREFIX) :]


def _version_key(path: Path) -> tuple[tuple[int, ...], str]:
    numbers: list[int] = []
    for chunk in version_of(path).split("."):
        digits = "".join(character for character in chunk if character.isdigit())
        numbers.append(int(digits) if digits else 0)
    return tuple(numbers), path.name


def read_active(dist: Path) -> str | None:
    pointer = dist / POINTER
    if not pointer.is_file():
        return None
    value = pointer.read_text(encoding="utf-8").strip()
    return value or None


def write_active(dist: Path, name: str) -> None:
    """Atomic write: a half-written pointer would leave no launchable version.

    ``os.replace`` can fail with WinError 5 when something blocks rename/delete
    but still allows writing (antivirus, or a sandboxed shell: on this machine
    only in-place writes went through). Fall back to rewriting the pointer in
    place — it is one short line, so the atomic swap is a nicety rather than a
    correctness requirement.
    """
    dist.mkdir(parents=True, exist_ok=True)
    pointer = dist / POINTER
    temp = pointer.with_suffix(".tmp")
    temp.write_text(name, encoding="utf-8")
    try:
        os.replace(temp, pointer)
    except PermissionError:
        pointer.write_text(name, encoding="utf-8")
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass


def resolve(dist: Path, wanted: str) -> Path:
    """Accept a version, a directory name, ``previous`` or ``latest``."""
    found = versions(dist)
    if not found:
        raise SystemExit(f"没有任何发布版本：{dist}")

    active = read_active(dist)

    if wanted in ("latest", "newest"):
        return found[0]
    if wanted == "previous":
        # Toggle semantics: with an active version, "previous" is the newest
        # release that is *not* active, so running the command twice flips back
        # and forth. With no pointer set there is nothing to move away from, so
        # "previous" honestly means the second-newest build.
        if active is None:
            if len(found) < 2:
                raise SystemExit("只有一个版本，没有可回退的目标")
            return found[1]
        for path in found:
            if path.name != active:
                return path
        raise SystemExit("只有一个版本，没有可回退的目标")
    if wanted in ("active", "current"):
        for path in found:
            if path.name == active:
                return path
        raise SystemExit("active.txt 指向的版本不存在，请先 switch 指定一个")

    for path in found:
        if wanted in (path.name, version_of(path)):
            return path
    raise SystemExit(f"找不到版本 {wanted}；可用：{', '.join(version_of(p) for p in found)}")


def describe(path: Path) -> dict[str, object]:
    size = sum(item.stat().st_size for item in path.rglob("*") if item.is_file())
    return {
        "version": version_of(path),
        "directory": path.name,
        "mb": round(size / 1024 / 1024, 1),
        "built": datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M"),
    }


def cmd_list(dist: Path) -> int:
    found = versions(dist)
    if not found:
        print(f"没有发布版本：{dist}")
        return 1
    active = read_active(dist)
    print(f"发布目录：{dist}")
    for path in found:
        info = describe(path)
        mark = "← 当前" if path.name == active else ""
        print(f"  {info['version']:<10} {info['mb']:>7} MB  {info['built']}  {mark}")
    if active is None:
        print("\n未设置 active.txt，启动脚本会挑版本号最大的一个。")
    return 0


def cmd_switch(dist: Path, wanted: str) -> int:
    target = resolve(dist, wanted)
    before = read_active(dist)
    write_active(dist, target.name)
    print(f"已切换：{before or '(未设置)'} → {target.name}")
    print(f"下次启动 dist/启动 Lite.bat 即运行 {version_of(target)}")
    print("提示：每个版本有各自的 lite/runtime-config.json，界面设置不跨版本同步。")
    return 0


def cmd_prune(dist: Path, keep: int, dry_run: bool) -> int:
    found = versions(dist)
    if keep < 1:
        raise SystemExit("--keep 至少为 1")
    active = read_active(dist)
    doomed = found[keep:]
    if not doomed:
        print(f"共 {len(found)} 个版本，无需清理。")
        return 0
    for path in doomed:
        if path.name == active:
            print(f"跳过当前版本：{path.name}")
            continue
        size = sum(item.stat().st_size for item in path.rglob("*") if item.is_file())
        print(f"{'将删除' if dry_run else '删除'}：{path.name}（{size / 1024 / 1024:.1f} MB）")
        if not dry_run:
            shutil.rmtree(path, ignore_errors=True)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="发布版本切换与清理")
    parser.add_argument("--root", default=str(ROOT / "dist"), help="发布根目录")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list", help="列出版本与当前版本")

    switch = sub.add_parser("switch", help="切换当前版本")
    switch.add_argument("version", help="版本号 / 目录名 / previous / latest")

    prune = sub.add_parser("prune", help="删除多余版本")
    prune.add_argument("--keep", type=int, default=2, help="保留最近几个（默认 2）")
    prune.add_argument("--dry-run", action="store_true", help="只看不删")

    args = parser.parse_args()
    dist = Path(args.root).resolve()

    if args.command == "list":
        return cmd_list(dist)
    if args.command == "switch":
        return cmd_switch(dist, args.version)
    return cmd_prune(dist, args.keep, args.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
