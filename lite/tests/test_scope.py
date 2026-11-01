from __future__ import annotations

import json
import unittest
from pathlib import Path

from lite.apply_scope import apply_scope


ROOT = Path(__file__).resolve().parents[2]


class ScopeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scope = json.loads((ROOT / "lite" / "scope.json").read_text(encoding="utf-8"))
        cls.interface = json.loads(
            (ROOT / "assets" / "interface.json").read_text(encoding="utf-8-sig")
        )
        cls.overrides = json.loads(
            (ROOT / "lite" / "pipeline-overrides.json").read_text(encoding="utf-8")
        )

    def test_excluded_tasks_are_absent(self):
        lite, report = apply_scope(self.interface, self.scope, self.overrides)
        names = {task["name"] for task in lite["task"]}
        for item in self.scope["tasks"]["exclude"]:
            self.assertNotIn(item["name"], names)
        self.assertEqual(report["source_task_count"] - report["excluded_task_count"], len(names))

    def test_confirmed_war_chariot_override(self):
        lite, report = apply_scope(self.interface, self.scope, self.overrides)
        task = next(t for t in lite["task"] if t["name"] == "🏰 邺城之战V3")
        target = task["pipeline_override"]["邺城事件-确认选择战车"]["action"]["param"]["target"]
        self.assertEqual(target, [357, 1181, 3, 3])
        self.assertEqual(report["pipeline_overrides"][0]["task"], "🏰 邺城之战V3")

    def test_ocr_quantization_is_forbidden(self):
        self.assertEqual(
            self.scope["constraints"]["ocr_model_quantization"], "forbidden"
        )


if __name__ == "__main__":
    unittest.main()
