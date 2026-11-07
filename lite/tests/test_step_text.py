from __future__ import annotations

import unittest

from lite.step_text import focus_text


class FocusTextTest(unittest.TestCase):
    def test_plain_string_is_used_as_is(self):
        self.assertEqual(focus_text("开始领取密探特训奖励"), "开始领取密探特训奖励")

    def test_none_and_empty_are_ignored(self):
        for value in (None, "", "   ", {}, [], 0):
            self.assertIsNone(focus_text(value), value)

    def test_object_form_reads_content(self):
        value = {"content": "开始花灯绘", "display": ["log", "toast"]}
        self.assertEqual(focus_text(value), "开始花灯绘")

    def test_legacy_start_wins_over_toast(self):
        # daily/special_training_reward.json 里就是这个形状。
        value = {"start": "已领取密探特训奖励", "toast": "已领取密探特训奖励"}
        self.assertEqual(focus_text(value), "已领取密探特训奖励")

    def test_message_keyed_form_prefers_action_starting(self):
        value = {
            "Node.Action.Succeeded": "搞定了",
            "Node.Action.Starting": "开始执行",
        }
        self.assertEqual(focus_text(value), "开始执行")

    def test_failure_message_is_not_shown_as_current_step(self):
        value = {
            "Node.Action.Failed": "执行失败，请检查环境",
            "Node.Recognition.Failed": "没认出来",
        }
        self.assertIsNone(focus_text(value))

    def test_display_key_alone_does_not_become_text(self):
        self.assertIsNone(focus_text({"display": "toast"}))

    def test_nested_object_inside_message_key(self):
        value = {"Node.Action.Starting": {"content": "进入活动页", "display": "log"}}
        self.assertEqual(focus_text(value), "进入活动页")

    def test_name_placeholder_is_substituted(self):
        value = {"Node.Action.Starting": "{name} 开始执行，任务 ID: {task_id}"}
        self.assertEqual(
            focus_text(value, "领取密探特训奖励启动"),
            "领取密探特训奖励启动 开始执行，任务 ID: {task_id}",
        )

    def test_unparsed_json_string_is_decoded(self):
        self.assertEqual(focus_text('{"content": "开始领取"}'), "开始领取")

    def test_multiline_text_is_folded_to_one_row(self):
        self.assertEqual(focus_text("第一行\n第二行   第三行"), "第一行 第二行 第三行")


if __name__ == "__main__":
    unittest.main()
