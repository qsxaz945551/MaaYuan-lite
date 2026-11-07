"""Runtime automation settings shared by the console and the runner."""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

from .constants import DEFAULT_TRAINING


ROOT = Path(__file__).resolve().parents[1]
# 部署配置：路径、端口、串号。装机时定下，程序不写它。
CONFIG_FILE = ROOT / "lite" / "runtime-config.json"
# 用户偏好：启动/结束动作、上次选的历练档位。改一次就写一次，所以放 runtime/。
SETTINGS_FILE = ROOT / "runtime" / "settings.json"

# Serialises read-modify-write: the WPF shell can fire two saves (startup and
# shutdown dropdowns) within the same second and one used to overwrite the other.
_WRITE_LOCK = threading.Lock()

STARTUP_ACTIONS = ("none", "minimize_only", "auto_run", "auto_run_minimized")
SHUTDOWN_ACTIONS = ("none", "close_maa", "close_both")

DEFAULTS: dict[str, Any] = {
    "startup_action": "none",
    "shutdown_action": "none",
    "last_training": DEFAULT_TRAINING,
    "last_dungeon": False,
    "auto_update_resources": True,
}

# The wire format is camelCase (the WPF client); storage stays snake_case so the
# JSON file and Python call sites keep reading naturally.
CAMEL: dict[str, str] = {
    "startup_action": "startupAction",
    "shutdown_action": "shutdownAction",
    "last_training": "lastTraining",
    "last_dungeon": "lastDungeon",
    "auto_update_resources": "autoUpdateResources",
}
SNAKE: dict[str, str] = {value: key for key, value in CAMEL.items()}


def to_wire(data: dict[str, Any]) -> dict[str, Any]:
    """Response shape: camelCase only.

    The snake_case duplicates existed solely for the retired HTML console; the
    WPF client reads camelCase, so keeping both spellings only invited drift.
    """
    payload = dict(data)
    for snake in CAMEL:
        payload.pop(snake, None)
    for snake, camel in CAMEL.items():
        if snake in data:
            payload[camel] = data[snake]
    return payload


def from_wire(patch: dict[str, Any]) -> dict[str, Any]:
    """Accept either spelling in a request body."""
    normalized: dict[str, Any] = {}
    for key, value in patch.items():
        normalized[SNAKE.get(key, key)] = value
    return normalized


def load_config() -> dict[str, Any]:
    with CONFIG_FILE.open("r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def _read_object(path: Path) -> dict[str, Any] | None:
    """读一个 JSON 对象；不存在或读坏都返回 None，让调用方走兜底。"""
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _stored() -> dict[str, Any]:
    """用户偏好：优先 runtime/settings.json。

    0.3.2 及更早版本把 ``automation`` 写在 ``lite/runtime-config.json`` 里，与装机
    路径混在一起，改一次设置就让工作区变脏。旧位置仍然可读，第一次保存时才搬家。
    """
    data = _read_object(SETTINGS_FILE)
    if data is not None:
        return data
    legacy = (_read_object(CONFIG_FILE) or {}).get("automation")
    return legacy if isinstance(legacy, dict) else {}


def _migrate(data: dict[str, Any]) -> dict[str, Any]:
    """Map the old boolean flags onto the two action enums."""
    if "startup_action" in data or "shutdown_action" in data:
        return data
    migrated = dict(data)
    if data.get("auto_start") and data.get("start_minimized"):
        migrated["startup_action"] = "auto_run_minimized"
    elif data.get("auto_start"):
        migrated["startup_action"] = "auto_run"
    elif data.get("start_minimized"):
        migrated["startup_action"] = "minimize_only"
    else:
        migrated["startup_action"] = "none"
    migrated["shutdown_action"] = (
        "close_both" if data.get("close_emulator") else "none"
    )
    for legacy in ("auto_start", "start_minimized", "close_emulator"):
        migrated.pop(legacy, None)
    return migrated


def load_settings() -> dict[str, Any]:
    data = _migrate(dict(_stored()))
    merged = dict(DEFAULTS)
    merged.update({key: data[key] for key in data if key in DEFAULTS})
    if merged["startup_action"] not in STARTUP_ACTIONS:
        merged["startup_action"] = "none"
    if merged["shutdown_action"] not in SHUTDOWN_ACTIONS:
        merged["shutdown_action"] = "none"
    return merged


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    """Write through a temp file so a crash never leaves a half-written config.

    ``os.replace`` is atomic on the same volume; a reader either sees the old
    file or the new one, never a truncated JSON.
    """
    temp = path.with_suffix(path.suffix + ".tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    temp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    try:
        os.replace(temp, path)
    except PermissionError:
        # 目标被占用（杀软扫描、文件夹重定向）时，覆盖写仍可成功。
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        temp.unlink(missing_ok=True)


def save_settings(patch: dict[str, Any]) -> dict[str, Any]:
    with _WRITE_LOCK:
        current = load_settings()
        for key, value in patch.items():
            if key == "startup_action" and value in STARTUP_ACTIONS:
                current[key] = value
            elif key == "shutdown_action" and value in SHUTDOWN_ACTIONS:
                current[key] = value
            elif key == "last_training":
                current[key] = str(value)
            elif key == "last_dungeon":
                current[key] = bool(value)
            elif key == "auto_update_resources":
                current[key] = bool(value)
        _write_json_atomic(SETTINGS_FILE, current)
        return current
