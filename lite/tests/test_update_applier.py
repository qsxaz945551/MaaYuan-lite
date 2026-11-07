from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from lite.daily_plan import load_profile
from lite.pipeline_fixes import FIXES
from lite.round_progress import ROUND_MARKERS
from lite.task_options_service import load_selection
from lite.update_applier import apply_staged, has_staged, rollback


def _node_names() -> set[str]:
    """Every node the gate checks, plus filler to pass the count threshold."""
    nodes: set[str] = set()
    for patch in FIXES.values():
        nodes.update(patch)
    for markers in ROUND_MARKERS.values():
        nodes.update(markers)
    nodes.update(f"filler-{index}" for index in range(120))
    return nodes


def _write_pipeline(root: Path, marker: str) -> None:
    pipeline = root / "pipeline"
    pipeline.mkdir(parents=True)
    for name in _node_names():
        (pipeline / f"{name}.json").write_text(
            json.dumps({name: {"next": [], "marker": marker}}, ensure_ascii=False),
            encoding="utf-8",
        )


def _write_interface(root: Path) -> None:
    names: set[str] = set()
    for item in load_profile().get("daily_order", []):
        name = item.get("name") if isinstance(item, dict) else str(item)
        if name:
            names.add(str(name))
    names.update(str(key) for key in load_selection() if key)
    root.parent.mkdir(parents=True, exist_ok=True)
    root.write_text(
        json.dumps({"task": [{"name": name, "entry": "x"} for name in sorted(names)]}, ensure_ascii=False),
        encoding="utf-8",
    )


class ApplyStagedTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        _write_pipeline(self.root / "assets" / "resource" / "base", "old")
        _write_pipeline(self.root / "assets.next" / "assets" / "resource" / "base", "new")
        _write_interface(self.root / "assets" / "interface.json")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _marker(self) -> str:
        sample = next((self.root / "assets" / "resource" / "base" / "pipeline").glob("*.json"))
        return json.loads(sample.read_text(encoding="utf-8"))[sample.stem]["marker"]

    def test_lite_added_template_survives_the_swap(self) -> None:
        """整目录替换会带走 activity_title.png，切换后必须补回来。"""
        extra = self.root / "assets" / "resource" / "base" / "image" / "activity_title.png"
        extra.parent.mkdir(parents=True)
        extra.write_bytes(b"template-bytes")

        result = apply_staged(self.root, interface_source="")

        self.assertTrue(result["ok"], result)
        self.assertIn("image/activity_title.png", result.get("restoredExtras", []))
        live = self.root / "assets" / "resource" / "base" / "image" / "activity_title.png"
        self.assertEqual(live.read_bytes(), b"template-bytes")

    def test_staged_detected(self) -> None:
        self.assertTrue(has_staged(self.root))

    def test_apply_swaps_tree(self) -> None:
        result = apply_staged(self.root, interface_source="")
        self.assertTrue(result["ok"], result)
        self.assertEqual(self._marker(), "new")
        self.assertFalse(has_staged(self.root))
        self.assertTrue((self.root / "assets.prev" / "resource" / "base").is_dir())

    def test_rollback_restores_old(self) -> None:
        apply_staged(self.root, interface_source="")
        self.assertTrue(rollback(self.root))
        self.assertEqual(self._marker(), "old")

    def test_missing_stage_is_reported(self) -> None:
        result = apply_staged(self.root / "nope", interface_source="")
        self.assertFalse(result["ok"])

    def test_gate_rejects_broken_stage(self) -> None:
        broken = self.root / "assets.next" / "assets" / "resource" / "base"
        for path in broken.rglob("*.json"):
            path.unlink()
        (broken / "pipeline").rmdir()
        result = apply_staged(self.root, interface_source="")
        self.assertFalse(result["ok"])
        self.assertEqual(self._marker(), "old")


if __name__ == "__main__":
    unittest.main()
