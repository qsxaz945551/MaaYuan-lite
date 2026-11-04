"""Q2: restart the emulator in the middle of a task.

What the acceptance criterion actually asks for is "recovers by itself or stops
with a clear reason" — both are acceptable, silently hanging is not. So this
script prints the three things that matter and does not pretend to decide:

1. does the service still answer HTTP after the emulator disappears,
2. does the task end with a readable reason (instead of staying ``running``),
3. can a second task still be started (the 409-after-first-run bug class).

The emulator restart is a real change to the user's machine, so the caller must
have agreed to it. Nothing here changes resolution/DPI/config — it only quits
and launches the existing instance.

Usage:
    python devtools/smoke_emulator_restart.py --task "🏯 据点日常" --midway 25
    python devtools/smoke_emulator_restart.py --task "🏯 据点日常" --verify-recovery
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from stability_run import (  # noqa: E402
    Client,
    spawn_service,
    start_run,
    stop_service,
)

KEYWORDS = (
    "任务失败",
    "任务完成",
    "运行异常",
    "Agent",
    "连接",
    "超时",
    "中止",
    "关闭步骤",
    "设备",
)


def config() -> dict:
    path = ROOT / "lite" / "runtime-config.json"
    return json.loads(path.read_text(encoding="utf-8"))


def adb_devices(adb: Path, serial: str) -> bool:
    try:
        result = subprocess.run(
            [str(adb), "devices"], capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    for line in result.stdout.splitlines():
        if line.startswith(serial) and "device" in line:
            return True
    return False


def restart_emulator(emulator_dir: Path, adb: Path, serial: str, wait: float) -> bool:
    """Quit and relaunch the instance, then wait for adb to report it again."""
    console = emulator_dir / "ldconsole.exe"
    print("  → ldconsole quit")
    subprocess.run([str(console), "quit", "--index", "0"], cwd=str(emulator_dir),
                   capture_output=True, timeout=90)
    time.sleep(8)
    print("  → ldconsole launch")
    subprocess.run([str(console), "launch", "--index", "0"], cwd=str(emulator_dir),
                   capture_output=True, timeout=90)

    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        if adb_devices(adb, serial):
            print(f"  → adb 已恢复（等待 {int(wait - (deadline - time.monotonic()))} 秒）")
            return True
        time.sleep(5)
    return False


def wait_running(client: Client, seconds: float) -> str:
    """Wait until the task has been running for roughly ``seconds``."""
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        state = client.get("/api/state?since=0")
        if state.get("status") in ("starting", "running"):
            break
        time.sleep(1)
    time.sleep(seconds)
    return client.get("/api/state?since=0").get("status", "?")


def main() -> int:
    parser = argparse.ArgumentParser(description="Q2 模拟器重启场景")
    parser.add_argument("--task", default="🏯 据点日常")
    parser.add_argument("--midway", type=float, default=25.0, help="跑多久后重启模拟器")
    parser.add_argument("--settle", type=float, default=180.0, help="重启后观察多久")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--verify-recovery", action="store_true",
                        help="模拟器恢复后再跑一个任务，确认服务没卡死")
    parser.add_argument("--recovery-task", default="🚀 启动游戏",
                        help="第二轮用什么任务验证（默认会自己拉起游戏）")
    args = parser.parse_args()

    cfg = config()
    serial = cfg.get("adb_serial", "emulator-5554")
    # adb_path 通常是空字符串（应用运行时自动探测），这里走同一套探测逻辑
    sys.path.insert(0, str(ROOT))
    from lite.adb_finder import find_adb

    found, reason = find_adb(str(cfg.get("adb_path") or ""), ROOT)
    if found is None:
        print(f"找不到 adb：{reason}")
        return 1
    adb = found
    emulator_dir = adb.parent

    print(f"adb: {adb}")
    if not adb_devices(adb, serial):
        print("模拟器当前不在线，先启动再跑本脚本")
        return 1

    service = spawn_service(args.port)
    client = Client(args.port)
    code = 0
    try:
        print(f"\n[1] 启动任务：{args.task}")
        try:
            client.post("/api/run-task", {"names": [args.task]})
        except urllib.error.HTTPError as error:
            print(f"启动失败：{error}")
            return 1

        status = wait_running(client, args.midway)
        print(f"    运行 {int(args.midway)} 秒后状态：{status}")

        print("\n[2] 重启模拟器")
        started = time.monotonic()
        back = restart_emulator(emulator_dir, adb, serial, wait=180)
        took = time.monotonic() - started
        if not back:
            print(f"    模拟器 {int(took)} 秒内没回来，后面的判断会失真")

        print(f"\n[3] 观察 {int(args.settle)} 秒")
        deadline = time.monotonic() + args.settle
        seen = 0
        final: dict = {}
        alive_checks = 0
        while time.monotonic() < deadline:
            try:
                state = client.get("/api/state?since=0")
                alive_checks += 1
            except OSError as error:
                print(f"    ! 服务无响应：{error}")
                code = 1
                break
            final = state
            logs = state.get("logs", [])
            for line in logs[seen:]:
                if any(word in line["message"] for word in KEYWORDS):
                    print(f"    {line['time']} [{line['level']}] {line['message'][:78]}")
            seen = len(logs)
            if state.get("status") not in ("starting", "running"):
                break
            time.sleep(3)

        print("\n[4] 结论")
        status = final.get("status", "?")
        summary = final.get("summary") or {}
        print(f"    HTTP 存活检查：{alive_checks} 次全部有响应" if code == 0 else "    服务中途失联")
        print(f"    任务最终状态：{status} / {summary}")
        if status in ("starting", "running"):
            print("    ⚠ 任务没有结束——界面会一直转圈")
            code = 1
        elif status == "completed" and not summary.get("failed"):
            print("    自愈：任务在模拟器恢复后跑完了")
        else:
            print("    明确停止：给出的是可读状态而非挂死")

        if args.verify_recovery:
            print("\n[5] 恢复后再跑一个短任务")
            try:
                # 用带重试的启动：上一轮的收尾可能还没走完，裸 POST 会误报 409
                start_run(client, args.recovery_task)
                deadline = time.monotonic() + 240
                while time.monotonic() < deadline:
                    state = client.get("/api/state?since=0")
                    if state.get("status") not in ("starting", "running"):
                        break
                    time.sleep(3)
                print(f"    第二轮状态：{state.get('status')} / {state.get('summary')}")
                if state.get("status") in ("starting", "running"):
                    print("    ⚠ 第二轮启动不了或卡住了")
                    code = 1
            except urllib.error.HTTPError as error:
                print(f"    ⚠ 第二轮被拒绝：{error}（疑似 409 残留）")
                code = 1
        crash = ROOT / "runtime" / "crash.log"
        if crash.is_file() and crash.stat().st_size:
            print("\n[6] runtime/crash.log 有新内容")
            print("\n".join(crash.read_text(encoding="utf-8").splitlines()[-25:]))
        else:
            print("\n[6] runtime/crash.log 为空：服务不是原生崩溃退出的")
    finally:
        stop_service(service)
    return code


if __name__ == "__main__":
    sys.exit(main())
