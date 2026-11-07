"""Smoke check: a failed UI notice must land in the run log.

Starts the active release's backend, posts a synthetic failure notice through
/api/note and checks that /api/state returns it as a warn line. Use this after
changing the notice/log wiring; the unit suite cannot cover the HTTP handler.

    runtime_env/python/python.exe devtools/smoke_ui_note.py
"""
from __future__ import annotations

import json
import subprocess
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
PKG = DIST / (DIST / "active.txt").read_text(encoding="utf-8").strip()
PY = PKG / "runtime_env" / "python" / "python.exe"
PORT_FILE = PKG / "runtime" / "port.txt"


def main() -> int:
    if not PY.is_file():
        raise SystemExit(f"运行时不存在：{PY}")
    proc = subprocess.Popen(
        [str(PY), "app.py", "--no-browser"],
        cwd=str(PKG),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        port = None
        for _ in range(40):
            if PORT_FILE.is_file():
                try:
                    port = int(PORT_FILE.read_text(encoding="utf-8").strip())
                    break
                except ValueError:
                    pass
            time.sleep(0.3)
        if port is None:
            raise SystemExit("服务没起来")

        base = f"http://127.0.0.1:{port}"
        body = json.dumps({"message": "保存失败：自检用", "level": "warn"}).encode("utf-8")
        request = urllib.request.Request(
            base + "/api/note",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            result = json.load(response)
        with urllib.request.urlopen(base + "/api/state?since=0", timeout=5) as response:
            state = json.load(response)

        hits = [
            line for line in state.get("logs", [])
            if "界面：保存失败：自检用" in line.get("message", "")
        ]
        print(f"包：{PKG.name}  端口 {port}  POST /api/note -> {result}")
        print("日志命中：", hits)
        if not result.get("ok") or not hits or hits[-1]["level"] != "warn":
            raise SystemExit("失败提示没有写进运行日志")
        print("OK")
        return 0
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
