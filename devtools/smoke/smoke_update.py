"""End-to-end check of the staged swap using the real resource tree.

Runs in a temp directory so the live assets are never touched, but the files
are the real ones: the compatibility gate therefore sees genuine pipeline JSON
and passes for the same reasons a shipped update would.

    python devtools/smoke/smoke_update.py
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from lite.update_applier import apply_staged, backup_root, has_staged, rollback  # noqa: E402


def tree_size(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def pipeline_count(path: Path) -> int:
    return len(list((path / "pipeline").rglob("*.json")))


def main() -> int:
    source = ROOT / "assets" / "resource" / "base"
    if not source.is_dir():
        print(f"缺少资源目录：{source}")
        return 1

    with tempfile.TemporaryDirectory() as temp:
        sandbox = Path(temp)
        live = sandbox / "assets" / "resource" / "base"
        print(f"[1/6] 复制真实资源到沙箱（{tree_size(source) / 1048576:.0f} MB）")
        shutil.copytree(source, live)
        shutil.copy2(ROOT / "assets" / "interface.json", sandbox / "assets" / "interface.json")

        print("[2/6] 复制 agent 与来源清单")
        shutil.copytree(ROOT / "agent", sandbox / "agent")
        manifest = ROOT / "assets" / ".source.json"
        if manifest.is_file():
            shutil.copy2(manifest, sandbox / "assets" / ".source.json")

        print("[3/6] 构造待生效目录 assets.next/")
        staged = sandbox / "assets.next"
        shutil.copytree(sandbox / "assets", staged / "assets")
        shutil.copytree(sandbox / "agent", staged / "agent")
        (staged / "assets" / "interface.json").write_text(
            (sandbox / "assets" / "interface.json").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        assert has_staged(sandbox), "待生效目录未被识别"

        before_count = pipeline_count(live)
        before_size = tree_size(live)

        print("[4/6] 执行切换")
        result = apply_staged(sandbox, interface_source="")
        if not result.get("ok"):
            print(f"  失败：{result}")
            return 1
        after_count = pipeline_count(sandbox / "assets" / "resource" / "base")
        print(
            f"  pipeline {before_count} → {after_count}，"
            f"大小 {before_size / 1048576:.0f} MB，"
            f"agent {'已' if result.get('agentSwapped') else '未'}替换"
        )
        if after_count != before_count:
            print("  管线数量不一致，说明拷贝不完整")
            return 1
        if not (backup_root(sandbox) / "resource" / "base").is_dir():
            print("  备份目录缺失")
            return 1
        if has_staged(sandbox):
            print("  切换后暂存目录仍在")
            return 1

        print("[5/6] 回滚")
        if not rollback(sandbox):
            print("  回滚失败")
            return 1
        restored = pipeline_count(sandbox / "assets" / "resource" / "base")
        restored_size = tree_size(sandbox / "assets" / "resource" / "base")
        print(f"  pipeline {restored}，大小 {restored_size / 1048576:.0f} MB")
        if restored != before_count or restored_size != before_size:
            print("  回滚后与原始状态不一致")
            return 1

        print("[6/6] 通过：切换与回滚都可逆，实机资源未被修改")
        return 0


if __name__ == "__main__":
    sys.exit(main())
