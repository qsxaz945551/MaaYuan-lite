"""Read-only MaaFramework integration spike.

This script only connects to the emulator, loads the resource bundle and
captures one screenshot. It does not click, swipe, launch apps or run tasks.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--maa-root", type=Path, required=True)
    parser.add_argument("--adb", type=Path, required=True)
    parser.add_argument("--serial", default="emulator-5554")
    parser.add_argument("--resource", type=Path, default=ROOT / "assets" / "resource" / "base")
    parser.add_argument("--output", type=Path, default=ROOT / "build" / "spike" / "screenshot.png")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    native = args.maa_root / "runtimes" / "win-x64" / "native"
    agent_candidates = [
        args.maa_root / "libs" / "MaaAgentBinary",
        args.maa_root / "MaaAgentBinary",
        args.maa_root / "python" / "Lib" / "site-packages" / "MaaAgentBinary",
    ]
    agent_binary = next((path for path in agent_candidates if path.is_dir()), None)
    if not native.is_dir():
        raise SystemExit(f"MaaFramework native directory not found: {native}")
    if agent_binary is None:
        raise SystemExit(
            "MaaAgentBinary directory not found in: "
            + ", ".join(str(path) for path in agent_candidates)
        )
    if not args.resource.is_dir():
        raise SystemExit(f"Resource directory not found: {args.resource}")

    os.environ["MAAFW_BINARY_PATH"] = str(native)

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
    print("Connecting to emulator...", flush=True)
    connection = controller.post_connection().wait()
    print(f"Connection: {connection.status}", flush=True)
    if not connection.succeeded:
        return 2

    resource = Resource()
    print(f"Loading resource: {args.resource}", flush=True)
    loading = resource.post_bundle(args.resource).wait()
    print(f"Resource: {loading.status}", flush=True)
    if not loading.succeeded:
        return 3

    tasker = Tasker()
    if not tasker.bind(resource, controller):
        print("Failed to bind resource and controller.", file=sys.stderr)
        return 4
    print(f"Tasker initialized: {tasker.inited}", flush=True)

    print("Capturing screenshot (read-only)...", flush=True)
    capture = controller.post_screencap().wait()
    print(f"Screenshot: {capture.status}", flush=True)
    if not capture.succeeded:
        return 5

    image = capture.get()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    try:
        from PIL import Image
    except ImportError as error:
        print(f"Screenshot captured but PIL is unavailable: {error}", file=sys.stderr)
        return 6

    Image.fromarray(image).save(args.output)
    print(f"Saved screenshot: {args.output}", flush=True)
    print(f"Resolution: {image.shape[1]}x{image.shape[0]}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
