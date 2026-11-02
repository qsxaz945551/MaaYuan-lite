"""Swap in a staged resource folder and roll back if it fails.

The downloader writes a complete tree to ``assets.next/``; nothing replaces the
live resources until the gate passes. All moves are renames on the same volume,
so the switch takes milliseconds and a failure leaves the old tree intact.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from .update_gate import validate

STAGE = "assets.next"
BACKUP = "assets.prev"


def stage_root(project_root: Path) -> Path:
    return project_root / STAGE


def backup_root(project_root: Path) -> Path:
    return project_root / BACKUP


def has_staged(project_root: Path) -> bool:
    return (stage_root(project_root) / "resource" / "base").is_dir()


def apply_staged(project_root: Path, interface_source: str = "") -> dict[str, Any]:
    """Replace assets/resource/base with the staged copy.

    ``interface_source`` comes from runtime-config: when it is empty the bundle
    owns ``assets/interface.json`` and it is swapped too; a dev checkout that
    points at vendor/ is left alone.
    """
    staged = stage_root(project_root)
    staged_resource = staged / "resource" / "base"
    if not staged_resource.is_dir():
        return {"ok": False, "error": f"没有待生效资源：{staged_resource}"}

    problems = validate(project_root, resource_root=staged_resource)
    if problems:
        return {"ok": False, "error": "兼容性门禁未通过", "problems": problems}

    target = project_root / "assets" / "resource" / "base"
    backup = backup_root(project_root)
    interface_staged = staged / "interface.json"
    interface_target = project_root / "assets" / "interface.json"
    swap_interface = not str(interface_source or "").strip() and interface_staged.is_file()

    if backup.exists():
        shutil.rmtree(backup)
    (backup / "resource").mkdir(parents=True)

    try:
        if target.exists():
            target.rename(backup / "resource" / "base")
        staged_resource.rename(target)
        if swap_interface:
            if interface_target.is_file():
                shutil.copy2(interface_target, backup / "interface.json")
            shutil.copy2(interface_staged, interface_target)
    except OSError as error:
        _restore(project_root)
        return {"ok": False, "error": f"切换失败，已回滚：{error}"}

    shutil.rmtree(staged, ignore_errors=True)
    return {
        "ok": True,
        "backup": str(backup),
        "interfaceSwapped": swap_interface,
    }


def rollback(project_root: Path) -> bool:
    """Undo the last apply_staged call."""
    return _restore(project_root)


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
        saved_interface = backup / "interface.json"
        if saved_interface.is_file():
            shutil.copy2(saved_interface, project_root / "assets" / "interface.json")
        shutil.rmtree(backup, ignore_errors=True)
        return True
    except OSError:
        return False
