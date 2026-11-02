"""Audit which site-packages are actually needed by MaaYuan Lite.

Static scan: parse every import in app.py / lite / agent, subtract stdlib and
local modules, map import names to distribution names, then compare against the
real site-packages directory and report size for each.

Usage:
    python devtools/audit_runtime.py
    python devtools/audit_runtime.py --packages "D:/.../python/Lib/site-packages"
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "lite" / "runtime-config.json"

# import name -> distribution name on disk (lowercase, '-' and '_' normalised)
DIST_NAME = {
    "cv2": "opencv-python",
    "pil": "pillow",
    "maa": "maafw",
    "dateutil": "python-dateutil",
    "attr": "attrs",
    "yaml": "pyyaml",
    "strenum": "strenum",
}

# imported at runtime through agent scripts; static scan cannot see these
SMOKE = ["maa", "cv2", "numpy", "PIL", "loguru", "zhconv", "jsonschema", "openpyxl", "dateutil"]

# optional imports wrapped in try/except ImportError: absence is tolerated
OPTIONAL = {"certifi"}

# referenced by path, never imported
PATH_REF = {"MaaAgentBinary": "session.py 作为 AdbController 的 agent_path"}

# confirmed unused by any code path; safe to delete from the release runtime
SAFE_DELETE = {"pandas", "pandas.libs", "pip"}


def local_module_names() -> set[str]:
    names = {path.stem for path in ROOT.glob("*.py")}
    for folder in (ROOT / "lite", ROOT / "agent", ROOT / "devtools"):
        if folder.is_dir():
            names.add(folder.name)
            for path in folder.rglob("*.py"):
                names.add(path.stem)
            for path in folder.rglob("*"):
                if path.is_dir():
                    names.add(path.name)
    return names


def imported_names() -> dict[str, set[str]]:
    """top-level import name -> files that use it"""
    found: dict[str, set[str]] = {}
    targets = [ROOT / "app.py"]
    targets += list((ROOT / "lite").rglob("*.py"))
    targets += list((ROOT / "agent").rglob("*.py"))
    targets = [
        path for path in targets
        if "tests" not in path.parts and "__pycache__" not in path.parts
    ]

    for path in targets:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                names = [node.module.split(".")[0]]
            for name in names:
                found.setdefault(name, set()).add(str(path.relative_to(ROOT)))
    return found


def normalize(name: str) -> str:
    return name.lower().replace("-", "_").replace(".", "_")


def dist_for(import_name: str) -> str:
    return DIST_NAME.get(import_name.lower(), import_name)


def dir_size(path: Path) -> int:
    total = 0
    for item in path.rglob("*"):
        try:
            if item.is_file():
                total += item.stat().st_size
        except OSError:
            continue
    return total


def find_packages() -> Path | None:
    config = json.loads(CONFIG.read_text(encoding="utf-8-sig"))
    runtime_root = Path(config.get("runtime_root", ""))
    if not runtime_root.is_absolute():
        runtime_root = ROOT / runtime_root
    candidates = [
        runtime_root / "python" / "Lib" / "site-packages",
        ROOT / "runtime_env" / "python" / "Lib" / "site-packages",
    ]
    for path in candidates:
        if path.is_dir():
            return path
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--packages", default="", help="site-packages 目录，默认自动探测")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args()

    packages = Path(args.packages) if args.packages else find_packages()
    if packages is None or not packages.is_dir():
        print("[错误] 找不到 site-packages，请用 --packages 指定")
        return 2

    local = local_module_names()
    stdlib = set(sys.stdlib_module_names)
    imports = imported_names()

    third_party: dict[str, set[str]] = {}
    for name, files in imports.items():
        if name in stdlib or name in local or name.startswith("_"):
            continue
        third_party[name] = files

    installed: dict[str, Path] = {}
    for entry in packages.iterdir():
        if not entry.is_dir():
            continue
        if entry.name.endswith((".dist-info", ".data", ".libs")):
            continue
        installed[normalize(entry.name)] = entry

    needed = []
    missing = []
    optional = []
    used_dirs: set[str] = set()
    for name in sorted(third_party):
        dist = dist_for(name)
        directory = installed.get(normalize(name)) or installed.get(normalize(dist))
        if directory is None:
            prefix = normalize(name)
            fallback = [key for key in installed if key.startswith(prefix)]
            directory = installed[fallback[0]] if fallback else None
        if directory is None:
            (optional if name in OPTIONAL else missing).append((name, dist))
            continue
        used_dirs.add(directory.name)
        needed.append((name, dist, directory, dir_size(directory)))

    safe_delete = []
    keep = []
    for _, directory in sorted(installed.items()):
        if directory.name in used_dirs:
            continue
        name = directory.name
        if name in PATH_REF:
            keep.append((name, dir_size(directory), PATH_REF[name]))
        elif name in SAFE_DELETE:
            safe_delete.append((name, dir_size(directory)))
        else:
            keep.append((name, dir_size(directory), "传递依赖或运行时组件"))

    if args.json:
        print(json.dumps({
            "packages": str(packages),
            "needed": [{"import": n, "dist": d, "size": s} for n, d, _, s in needed],
            "keep": [{"name": n, "size": s, "reason": r} for n, s, r in keep],
            "safe_delete": [{"name": n, "size": s} for n, s in safe_delete],
            "missing": [{"import": n, "dist": d} for n, d in missing],
            "optional": [{"import": n, "dist": d} for n, d in optional],
        }, ensure_ascii=False, indent=2))
        return 1 if missing else 0

    print(f"site-packages: {packages}\n")

    print("== 需要（代码里 import 到的） ==")
    for name, dist, _, size in sorted(needed, key=lambda row: -row[3]):
        print(f"  {name:<12}{dist:<18}{size / 1048576:7.1f} MB")

    print("\n== 保留（传递依赖 / 按路径引用） ==")
    for name, size, reason in sorted(keep, key=lambda row: -row[1]):
        print(f"  {name:<30}{size / 1048576:7.1f} MB  {reason}")

    print("\n== 可安全删除 ==")
    for name, size in sorted(safe_delete, key=lambda row: -row[1]):
        print(f"  {name:<30}{size / 1048576:7.1f} MB")

    print("\n== 缺失（import 了但没装） ==")
    if missing:
        for name, dist in missing:
            print(f"  {name}（{dist}）")
    else:
        print("  无")

    if optional:
        print("\n== 可选（缺失也能跑） ==")
        for name, dist in optional:
            print(f"  {name}（{dist}）")

    total_needed = sum(size for _, _, _, size in needed)
    total_delete = sum(size for _, size in safe_delete)
    print(f"\n合计：需要 {total_needed / 1048576:.0f} MB / 可删 {total_delete / 1048576:.0f} MB")

    print("\n== 运行时冒烟（能否 import） ==")
    for name in SMOKE:
        try:
            __import__(name)
            print(f"  {name:<12} ok")
        except Exception as error:  # noqa: BLE001 - report, don't fail
            print(f"  {name:<12} FAIL {error}")

    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
