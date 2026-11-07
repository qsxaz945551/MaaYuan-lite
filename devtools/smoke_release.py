"""Smoke-check a packaged release without touching the game state.

    python devtools/smoke_release.py                  # 检查 active.txt 指向的版本
    python devtools/smoke_release.py --pkg MaaYuan-Lite-0.2.3
    python devtools/smoke_release.py --skip-game      # 连模拟器那步也省掉

Verifies the *package*, not the working tree: it boots the bundled
``runtime_env``, reads ``/api/meta`` and ``/api/health``, optionally runs one
``/api/check`` (connect + screenshot, no clicks), then shuts the service down
through ``/api/exit``.

Why it exists: 0.2.2 shipped for two days while every runtime fix stayed in the
working tree, so "启动能开" had never been proven against a built folder.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"


def active_package() -> Path:
    pointer = DIST / "active.txt"
    if not pointer.is_file():
        raise SystemExit("dist/active.txt 不存在，请用 --pkg 指定版本")
    name = pointer.read_text(encoding="utf-8").strip()
    return DIST / name


def get(port: int, path: str, timeout: float = 30.0):
    return json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=timeout))


def post(port: int, path: str, payload: dict | None = None, timeout: float = 120.0):
    body = json.dumps(payload or {}).encode()
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=body,
        headers={"Content-Type": "application/json", "Content-Length": str(len(body))},
    )
    return json.load(urllib.request.urlopen(request, timeout=timeout))


def wait_port(pkg: Path, seconds: float = 40.0) -> int:
    port_file = pkg / "runtime" / "port.txt"
    deadline = time.time() + seconds
    while time.time() < deadline:
        time.sleep(0.3)
        if port_file.is_file():
            text = port_file.read_text().strip()
            if text.isdigit():
                return int(text)
    raise SystemExit("服务没有写出端口")


def main() -> int:
    parser = argparse.ArgumentParser(description="发布包自检")
    parser.add_argument("--pkg", default="", help="包名或绝对路径，默认取 active.txt")
    parser.add_argument("--skip-game", action="store_true", help="跳过 /api/check（不连模拟器）")
    parser.add_argument("--shot", default="", help="把最近截图另存到该路径")
    args = parser.parse_args()

    pkg = Path(args.pkg) if args.pkg else active_package()
    if not pkg.is_absolute():
        pkg = (DIST / pkg) if (DIST / pkg).is_dir() else (ROOT / pkg)
    if not (pkg / "app.py").is_file():
        raise SystemExit(f"不是有效的发布包：{pkg}")

    python = pkg / "runtime_env" / "python" / "python.exe"
    if not python.is_file():
        raise SystemExit(f"缺少运行时：{python}")

    print(f"包：{pkg.name}")
    proc = subprocess.Popen([str(python), "app.py"], cwd=pkg)
    port = 0
    try:
        port = wait_port(pkg)
        meta = get(port, "/api/meta")
        print(f"  端口 {port}  version={meta.get('version')}  api={meta.get('apiVersion')}")

        health = get(port, "/api/health", timeout=60)
        failed = [item.get("name") for item in health.get("checks", []) if item.get("status") == "fail"]
        print(f"  health ok={health.get('ok')}  未通过={failed or '无'}")
        if failed:
            return 1

        if args.skip_game:
            print("  已跳过 /api/check")
            return 0

        post(port, "/api/check")
        deadline = time.time() + 150
        state: dict = {}
        while time.time() < deadline:
            time.sleep(2)
            state = get(port, "/api/state?since=latest")
            if state.get("status") not in ("checking", "starting"):
                break
        print(f"  check status={state.get('status')}  currentTask={state.get('currentTask')!r}")

        if args.shot:
            data = urllib.request.urlopen(f"http://127.0.0.1:{port}/api/screenshot", timeout=20).read()
            Path(args.shot).write_bytes(data)
            print(f"  截图 {len(data)} 字节 -> {args.shot}")
        return 0 if state.get("status") == "idle" else 1
    finally:
        if port:
            try:
                post(port, "/api/exit", timeout=10)
            except Exception as error:  # noqa: BLE001 - shutdown is best effort
                print(f"  exit 请求失败：{error}", file=sys.stderr)
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            proc.terminate()


if __name__ == "__main__":
    raise SystemExit(main())
