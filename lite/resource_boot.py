"""Everything that has to be settled before the service starts serving.

Resource switching, interface regeneration and config loading all happen before
the HTTP server exists. They used to live in ``app.py`` next to the routes,
which made the composition root hard to read and the update path hard to test.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG_FILE = ROOT / "lite" / "runtime-config.json"
INTERFACE_FILE = ROOT / "build" / "generated" / "interface.json"


def managed_resource_root(config: dict) -> Path:
    value = str(config.get("resource_root") or "").strip()
    return Path(value) if value else ROOT / "assets" / "resource" / "base"


def bundle_owns_resources(config: dict) -> bool:
    """True when the running resources are the bundle's own copy.

    A dev checkout points ``resource_root`` at ``vendor/MaaYuan-src``; swapping
    ``assets/`` there would update a tree the runtime never reads, so the
    updater refuses instead of pretending to work.
    """
    try:
        return managed_resource_root(config).resolve() == (
            ROOT / "assets" / "resource" / "base"
        ).resolve()
    except OSError:
        return False


def apply_staged_resources(config: dict) -> tuple[str, str] | None:
    """Switch to a downloaded resource tree before anything opens the pipeline.

    Returns ``(message, level)`` for the run log: this happens before the
    service exists, so the shell only sees it after the fact. Without that line
    the resource tree silently changes under the user between two launches.
    """
    from lite.update_applier import apply_staged, cleanup_partial, has_staged

    cleanup_partial(ROOT)
    if not has_staged(ROOT):
        return None
    if not bundle_owns_resources(config):
        message = "检测到待生效资源，但当前配置指向开发目录，已跳过自动切换（用 devtools/release/sync_repo.py --update）。"
        print(message, file=sys.stderr)
        return message, "warn"

    result = apply_staged(ROOT, str(config.get("interface_source", "")))
    if not result.get("ok"):
        problems = result.get("problems") or []
        detail = f"（{'；'.join(str(item) for item in problems[:3])}）" if problems else ""
        message = f"资源切换失败，继续使用旧版本：{result.get('error')}{detail}"
        print(message, file=sys.stderr)
        return message, "warn"

    ok, detail = rebuild_interface()
    if not ok:
        # The gate checked the tree, but a broken interface still means the new
        # resources cannot be used. Go back rather than run on half a bundle.
        from lite.update_applier import rollback

        restored = rollback(ROOT)
        rebuild_interface()
        message = (
            f"新资源无法生成 interface（{detail}），"
            f"{'已回滚到旧版本' if restored else '回滚失败，请手动恢复 assets.prev'}"
        )
        print(message, file=sys.stderr)
        return message, "error"

    extras = result.get("restoredExtras") or []
    message = (
        f"已切换到新资源（agent {'已' if result.get('agentSwapped') else '未'}替换），"
        f"interface 重建成功"
        f"{f'，补回 {len(extras)} 个本地文件' if extras else ''}。"
    )
    print(message, flush=True)
    return message, "info"


def ensure_interface(config: dict) -> None:
    """Rebuild the scoped interface when the source is newer than the output.

    The WPF shell starts app.py directly, so this cannot live in a .bat file:
    an update or a manual resource refresh must not leave a stale task list.
    """
    generated = ROOT / "build" / "generated" / "interface.json"
    source_value = str(config.get("interface_source") or "").strip()
    source = Path(source_value) if source_value else ROOT / "assets" / "interface.json"
    try:
        if generated.is_file() and (
            not source.is_file() or generated.stat().st_mtime >= source.stat().st_mtime
        ):
            return
    except OSError:
        pass
    ok, detail = rebuild_interface()
    if not ok:
        print(f"interface 重建失败：{detail}", file=sys.stderr)


def rebuild_interface() -> tuple[bool, str]:
    """Regenerate build/generated/interface.json after resources changed."""
    try:
        result = subprocess.run(
            [sys.executable, str(ROOT / "lite" / "apply_scope.py")],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
        )
    except (OSError, subprocess.SubprocessError) as error:
        return False, str(error)
    if result.returncode != 0:
        return False, (result.stderr or result.stdout).strip()[:400]
    return True, result.stdout.strip()[:400]


def load_config() -> dict:
    with CONFIG_FILE.open("r", encoding="utf-8-sig") as handle:
        config = json.load(handle)
    # Relative paths are resolved against the project root, not the current
    # working directory: the bundle must behave the same when started from
    # Explorer, a shortcut, or the WPF shell.
    for key in (
        "runtime_root",
        "adb_path",
        "resource_path",
        "resource_root",
        "agent_root",
        "interface_source",
    ):
        value = str(config.get(key) or "").strip()
        if not value:
            continue
        path = Path(value)
        config[key] = str(path if path.is_absolute() else (ROOT / path).resolve())

    from lite.adb_finder import find_adb

    adb, source = find_adb(str(config.get("adb_path") or ""), ROOT)
    if adb is not None:
        config["adb_path"] = str(adb)
        config["adb_source"] = source
    return config


def load_interface() -> dict:
    return json.loads(INTERFACE_FILE.read_text(encoding="utf-8"))
