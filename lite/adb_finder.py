"""Locate adb.exe without hard-coding one install path.

Order: configured value -> LDPLAYER_PATH -> registry InstallDir -> common
install folders -> bundled platform-tools. The bundled copy is optional; this
project deliberately does not ship one, so the common folders matter most.
"""

from __future__ import annotations

import os
from pathlib import Path

try:
    import winreg
except ImportError:  # non-Windows, keeps the module importable in tests
    winreg = None  # type: ignore[assignment]

REGISTRY_KEYS = [
    (r"SOFTWARE\leidian\ldplayer9", "InstallDir"),
    (r"SOFTWARE\leidian\ldplayer14", "InstallDir"),
    (r"SOFTWARE\WOW6432Node\leidian\ldplayer9", "InstallDir"),
    (r"SOFTWARE\WOW6432Node\leidian\ldplayer14", "InstallDir"),
    (r"SOFTWARE\XuanZhi\LDPlayer", "InstallDir"),
    (r"SOFTWARE\WOW6432Node\XuanZhi\LDPlayer", "InstallDir"),
]

COMMON_GLOBS = [
    "C:/LDPlayer*/adb.exe",
    "D:/LDPlayer*/adb.exe",
    "E:/LDPlayer*/adb.exe",
    "C:/Program Files/LDPlayer*/adb.exe",
    "D:/Program Files/LDPlayer*/adb.exe",
    "C:/Program Files (x86)/LDPlayer*/adb.exe",
    "D:/Apps Game/LDPlayer*/adb.exe",
    "C:/Apps Game/LDPlayer*/adb.exe",
]


def _from_registry() -> Path | None:
    if winreg is None:
        return None
    for subkey, value_name in REGISTRY_KEYS:
        for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            try:
                with winreg.OpenKey(root, subkey) as key:
                    value, _ = winreg.QueryValueEx(key, value_name)
            except OSError:
                continue
            candidate = Path(str(value)) / "adb.exe"
            if candidate.is_file():
                return candidate
    return None


def _from_common_folders() -> Path | None:
    for pattern in COMMON_GLOBS:
        base = Path(pattern.split("*")[0])
        suffix = pattern.split("*", 1)[1] if "*" in pattern else ""
        parent = base.parent
        if not parent.is_dir():
            continue
        prefix = base.name
        for entry in parent.iterdir():
            if not entry.is_dir() or not entry.name.lower().startswith(prefix.lower()):
                continue
            candidate = entry / suffix.lstrip("/")
            if candidate.is_file():
                return candidate
    return None


def find_adb(configured: str, project_root: Path) -> tuple[Path | None, str]:
    """Return (path, where it came from). ``path`` is None when nothing works."""
    text = (configured or "").strip()
    if text:
        path = Path(text)
        if not path.is_absolute():
            path = (project_root / path).resolve()
        if path.is_file():
            return path, "配置"

    env = os.environ.get("LDPLAYER_PATH", "").strip()
    if env:
        candidate = Path(env) / "adb.exe"
        if candidate.is_file():
            return candidate, "环境变量 LDPLAYER_PATH"

    candidate = _from_registry()
    if candidate is not None:
        return candidate, "注册表"

    candidate = _from_common_folders()
    if candidate is not None:
        return candidate, "常见安装目录"

    bundled = project_root / "runtime_env" / "platform-tools" / "adb.exe"
    if bundled.is_file():
        return bundled, "内置 platform-tools"

    return None, "未找到"
