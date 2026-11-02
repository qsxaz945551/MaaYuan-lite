"""Build a portable MaaYuan Lite release folder.

    python devtools/build_release.py            # -> dist/MaaYuan-Lite-<version>/
    python devtools/build_release.py --zip      # also produce a zip (slow)

The output is self-contained except for the .NET 10 Desktop Runtime
(framework-dependent WPF) and the emulator itself.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lite"))
from version import VERSION  # noqa: E402

EXCLUDE_DIRS = {
    "__pycache__",
    ".git",
    "spike",
    "failures",
    "logs",
    "on_error",
    "node_modules",
    "tests",
}
EXCLUDE_SUFFIX = {".pyc", ".pyo", ".pdb"}

START_BAT = """@echo off
chcp 65001 >nul
cd /d "%~dp0"

if not exist "MaaYuanLite.Desktop.exe" (
  echo [ERROR] 缺少 MaaYuanLite.Desktop.exe
  pause
  exit /b 1
)

if not exist "runtime_env\\python\\python.exe" (
  echo [ERROR] 运行时缺失：runtime_env\\python\\python.exe
  pause
  exit /b 1
)

start "" "MaaYuanLite.Desktop.exe"
"""


def ignore(directory: str, names: list[str]) -> list[str]:
    return [
        name
        for name in names
        if name in EXCLUDE_DIRS or Path(name).suffix in EXCLUDE_SUFFIX
    ]


def copy_tree(source: Path, target: Path, label: str) -> None:
    if not source.exists():
        print(f"  [跳过] {label}：{source} 不存在")
        return
    shutil.copytree(source, target, ignore=ignore, dirs_exist_ok=True)
    size = sum(path.stat().st_size for path in target.rglob("*") if path.is_file())
    print(f"  {label:<24}{size / 1048576:8.1f} MB")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="dist")
    parser.add_argument("--version", default=VERSION)
    parser.add_argument("--zip", action="store_true", help="额外生成 zip（较慢）")
    parser.add_argument("--skip-publish", action="store_true", help="复用已有 WPF 产物")
    args = parser.parse_args()

    target = ROOT / args.out / f"MaaYuan-Lite-{args.version}"
    if target.exists():
        print(f"清理旧产物：{target}")
        shutil.rmtree(target)
    target.mkdir(parents=True)

    print(f"目标：{target}")

    if not args.skip_publish:
        print("dotnet publish ...")
        subprocess.run(
            [
                "dotnet", "publish", "desktop/MaaYuanLite.Desktop",
                "-c", "Release", "-r", "win-x64", "--self-contained", "false",
                "-o", str(target),
            ],
            cwd=ROOT,
            check=True,
            stdout=subprocess.DEVNULL,
        )

    print("重建 interface ...")
    subprocess.run(
        [str(ROOT / "runtime_env" / "python" / "python.exe"), "lite/apply_scope.py"],
        cwd=ROOT,
        check=True,
        stdout=subprocess.DEVNULL,
    )

    print("复制运行时与资源：")
    copy_tree(ROOT / "runtime_env", target / "runtime_env", "runtime_env")
    copy_tree(ROOT / "assets" / "resource" / "base", target / "assets" / "resource" / "base", "assets/resource/base")
    interface_source = ROOT / "assets" / "interface.json"
    if interface_source.is_file():
        shutil.copy2(interface_source, target / "assets" / "interface.json")
    copy_tree(ROOT / "agent", target / "agent", "agent")
    copy_tree(ROOT / "lite", target / "lite", "lite")
    shutil.rmtree(target / "lite" / "tests", ignore_errors=True)

    # Release config: no vendor/, no machine-specific paths. Empty resource /
    # agent / interface mean "use the copies inside this folder".
    config = json.loads((ROOT / "lite" / "runtime-config.json").read_text(encoding="utf-8-sig"))
    config.update(
        {
            "runtime_root": "runtime_env",
            "adb_path": "",
            "resource_root": "",
            "agent_root": "",
            "interface_source": "",
            "resource_path": "assets/resource/base",
        }
    )
    (target / "lite" / "runtime-config.json").write_text(
        json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    for name in ("app.py", "NOTICE.md", "LITE.md", "MANIFEST.md"):
        source = ROOT / name
        if source.is_file():
            shutil.copy2(source, target / name)
    docs = ROOT / "docs"
    if docs.is_dir():
        copy_tree(docs, target / "docs", "docs")

    generated = target / "build" / "generated"
    generated.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "build" / "generated" / "interface.json", generated / "interface.json")
    shutil.copy2(ROOT / "build" / "generated" / "scope-report.json", generated / "scope-report.json")

    (target / "start-lite.bat").write_text(START_BAT, encoding="utf-8")

    total = sum(path.stat().st_size for path in target.rglob("*") if path.is_file())
    files = sum(1 for path in target.rglob("*") if path.is_file())
    print(f"\n产物：{target}")
    print(f"文件 {files} 个，合计 {total / 1048576:.0f} MB")

    leftover = [
        path.relative_to(target)
        for path in target.rglob("*")
        if path.is_file() and ("Apps Game" in path.name or path.suffix == ".disabled")
    ]
    if leftover:
        print("警告：产物里仍有原版目录痕迹：" + ", ".join(str(item) for item in leftover[:5]))

    if args.zip:
        print("压缩 zip ...")
        archive = shutil.make_archive(str(target), "zip", root_dir=str(target))
        print(f"zip：{archive}（{Path(archive).stat().st_size / 1048576:.0f} MB）")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
