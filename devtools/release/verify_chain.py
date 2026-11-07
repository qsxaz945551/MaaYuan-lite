"""Run one full daily chain against the packaged release and record the result.

    python devtools/release/verify_chain.py

Runs the release currently named in dist/active.txt, writes build/chain-verify.json
with per-task status/duration, then shuts the service down through /api/exit.
Takes 8-13 minutes and clicks the real game window.
"""

from __future__ import annotations

import json
import subprocess
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PKG = ROOT / "dist" / (ROOT / "dist" / "active.txt").read_text(encoding="utf-8").strip()
PY = PKG / "runtime_env" / "python" / "python.exe"
OUT = ROOT / "build" / "chain-verify.json"


def get(port: int, path: str, timeout: float = 30.0):
    return json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=timeout))


def post(port: int, path: str, payload: dict | None = None, timeout: float = 60.0):
    body = json.dumps(payload or {}).encode()
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=body,
        headers={"Content-Type": "application/json", "Content-Length": str(len(body))},
    )
    return json.load(urllib.request.urlopen(request, timeout=timeout))


def wait_port(seconds: float = 60.0) -> int:
    port_file = PKG / "runtime" / "port.txt"
    deadline = time.time() + seconds
    while time.time() < deadline:
        time.sleep(0.5)
        if port_file.is_file():
            text = port_file.read_text().strip()
            if text.isdigit():
                return int(text)
    raise SystemExit("服务没有写出端口")


def main() -> int:
    started = time.time()
    proc = subprocess.Popen([str(PY), "app.py"], cwd=PKG)
    port = 0
    try:
        port = wait_port()
        print(f"服务就绪 port={port}", flush=True)

        post(port, "/api/start", {"training": "修为", "dungeon": False, "resume": False})
        print("已开始日常", flush=True)

        state: dict = {}
        last_report = 0.0
        deadline = time.time() + 1500
        while time.time() < deadline:
            time.sleep(3)
            try:
                state = get(port, "/api/state?since=latest")
            except Exception as error:  # noqa: BLE001
                print(f"轮询失败（继续）：{error}", flush=True)
                continue
            status = state.get("status")
            if status not in ("starting", "running"):
                break
            now = time.time()
            if now - last_report > 30:
                last_report = now
                done = [
                    (t.get("name"), t.get("status"))
                    for t in state.get("tasks", [])
                    if t.get("status") in ("succeeded", "failed", "timed_out", "skipped", "skipped_no_resource")
                ]
                print(
                    f"[{int(now - started):4d}s] {status} 当前={state.get('currentTask')!r} "
                    f"已完成 {len(done)}/{len(state.get('tasks', []))}",
                    flush=True,
                )

        tasks = state.get("tasks", [])
        summary = state.get("summary", {})
        report = {
            "version": PKG.name,
            "status": state.get("status"),
            "elapsed": round(time.time() - started, 1),
            "summary": summary,
            "tasks": [
                {
                    "name": t.get("name"),
                    "status": t.get("status"),
                    "duration": t.get("duration"),
                }
                for t in tasks
            ],
        }
        OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(
            f"结束 status={report['status']} 用时={report['elapsed']}s "
            f"成功={summary.get('succeeded')} 失败={summary.get('failed')} "
            f"未领取={summary.get('skipped', 0)}",
            flush=True,
        )
        for task in report["tasks"]:
            print(f"  {task['status']:<10} {task['duration'] or 0:>7}s  {task['name']}", flush=True)
        return 0 if summary.get("failed", 1) == 0 else 1
    finally:
        if port:
            try:
                post(port, "/api/exit", timeout=10)
            except Exception as error:  # noqa: BLE001
                print(f"exit 请求失败：{error}", flush=True)
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            proc.terminate()


if __name__ == "__main__":
    raise SystemExit(main())
