"""Inject one fault into a running MaaYuan Lite session (Q2 故障注入).

Q2 asks whether Lite survives five kinds of trouble: the agent dies mid-task,
adb drops, the network goes away, the screen locks, or the emulator restarts.

This tool only *injects* the fault and then prints what Lite did about it.
Judging stays manual on purpose: "recovered and kept going" and "stopped with a
clear reason" are both passes, and the difference is in the log wording, not in
a single boolean.

Usage (Lite must already be running a task):

    python devtools/smoke/inject_fault.py agent        # kill the agent process
    python devtools/smoke/inject_fault.py adb          # adb disconnect
    python devtools/smoke/inject_fault.py network      # airplane mode on
    python devtools/smoke/inject_fault.py lockscreen   # power key (screen off)
    python devtools/smoke/inject_fault.py emulator     # quit the emulator
    python devtools/smoke/inject_fault.py --list       # show faults and expectations

Every fault prints the command that undoes it.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from lite.adb_finder import find_adb  # noqa: E402
from lite.settings import load_config  # noqa: E402

SAMPLE_SECONDS = 10


# ---------------------------------------------------------------- helpers


def _config() -> dict:
    return load_config()


def _adb() -> tuple[Path, str]:
    config = _config()
    path, source = find_adb(str(config.get("adb_path", "")), ROOT)
    if path is None:
        raise SystemExit(f"找不到 adb（{source}）。先在 lite/runtime-config.json 里指定 adb_path。")
    serial = str(config.get("adb_serial", "emulator-5554"))
    return path, serial


def _adb_run(*args: str) -> str:
    path, serial = _adb()
    result = subprocess.run(
        [str(path), "-s", serial, *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )
    return (result.stdout + result.stderr).strip()


def _port() -> int | None:
    """Read the port the running service wrote; None when it is not running."""
    path = ROOT / "runtime" / "port.txt"
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def _state() -> dict | None:
    port = _port()
    if port is None:
        return None
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/api/state?since=0", timeout=5
        ) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception:  # noqa: BLE001 - service may have died, that is a result too
        return None


def _sample(label: str) -> None:
    print(f"\n--- {SAMPLE_SECONDS} 秒后观察（{label}）---")
    time.sleep(SAMPLE_SECONDS)
    state = _state()
    if state is None:
        print("服务无响应：进程可能已退出，或被故障卡住。")
        return
    print(f"status: {state.get('status')}  当前任务: {state.get('currentTask') or '—'}")
    for line in state.get("logs", [])[-6:]:
        print(f"  {line['time']} [{line['level']}] {line['message'][:88]}")


# ---------------------------------------------------------------- faults


def inject_agent() -> str:
    """Stop the agent process as if it crashed; Lite should restart it."""
    path = ROOT / "runtime" / "agent.json"
    if not path.is_file():
        raise SystemExit("没有 runtime/agent.json：当前没有运行中的 agent。")
    data = json.loads(path.read_text(encoding="utf-8"))
    pid = int(data.get("pid", 0))
    if not pid:
        raise SystemExit("agent.json 里没有 PID。")
    result = subprocess.run(
        ["taskkill", "/F", "/PID", str(pid)],
        capture_output=True,
        text=True,
        encoding="gbk",     # taskkill 在中文系统上输出 GBK
        errors="replace",
    )
    if result.returncode != 0:
        raise SystemExit(f"结束进程失败：{result.stderr or result.stdout}")
    return "agent 已强杀；Lite 应记录「Agent 异常退出」并自动重启"


def inject_adb() -> str:
    """Drop the adb transport; Lite should notice before the next task."""
    _adb_run("disconnect")
    return "adb 已断开；重连：`adb connect emulator-5554`（或重启模拟器）"


def inject_network() -> str:
    """Turn on airplane mode inside the emulator."""
    out = _adb_run("shell", "cmd", "connectivity", "airplane-mode", "enable")
    if "Unknown command" in out or "Error" in out:
        # Older images only have the settings route.
        _adb_run("shell", "settings", "put", "global", "airplane_mode_on", "1")
        _adb_run(
            "shell", "am", "broadcast", "-a",
            "android.intent.action.AIRPLANE_MODE", "--ez", "state", "true",
        )
    return "模拟器已断网；恢复：`adb shell cmd connectivity airplane-mode disable`"


def inject_lockscreen() -> str:
    """Press power so the screen turns off; screenshots should go black."""
    _adb_run("shell", "input", "keyevent", "26")
    return "已发送电源键；唤醒：`adb shell input keyevent 26` 再 `input keyevent 82`"


def inject_emulator() -> str:
    """Quit the emulator instance outright."""
    ldconsole = Path("D:/Apps Game/LDPlayer14/ldconsole.exe")
    if not ldconsole.is_file():
        raise SystemExit(f"找不到 {ldconsole}；请手动关闭模拟器。")
    subprocess.run(
        [str(ldconsole), "quit", "--index", "0"],
        capture_output=True,
        timeout=60,
    )
    return "模拟器已关闭；恢复：启动雷电后等桌面出现再继续"


# AGENTS.md R2：模拟器只能由用户手动启动/重启。这两类故障会改变模拟器状态
# （断网用的是飞行模式，会把模拟器系统卡死），所以要求用户在终端里显式设置
# MAAYUAN_ALLOW_EMULATOR_CONTROL=1 才能执行；AI 会话里不会设置它。
GUARD_ENV = "MAAYUAN_ALLOW_EMULATOR_CONTROL"
EMULATOR_CONTROL_FAULTS = {"emulator", "network"}


def emulator_control_allowed() -> bool:
    return os.environ.get(GUARD_ENV) == "1"


FAULTS = {
    "agent": (inject_agent, "Agent 中途被杀"),
    "adb": (inject_adb, "adb 掉线"),
    "network": (inject_network, "断网"),
    "lockscreen": (inject_lockscreen, "锁屏"),
    "emulator": (inject_emulator, "模拟器重启"),
}

EXPECTATIONS = """\
| 故障 | 期望（任一即为通过） |
|---|---|
| agent     | 日志出现「Agent 异常退出」→「Agent 已重启」，后续任务继续；重启失败则整轮停止并说明 |
| adb       | 下一任务前发现掉线 → 重连 3 次；仍失败则停止整轮并写明原因 |
| network   | 任务失败但不崩溃，日志给出具体错误；网络恢复后可继续未完成 |
| lockscreen| 截图黑屏时明确报错，不把黑屏当成「识别失败」反复重试 |
| emulator  | 连接失败即停止，日志说清「模拟器不可用」，不空转 |"""


# ---------------------------------------------------------------- entry


def main() -> int:
    global SAMPLE_SECONDS
    parser = argparse.ArgumentParser(description="Q2 故障注入：注入一次故障并观察 Lite 的反应")
    parser.add_argument("fault", nargs="?", choices=sorted(FAULTS), help="要注入的故障")
    parser.add_argument("--list", action="store_true", help="列出故障与期望行为")
    parser.add_argument(
        "--wait", type=int, default=SAMPLE_SECONDS, help=f"注入后观察秒数（默认 {SAMPLE_SECONDS}）"
    )
    args = parser.parse_args()

    if args.list:
        for name, (_fn, label) in FAULTS.items():
            mark = "（需用户手动执行）" if name in EMULATOR_CONTROL_FAULTS else ""
            print(f"  {name:<11} {label}{mark}")
        print("\n" + EXPECTATIONS)
        return 0

    if not args.fault:
        parser.error("需要指定故障类型，或使用 --list")

    if args.fault in EMULATOR_CONTROL_FAULTS and not emulator_control_allowed():
        print(
            f"「{FAULTS[args.fault][1]}」会改变模拟器状态，按 AGENTS.md R2 只能由用户手动执行。\n"
            "确认要跑的话，请在你自己的 cmd 窗口里先设置环境变量：\n"
            f"    set {GUARD_ENV}=1\n"
            "然后重新运行本命令。AI 会话里不会设置这个变量。",
            file=sys.stderr,
        )
        return 2

    SAMPLE_SECONDS = max(1, args.wait)

    if _port() is None:
        print("警告：没有找到 runtime/port.txt，Lite 服务可能没在运行。", file=sys.stderr)
        print("      注入仍会执行，但看不到反应。", file=sys.stderr)

    action, label = FAULTS[args.fault]
    print(f"注入故障：{label}（{args.fault}）")
    note = action()
    print(f"已注入。{note}")
    _sample(label)
    print("\n判定标准：" + EXPECTATIONS.splitlines()[2])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
