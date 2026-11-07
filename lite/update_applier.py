"""Swap in a staged resource folder and roll back if it fails.

The downloader writes a complete tree to ``assets.next/``; nothing replaces the
live resources until the gate passes. All moves are renames on the same volume,
so the switch takes milliseconds and a failure leaves the old tree intact.

A staged tree looks like::

    assets.next/
        resource/base/...     pipeline, images, models
        interface.json        upstream task definitions
        agent/...             Python agent scripts
        .source.json          which commit this came from
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from .source_manifest import MANIFEST_NAME
from .update_gate import validate

STAGE = "assets.next"
STAGE_PART = "assets.next.part"
BACKUP = "assets.prev"

# 上游资源树里没有、由 Lite 自己放进 assets/resource/base 的文件。
# 切换是整目录 rename，这些文件会被静默带走——活动页判页用的模板图就踩过这个坑。
# 与 devtools/release/upgrade.py 的 KEEP 保持同一份清单。
RESOURCE_EXTRAS = ("image/activity_title.png",)


def stage_root(project_root: Path) -> Path:
    return project_root / STAGE


def backup_root(project_root: Path) -> Path:
    return project_root / BACKUP


def has_staged(project_root: Path) -> bool:
    return (stage_root(project_root) / "assets" / "resource" / "base").is_dir()


def cleanup_partial(project_root: Path) -> None:
    """Drop a half-written stage left behind by an interrupted download."""
    shutil.rmtree(project_root / STAGE_PART, ignore_errors=True)


def apply_staged(project_root: Path, interface_source: str = "") -> dict[str, Any]:
    """Replace live resources with the staged copy.

    ``interface_source`` comes from runtime-config: when it is empty the bundle
    owns ``assets/interface.json`` and it is swapped too; a dev checkout that
    points at vendor/ is left alone.
    """
    staged = stage_root(project_root)
    staged_resource = staged / "assets" / "resource" / "base"
    if not staged_resource.is_dir():
        return {"ok": False, "error": f"没有待生效资源：{staged_resource}"}

    problems = validate(project_root, resource_root=staged_resource)
    if problems:
        return {"ok": False, "error": "兼容性门禁未通过", "problems": problems}

    assets = project_root / "assets"
    backup = backup_root(project_root)
    swap_interface = (
        not str(interface_source or "").strip()
        and (staged / "assets" / "interface.json").is_file()
    )
    swap_agent = (staged / "agent" / "main.py").is_file()

    if backup.exists():
        shutil.rmtree(backup, ignore_errors=True)
    (backup / "resource").mkdir(parents=True)

    moved: list[tuple[Path, Path]] = []
    try:
        target = assets / "resource" / "base"
        if target.exists():
            saved = backup / "resource" / "base"
            target.rename(saved)
            moved.append((saved, target))
        staged_resource.rename(target)

        if swap_interface:
            saved_interface = backup / "interface.json"
            if (assets / "interface.json").is_file():
                shutil.copy2(assets / "interface.json", saved_interface)
            shutil.copy2(staged / "assets" / "interface.json", assets / "interface.json")

        if swap_agent:
            live_agent = project_root / "agent"
            if live_agent.exists():
                saved_agent = backup / "agent"
                live_agent.rename(saved_agent)
                moved.append((saved_agent, live_agent))
            (staged / "agent").rename(live_agent)

        manifest = staged / "assets" / MANIFEST_NAME
        if manifest.is_file():
            live_manifest = assets / MANIFEST_NAME
            if live_manifest.is_file():
                shutil.copy2(live_manifest, backup / MANIFEST_NAME)
            shutil.copy2(manifest, live_manifest)

        carried = _carry_resource_extras(
            backup / "resource" / "base", assets / "resource" / "base"
        )
    except OSError as error:
        _undo(moved)
        _restore_extras(project_root, backup)
        return {"ok": False, "error": f"切换失败，已回滚：{error}"}

    shutil.rmtree(staged, ignore_errors=True)
    return {
        "ok": True,
        "backup": str(backup),
        "interfaceSwapped": swap_interface,
        "agentSwapped": swap_agent,
        "restoredExtras": carried,
    }


def _carry_resource_extras(previous: Path, current: Path) -> list[str]:
    """Bring Lite's own additions over to the freshly swapped tree.

    The staged tree comes from upstream and cannot contain them, so without this
    an auto-update silently removes e.g. the activity-page template and the
    pipeline fix that references it starts missing again.
    """
    carried: list[str] = []
    for relative in RESOURCE_EXTRAS:
        source = previous / relative
        if not source.is_file():
            continue
        target = current / relative
        if target.is_file():
            continue
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            carried.append(relative)
        except OSError:
            pass
    return carried


def rollback(project_root: Path) -> bool:
    """Undo the last apply_staged call."""
    return _restore(project_root)


def _undo(moved: list[tuple[Path, Path]]) -> None:
    for saved, live in reversed(moved):
        try:
            if live.exists():
                shutil.rmtree(live, ignore_errors=True)
            if saved.exists():
                saved.rename(live)
        except OSError:
            pass


def _restore_extras(project_root: Path, backup: Path) -> None:
    assets = project_root / "assets"
    saved_interface = backup / "interface.json"
    if saved_interface.is_file():
        try:
            shutil.copy2(saved_interface, assets / "interface.json")
        except OSError:
            pass
    saved_manifest = backup / MANIFEST_NAME
    if saved_manifest.is_file():
        try:
            shutil.copy2(saved_manifest, assets / MANIFEST_NAME)
        except OSError:
            pass
    saved_agent = backup / "agent"
    if saved_agent.is_dir():
        live_agent = project_root / "agent"
        try:
            shutil.rmtree(live_agent, ignore_errors=True)
            saved_agent.rename(live_agent)
        except OSError:
            pass


def _restore(project_root: Path) -> bool:
    backup = backup_root(project_root)
    saved_resource = backup / "resource" / "base"
    target = project_root / "assets" / "resource" / "base"
    if not saved_resource.is_dir():
        return False

    try:
        if target.exists():
            shutil.rmtree(target)
        saved_resource.rename(target)
        _restore_extras(project_root, backup)
        shutil.rmtree(backup, ignore_errors=True)
        return True
    except OSError:
        return False
