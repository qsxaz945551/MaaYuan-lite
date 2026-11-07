"""Environment self-check for MaaYuan Lite.

One command that answers "why doesn't it start": interpreter, packages, native
libraries, MaaAgentBinary, resources, OCR models, agent, adb, interface, port.

Usage:
    python app.py --selftest
"""

from __future__ import annotations

import ctypes
import importlib.metadata
import os
import socket
import subprocess
import sys
from pathlib import Path

from .constants import DEFAULT_HOST, DEFAULT_PORT
from typing import Any

OK = "[OK]  "
FAIL = "[FAIL]"
WARN = "[WARN]"


def _resolve(value: str, project_root: Path, default: Path) -> Path:
    text = (value or "").strip()
    path = Path(text) if text else default
    return path if path.is_absolute() else (project_root / path)


class Report:
    def __init__(self, echo: bool = True) -> None:
        self.echo = echo
        self.items: list[dict[str, str]] = []
        self.failed = 0
        self.warned = 0

    def _add(self, name: str, status: str, detail: str) -> None:
        self.items.append({"name": name, "status": status, "detail": detail})

    def ok(self, name: str, detail: str = "") -> None:
        self._add(name, "ok", detail)
        if self.echo:
            print(f"{OK} {name:<16}{detail}")

    def fail(self, name: str, detail: str) -> None:
        self.failed += 1
        self._add(name, "fail", detail)
        if self.echo:
            print(f"{FAIL} {name:<16}{detail}")

    def warn(self, name: str, detail: str) -> None:
        self.warned += 1
        self._add(name, "warn", detail)
        if self.echo:
            print(f"{WARN} {name:<16}{detail}")


def _package_version(dist: str) -> str:
    try:
        return importlib.metadata.version(dist)
    except importlib.metadata.PackageNotFoundError:
        return "?"


def _check_python(report: Report) -> None:
    report.ok("解释器", f"{sys.executable} ({sys.version.split()[0]})")
    print(f"       sys.path: {'; '.join(sys.path[:4])}")


def _check_packages(report: Report) -> None:
    modules = ["maa", "cv2", "numpy", "PIL", "loguru", "zhconv", "openpyxl", "jsonschema"]
    missing = []
    for name in modules:
        try:
            __import__(name)
        except Exception:  # noqa: BLE001 - report only
            missing.append(name)
    if missing:
        report.fail("依赖包", "无法导入：" + ", ".join(missing))
    else:
        report.ok("依赖包", f"8/8 可导入（maafw {_package_version('maafw')}）")


def _check_native(report: Report, runtime_root: Path) -> Path | None:
    candidates = [
        runtime_root / "native",
        runtime_root / "runtimes" / "win-x64" / "native",
    ]
    try:  # maa 包自带的 bin 目录
        import maa  # noqa: F401

        candidates.append(Path(maa.__file__).parent / "bin")
    except Exception:  # noqa: BLE001
        pass

    for path in candidates:
        if not (path / "MaaFramework.dll").is_file():
            continue
        try:
            if hasattr(os, "add_dll_directory"):
                handle = os.add_dll_directory(str(path))
            else:
                handle = None
            try:
                ctypes.WinDLL(str(path / "MaaFramework.dll"))
            finally:
                if handle is not None:
                    handle.close()
            report.ok("原生库", f"{path}（MaaFramework.dll 已加载）")
            return path
        except OSError as error:
            report.fail("原生库", f"{path} 存在但加载失败：{error}")
            return path

    report.fail("原生库", "未找到 MaaFramework.dll，检查 runtime_env/runtimes/win-x64/native")
    return None


def _check_agent_binary(report: Report, runtime_root: Path) -> None:
    candidates = [
        runtime_root / "libs" / "MaaAgentBinary",
        runtime_root / "MaaAgentBinary",
        runtime_root / "python" / "Lib" / "site-packages" / "MaaAgentBinary",
    ]
    try:
        import MaaAgentBinary  # noqa: F401

        candidates.append(Path(MaaAgentBinary.__file__).parent)
    except Exception:  # noqa: BLE001
        pass

    for path in candidates:
        if path.is_dir():
            report.ok("MaaAgentBinary", str(path))
            return
    report.fail("MaaAgentBinary", "未找到，检查 runtime_env/python/Lib/site-packages")


def _check_resource(report: Report, resource_root: Path) -> None:
    if not resource_root.is_dir():
        report.fail("任务资源", f"目录不存在：{resource_root}")
        return
    pipeline = resource_root / "pipeline"
    count = len(list(pipeline.rglob("*.json"))) if pipeline.is_dir() else 0
    if count < 100:
        report.fail("任务资源", f"{resource_root} pipeline 仅 {count} 个 JSON")
    else:
        report.ok("任务资源", f"{resource_root}（pipeline {count} 个）")

    ocr = resource_root / "model" / "ocr"
    missing = [name for name in ("det.onnx", "rec.onnx", "keys.txt") if not (ocr / name).is_file()]
    if missing:
        report.fail("OCR 模型", "缺少：" + ", ".join(missing))
    else:
        report.ok("OCR 模型", str(ocr))


