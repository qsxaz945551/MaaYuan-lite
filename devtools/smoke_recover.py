"""Smoke-test the unknown-screen recovery primitives on the real device.

Usage:
    python devtools/smoke_recover.py

It connects, checks the main-screen probe, sends a back key, and checks again.
Nothing is clicked in the game; the back key only affects the current screen.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lite.adb_finder import find_adb  # noqa: E402
from lite.session import LiteSession  # noqa: E402


def resolve(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else (ROOT / path).resolve()


def main() -> int:
    config = json.loads((ROOT / "lite" / "runtime-config.json").read_text(encoding="utf-8-sig"))
    adb, adb_source = find_adb(str(config.get("adb_path") or ""), ROOT)
    if adb is None:
        print("adb not found")
        return 1
    print(f"adb: {adb}（{adb_source}）")
    session = LiteSession(
        project_root=ROOT,
        maa_root=resolve(config["runtime_root"]),
        adb_path=adb,
        serial=str(config.get("adb_serial", "emulator-5554")),
        resource_path=resolve(config["resource_root"]),
        agent_root=resolve(config["agent_root"]),
    )
    session.start()
    try:
        print("main screen before:", session.is_main_screen())
        print("press back       :", session.press_back())
        print("main screen after :", session.is_main_screen())
        print("tap              :", session.tap(690, 40))
    finally:
        session.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
