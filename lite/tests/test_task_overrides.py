from __future__ import annotations

import json
import unittest
from pathlib import Path

from lite.task_overrides import build_task_override, load_options_snapshot


ROOT = Path(__file__).resolve().parents[2]


class TaskOverrideTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.interface = json.loads(
            (ROOT / "build" / "generated" / "interface.json").read_text(encoding="utf-8")
        )
        cls.options = load_options_snapshot()

    def _task(self, name: str):
        return next(task for task in self.interface["task"] if task["name"] == name)

    def test_nested_options_are_applied(self):
        task = self._task("🏯 据点日常")
        override = build_task_override(self.interface, task, self.options[task["name"]])
        self.assertIn("派遣大礼包", override)
        self.assertFalse(override["返回主界面"]["enabled"])

    def test_switch_indices_map_to_cases(self):
        task = self._task("🔶 日常收尾")
        override = build_task_override(self.interface, task, self.options[task["name"]])
        self.assertTrue(override["领取密探特训奖励启动"]["enabled"])

    def test_pipeline_override_survives_option_merge(self):
        """任务自带 pipeline_override 时，选项合并不能把它覆盖掉。"""
        task = {
            "name": "测试任务",
            "entry": "测试入口",
            "option": ["测试开关"],
            "pipeline_override": {
                "某节点": {"action": {"type": "Click", "param": {"target": [1, 2, 3, 4]}}}
            },
        }
        interface = {
            "task": [task],
            "option": {"测试开关": {"cases": [{"name": "Yes"}, {"name": "No"}]}},
        }
        override = build_task_override(
            interface, task, {"测试开关": {"index": 0, "label": "Yes"}}
        )
        self.assertEqual(
            override["某节点"]["action"]["param"]["target"], [1, 2, 3, 4]
        )
        self.assertTrue(override)


if __name__ == "__main__":
    unittest.main()