def _check_agent(report: Report, agent_root: Path) -> None:
    main_py = agent_root / "main.py"
    if not main_py.is_file():
        report.fail("Agent 脚本", f"缺少 {main_py}")
        return
    count = len(list(agent_root.rglob("*.py")))
    report.ok("Agent 脚本", f"{agent_root}（{count} 个 py）")


def _check_adb(report: Report, adb_path: Path, serial: str) -> None:
    if not adb_path.is_file():
        report.fail("adb", f"不存在：{adb_path}")
        return
    try:
        output = subprocess.run(
            [str(adb_path), "devices"],
            capture_output=True, text=True, timeout=10,
            encoding="utf-8", errors="ignore",
        ).stdout
    except Exception as error:  # noqa: BLE001
        report.fail("adb", f"执行失败：{error}")
        return

    online = any(
        line.split()[0] == serial and len(line.split()) > 1 and line.split()[1] == "device"
        for line in output.splitlines()
        if line.strip() and not line.startswith("List")
    )
    if online:
        report.ok("adb", f"{adb_path}（{serial} 在线）")
    else:
        report.warn("adb", f"{adb_path} 可用，但 {serial} 未连接（模拟器没开？）")


def _check_interface(report: Report, project_root: Path) -> None:
    """Check the generated interface, which is what actually gets loaded."""
    generated = project_root / "build" / "generated" / "interface.json"
    if not generated.is_file():
        report.fail("interface", f"缺少 {generated}，运行 lite/apply_scope.py")
        return
    import json

    try:
        data = json.loads(generated.read_text(encoding="utf-8"))
        tasks = len(data.get("task", []))
    except Exception as error:  # noqa: BLE001
        report.fail("interface", f"解析失败：{error}")
        return
    if tasks < 10:
        report.fail("interface", f"只有 {tasks} 个任务，可能裁剪异常")
    else:
        report.ok("interface", f"{generated}（{tasks} 个任务）")


def _check_port(report: Report, host: str, port: int) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(1.0)
        busy = sock.connect_ex((host, port)) == 0
    if busy:
        report.warn("端口", f"{host}:{port} 已被占用（可能有实例在运行）")
    else:
        report.ok("端口", f"{host}:{port} 可用")


def evaluate(project_root: Path, config: dict[str, Any], echo: bool = True) -> Report:
    say = print if echo else (lambda *args, **kwargs: None)
    if echo and hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            pass

    say("MaaYuan Lite 自检\n" + "=" * 60)
    say("（若出现 PluginMgr ... plugins 报错，属已知正常输出，不影响识别与点击）\n")
    report = Report(echo)

    runtime_root = _resolve(str(config.get("runtime_root", "")), project_root, project_root)
    resource_root = _resolve(str(config.get("resource_root", "")), project_root,
                             project_root / "assets" / "resource" / "base")
    agent_root = _resolve(str(config.get("agent_root", "")), project_root, project_root / "agent")
    interface_file = project_root / "build" / "generated" / "interface.json"
    adb_path = _resolve(str(config.get("adb_path", "")), project_root, project_root / "adb.exe")
    serial = str(config.get("adb_serial", "emulator-5554"))

    say(f"runtime_root : {runtime_root}")
    say(f"resource_root: {resource_root}")
    say(f"agent_root   : {agent_root}")
    say(f"interface    : {interface_file}")
    say(f"adb          : {adb_path}\n")

    _check_python(report)
    _check_packages(report)
    _check_native(report, runtime_root)
    _check_agent_binary(report, runtime_root)
    _check_resource(report, resource_root)
    _check_agent(report, agent_root)
    _check_adb(report, adb_path, serial)
    _check_interface(report, project_root)
    _check_port(
        report,
        str(config.get("host", DEFAULT_HOST)),
        int(config.get("port", DEFAULT_PORT)),
    )

    _persist(project_root, report)
    return report


def _persist(project_root: Path, report: Report) -> None:
    """Drop the result where the shell and support requests can find it."""
    import json
    from datetime import datetime

    try:
        target = project_root / "runtime" / "selftest.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(
                {
                    "checkedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "ok": report.failed == 0,
                    "failed": report.failed,
                    "warned": report.warned,
                    "items": report.items,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    except OSError:
        pass


def run_selftest(project_root: Path, config: dict[str, Any]) -> int:
    report = evaluate(project_root, config, echo=True)
    print("=" * 60)
    if report.failed:
        print(f"结论：{report.failed} 项失败，{report.warned} 项警告")
        return 1
    print(f"结论：通过（{report.warned} 项警告）")
    return 0


def collect(project_root: Path, config: dict[str, Any]) -> dict[str, Any]:
    """Same checks, no printing: used by GET /api/health."""
    report = evaluate(project_root, config, echo=False)
    return {
        "ok": report.failed == 0,
        "failed": report.failed,
        "warned": report.warned,
        "checks": report.items,
    }
