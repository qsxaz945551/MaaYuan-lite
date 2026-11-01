"""Validate the lightweight runner <-> Python Agent channel.

No game actions are performed. The script connects, starts the Agent,
binds custom actions and exits.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--maa-root", type=Path, required=True)
    parser.add_argument("--adb", type=Path, required=True)
    parser.add_argument("--serial", default="emulator-5554")
    parser.add_argument("--resource", type=Path, default=ROOT / "assets" / "resource" / "base")
    args = parser.parse_args()

    native = args.maa_root / "runtimes" / "win-x64" / "native"
    agent_candidates = [
        args.maa_root / "libs" / "MaaAgentBinary",
        args.maa_root / "python" / "Lib" / "site-packages" / "MaaAgentBinary",
    ]
    agent_binary = next((path for path in agent_candidates if path.is_dir()), None)
    if agent_binary is None:
        raise SystemExit("MaaAgentBinary not found")

    os.environ["MAAFW_BINARY_PATH"] = str(native)
    from maa.agent_client import AgentClient
    from maa.controller import AdbController
    from maa.resource import Resource
    from maa.tasker import Tasker

    controller = AdbController(
        adb_path=args.adb,
        address=args.serial,
        screencap_methods=4,
        input_methods=1,
        config={},
        agent_path=agent_binary,
    )
    print("connect controller", flush=True)
    if not controller.post_connection().wait().succeeded:
        print("controller connection failed", file=sys.stderr)
        return 2

    resource = Resource()
    print("load resource", flush=True)
    if not resource.post_bundle(args.resource).wait().succeeded:
        print("resource load failed", file=sys.stderr)
        return 3

    tasker = Tasker()
    if not tasker.bind(resource, controller):
        print("tasker bind failed", file=sys.stderr)
        return 4

    identifier = f"lite-spike-{os.getpid()}"
    client = AgentClient(identifier)
    client.set_timeout(120000)
    if not client.bind(resource):
        print("agent bind resource failed", file=sys.stderr)
        return 5
    if not client.register_sink(resource, controller, tasker):
        print("agent register sink failed", file=sys.stderr)
        return 6

    stdout_path = ROOT / "build" / "spike" / "agent.stdout.log"
    stderr_path = ROOT / "build" / "spike" / "agent.stderr.log"
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    stdout_file = stdout_path.open("w", encoding="utf-8")
    stderr_file = stderr_path.open("w", encoding="utf-8")

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    process = subprocess.Popen(
        [sys.executable, "-u", str(ROOT / "agent" / "main.py"), identifier],
        cwd=ROOT,
        env=env,
        stdout=stdout_file,
        stderr=stderr_file,
    )
    print(f"agent pid={process.pid}", flush=True)

    connected = False
    try:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if process.poll() is not None:
                print(f"agent exited early: {process.returncode}", file=sys.stderr)
                break
            if client.connect():
                connected = True
                break
            time.sleep(0.3)

        if not connected:
            print("agent connection failed", file=sys.stderr)
            return 5

        print(f"agent connected={client.connected} alive={client.alive}", flush=True)
        print(f"agent alive after bind={client.alive}", flush=True)
        return 0
    finally:
        try:
            client.disconnect()
        except Exception:
            pass
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
        stdout_file.close()
        stderr_file.close()
        print(f"agent logs: {stderr_path}", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
