"""选项选择要能扛住上游重排可选值。

老格式只存索引，而索引的含义由 `interface.json` 里 `cases` 的顺序决定。上游一旦
增删或重排某个选项的值，同一个数字就指向别的值：任务照常开始、照常成功，只是选错了
（真实例子：「王铜钱历练级别」索引 3 = 王庭贸易-最高，前面插一个新贸易点就变成西域贸易），
日志里完全看不出来。现在同时记名字，解析时名字优先。
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from lite import task_options_service as svc
from lite.task_overrides import build_task_override


def option_group(names: list[str]) -> dict:
    return {
        "type": "select",
        "default_case": names[0],
        "cases": [
            {
                "name": name,
                "pipeline_override": {
                    "选择": {"recognition": {"param": {"expected": name}}}
                },
            }
            for name in names
        ],
    }


class ResolveIndexTest(unittest.TestCase):
    def test_label_wins_when_cases_are_reordered(self) -> None:
        # 保存时：index 1、label「乙」
        selected = {"级别": {"index": 1, "label": "乙"}}
        # 上游把「乙」挪到最前面
        group = option_group(["乙", "甲", "丙"])
        self.assertEqual(svc.resolve_index(group, selected, "级别"), 0)

    def test_falls_back_to_index_when_label_gone(self) -> None:
        selected = {"级别": {"index": 1, "label": "已下线的值"}}
        group = option_group(["甲", "乙"])
        notes: list[str] = []
        self.assertEqual(svc.resolve_index(group, selected, "级别", note=notes.append), 1)
        self.assertEqual(len(notes), 1)
        self.assertIn("已下线的值", notes[0])

    def test_legacy_int_still_works(self) -> None:
        self.assertEqual(svc.resolve_index(option_group(["甲", "乙"]), {"级别": 1}, "级别"), 1)

    def test_legacy_out_of_range_falls_back_to_default(self) -> None:
        group = option_group(["甲", "乙"])
        group["default_case"] = "乙"
        notes: list[str] = []
        self.assertEqual(
            svc.resolve_index(group, {"级别": 9}, "级别", note=notes.append), 1
        )
        self.assertEqual(len(notes), 1)

    def test_missing_selection_uses_default_case(self) -> None:
        group = option_group(["甲", "乙"])
        group["default_case"] = "乙"
        self.assertEqual(svc.resolve_index(group, {}, "级别"), 1)


class ApplyChangeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.interface = {
            "option": {"级别": option_group(["甲", "乙", "丙"])},
            "task": [{"name": "T", "entry": "e", "option": ["级别"]}],
        }

    def test_stores_index_and_label(self) -> None:
        selection, _inputs = svc.apply_change(
            self.interface, {"task": "T", "group": "级别", "index": 2}, {}, {}
        )
        self.assertEqual(selection["T"]["级别"], {"index": 2, "label": "丙"})

    def test_reordered_resource_resolves_to_the_same_value(self) -> None:
        selection, _ = svc.apply_change(
            self.interface, {"task": "T", "group": "级别", "index": 1}, {}, {}
        )
        # 上游把「乙」挪到最后：索引 1 现在是「丙」，但名字还认得出「乙」
        reordered = {"option": {"级别": option_group(["甲", "丙", "乙"])}}
        self.assertEqual(
            svc.resolve_index(reordered["option"]["级别"], selection["T"], "级别"), 2
        )


class BackfillTest(unittest.TestCase):
    def test_fills_labels_for_legacy_entries(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "task-options.json"
            path.write_text(
                json.dumps({"T": {"级别": 1, "文本": {"输入": "x"}}}), encoding="utf-8"
            )
            interface = {
                "option": {
                    "级别": option_group(["甲", "乙"]),
                    "文本": {"type": "input", "inputs": [{"name": "输入"}]},
                }
            }
            filled = svc.backfill_labels(interface, path)
            self.assertEqual(filled, 1)
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["T"]["级别"], {"index": 1, "label": "乙"})
            # input 类选项不动
            self.assertEqual(data["T"]["文本"], {"输入": "x"})

    def test_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "task-options.json"
            path.write_text(json.dumps({"T": {"级别": 0}}), encoding="utf-8")
            interface = {"option": {"级别": option_group(["甲", "乙"])}}
            self.assertEqual(svc.backfill_labels(interface, path), 1)
            self.assertEqual(svc.backfill_labels(interface, path), 0)


class OverrideUsesLabelTest(unittest.TestCase):
    def test_override_follows_label_not_stale_index(self) -> None:
        interface = {
            "option": {"级别": option_group(["甲", "乙"])},
            "task": [{"name": "T", "entry": "e", "option": ["级别"]}],
        }
        # 保存时选的是「甲」(index 0)，上游把「甲」挪到了 index 1
        interface["option"]["级别"] = option_group(["乙", "甲"])
        selected = {"级别": {"index": 0, "label": "甲"}}
        notes: list[str] = []

        override = build_task_override(interface, interface["task"][0], selected, {}, notes)

        self.assertEqual(override["选择"]["recognition"]["param"]["expected"], "甲")
        self.assertEqual(notes, [])

    def test_override_reports_when_label_is_gone(self) -> None:
        interface = {
            "option": {"级别": option_group(["甲", "乙"])},
            "task": [{"name": "T", "entry": "e", "option": ["级别"]}],
        }
        selected = {"级别": {"index": 1, "label": "已下线"}}
        notes: list[str] = []

        build_task_override(interface, interface["task"][0], selected, {}, notes)

        self.assertEqual(len(notes), 1)
        self.assertIn("已下线", notes[0])


if __name__ == "__main__":
    unittest.main()
