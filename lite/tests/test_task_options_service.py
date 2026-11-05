from __future__ import annotations

import json
import unittest
from pathlib import Path

from lite.task_options_service import (
    OptionError,
    apply_change,
    describe_tasks,
    load_inputs,
    load_selection,
    resolve_index,
)
from lite.task_overrides import build_task_override


ROOT = Path(__file__).resolve().parents[2]


def load_interface() -> dict:
    return json.loads(
        (ROOT / "build" / "generated" / "interface.json").read_text(encoding="utf-8")
    )


class DescribeTest(unittest.TestCase):
    def setUp(self):
        self.interface = load_interface()
        self.selection = load_selection()
        self.inputs = load_inputs()

    def test_training_levels_are_exposed(self):
        tasks = describe_tasks(
            self.interface,
            ["💎 修为历练"],
            self.selection,
            self.inputs,
        )
        self.assertEqual(len(tasks), 1)
        groups = {group["group"]: group for group in tasks[0]["groups"]}
        self.assertIn("修为历练类别", groups)
        self.assertIn("修为历练级别", groups)
        self.assertIn("修为历练次数", groups)
        levels = groups["修为历练级别"]
        self.assertEqual(levels["type"], "select")
        self.assertIn("八", levels["cases"])
        # 用解析函数比对，而不是直接拿存储值当下标：
        # 存储格式可能从「纯索引」升级为「索引 + 名称」。
        self.assertEqual(
            levels["selected"],
            resolve_index(
                self.interface["option"]["修为历练级别"],
                self.selection["💎 修为历练"],
                "修为历练级别",
            ),
        )

    def test_child_option_follows_parent_case(self):
        task_name = "🚀 启动游戏"
        group_name = "使用指定账号登录"
        cases = self.interface["option"][group_name]["cases"]
        yes = next(i for i, case in enumerate(cases) if case["name"] == "Yes")

        before = describe_tasks(
            self.interface, [task_name], self.selection, self.inputs
        )[0]["groups"]
        self.assertNotIn("账号前3位", [group["group"] for group in before])

        selection, inputs = apply_change(
            self.interface,
            {"task": task_name, "group": group_name, "index": yes},
            dict(self.selection),
            dict(self.inputs),
        )
        after = describe_tasks(self.interface, [task_name], selection, inputs)[0][
            "groups"
        ]
        child = next(group for group in after if group["group"] == "账号前3位")
        self.assertEqual(child["type"], "input")
        self.assertEqual(child["depth"], 1)


class ValidateTest(unittest.TestCase):
    def setUp(self):
        self.interface = load_interface()
        self.selection = load_selection()
        self.inputs = load_inputs()

    def change(self, payload):
        return apply_change(
            self.interface, payload, dict(self.selection), dict(self.inputs)
        )

    def test_index_out_of_range_is_rejected(self):
        with self.assertRaises(OptionError):
            self.change({"task": "💎 修为历练", "group": "修为历练级别", "index": 99})

    def test_non_integer_index_is_rejected(self):
        with self.assertRaises(OptionError):
            self.change({"task": "💎 修为历练", "group": "修为历练级别", "index": "2"})

    def test_group_from_other_task_is_rejected(self):
        with self.assertRaises(OptionError):
            self.change({"task": "💎 修为历练", "group": "观星方式", "index": 0})

    def test_unknown_task_is_rejected(self):
        with self.assertRaises(OptionError):
            self.change({"task": "不存在的任务", "group": "观星方式", "index": 0})

    def test_input_value_is_saved(self):
        field = self.interface["option"]["账号前3位"]["inputs"][0]["name"]
        selection, inputs = self.change(
            {
                "task": "🚀 启动游戏",
                "group": "账号前3位",
                "inputs": {field: "abc"},
            }
        )
        self.assertEqual(inputs["🚀 启动游戏"]["账号前3位"][field], "abc")


class InputOverrideTest(unittest.TestCase):
    def test_input_value_replaces_placeholder(self):
        interface = load_interface()
        task = next(
            item for item in interface["task"] if item["name"] == "🎲 爱乐之村"
        )
        override = build_task_override(
            interface,
            task,
            {},
            {"小骰子识别精度": {"小骰子识别精度": "0.92"}},
        )
        threshold = override["大富翁-丢小骰子"]["recognition"]["param"]["threshold"]
        self.assertEqual(threshold, "0.92")


if __name__ == "__main__":
    unittest.main()
