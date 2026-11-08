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

    def test_removed_tasks_stay_out(self):
        """2026-11-08 用户要求把这几项从其他任务里彻底删掉。"""
        lite, _report = apply_scope(self.interface, self.scope, self.overrides)
        names = {task["name"] for task in lite["task"]}
        self.assertNotIn("🏰 邺城之战V3", names)
        self.assertNotIn("💤 关闭游戏", names)
        self.assertNotIn("🏴 朝歌之战V2", names)

    def test_orphan_options_are_pruned(self):
        """任务删掉后，只被它引用的选项组也不该留在生成物里。"""
        lite, report = apply_scope(self.interface, self.scope, self.overrides)
        self.assertNotIn("邺城-刷哪层", lite["option"])
        self.assertNotIn("选择要购买的商品", lite["option"])
        self.assertFalse([key for key in lite["option"] if key.startswith("朝歌-")])
        self.assertGreater(report["pruned_option_count"], 0)
        # 保留任务的选项必须还在
        self.assertIn("修为历练级别", lite["option"])

    def test_no_zhaoge_left_in_lite_config(self):
        """2026-11-08 精简：朝歌相关的默认配置、隐藏项也不能留。"""
        for relative in (
            "lite/task-options.json",
            "lite/daily-profile.json",
            "runtime/task-options.json",
        ):
            text = (ROOT / relative).read_text(encoding="utf-8")
            self.assertNotIn("朝歌", text, relative)

    def test_ocr_quantization_is_forbidden(self):
        self.assertEqual(
            self.scope["constraints"]["ocr_model_quantization"], "forbidden"
        )


if __name__ == "__main__":
    unittest.main()
