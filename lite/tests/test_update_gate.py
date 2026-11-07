"""The compatibility gate must not reject nodes the patch itself creates.

The 11-06 upstream update was refused on every launch because
``pipeline_fixes[start_日常鸢报启动]`` references ``等待小道消息收集完成`` and
``end_鸢报四连完成`` — both created by the fix, absent upstream by design.
The gate treated "not in upstream" as "renamed", so the update could never land.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from lite.daily_plan import load_profile
from lite.pipeline_fixes import FIXES, NEW_NODES
from lite.round_progress import ROUND_MARKERS
from lite.task_options_service import load_selection
from lite.update_gate import validate

ROOT = Path(__file__).resolve().parents[2]


def _patched_nodes() -> set[str]:
    """Every node the fixes expect to find upstream (new nodes excluded)."""
    nodes: set[str] = set()
    for entry, patch in FIXES.items():
        nodes.update(set(patch) - NEW_NODES.get(entry, set()))
    for markers in ROUND_MARKERS.values():
        nodes.update(markers)
    return nodes


def _expected_tasks() -> set[str]:
    names: set[str] = set()
    for item in load_profile().get("daily_order", []):
        name = item.get("name") if isinstance(item, dict) else str(item)
        if name:
            names.add(str(name))
    names.update(str(key) for key in load_selection() if key)
    return names


class GateTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.pipeline = self.root / "assets" / "resource" / "base" / "pipeline"
        self.pipeline.mkdir(parents=True)
        self.interface = self.root / "build" / "generated" / "interface.json"
        self.interface.parent.mkdir(parents=True)
        self._write_pipeline(_patched_nodes() | {f"filler-{i}" for i in range(120)})
        self._write_interface(_expected_tasks() | {f"extra-{i}" for i in range(10)})

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _write_pipeline(self, nodes: set[str]) -> None:
        payload = {name: {"next": []} for name in sorted(nodes)}
        (self.pipeline / "all.json").write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )

    def _write_interface(self, names: set[str]) -> None:
        self.interface.write_text(
            json.dumps(
                {"task": [{"name": name, "entry": "x"} for name in sorted(names)]},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    def test_new_nodes_are_not_required_upstream(self) -> None:
        self.assertEqual(validate(self.root), [])

    def test_missing_patched_node_is_still_reported(self) -> None:
        """真正的重命名要拦住：覆盖一个上游不存在的节点等于补丁静默失效。"""
        nodes = _patched_nodes() | {f"filler-{i}" for i in range(120)}
        victim = next(iter(FIXES["start_日常鸢报启动"]))
        nodes.discard(victim)
        self._write_pipeline(nodes)

        problems = validate(self.root)
        self.assertTrue(
            any(victim in problem for problem in problems),
            f"应当报告缺失的 {victim}，实际：{problems}",
        )


class NewNodeDeclarationTest(unittest.TestCase):
    def test_declared_nodes_belong_to_their_patch(self) -> None:
        for entry, nodes in NEW_NODES.items():
            self.assertIn(entry, FIXES)
            self.assertTrue(nodes <= set(FIXES[entry]), f"{entry} 声明了补丁里没有的节点")

    def test_declared_nodes_are_absent_from_live_resources(self) -> None:
        """声明为"新增"的节点如果上游真有，就该从清单里删掉。"""
        pipeline = ROOT / "assets" / "resource" / "base" / "pipeline"
        if not pipeline.is_dir():
            self.skipTest("资源目录不在")
        text = "".join(
            path.read_text(encoding="utf-8", errors="ignore")
            for path in pipeline.rglob("*.json")
        )
        for nodes in NEW_NODES.values():
            for node in nodes:
                self.assertNotIn(node, text, f"{node} 已存在于上游资源，NEW_NODES 该清理")
