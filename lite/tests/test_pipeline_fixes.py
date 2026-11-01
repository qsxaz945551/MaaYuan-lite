from __future__ import annotations

import unittest

from lite.pipeline_fixes import apply_pipeline_fixes


class PipelineFixesTest(unittest.TestCase):
    def test_6_24_checks_stamina_after_start(self):
        override = apply_pipeline_fixes("start_6-24", {})
        self.assertIn("检测体力回复框", override["开始行动"]["next"])
        self.assertEqual(override["开始行动"]["next"][0], "检测体力回复框")
        self.assertEqual(override["6-24事件选择"]["on_error"][0], "检测体力回复框")

    def test_stamina_text_covers_real_dialog(self):
        override = apply_pipeline_fixes("start_6-24", {})
        expected = override["检测体力回复框"]["recognition"]["param"]["expected"]
        self.assertIn("体力回复", expected)
        self.assertIn("用道具回复", expected)
        self.assertIn("用日金市回复", expected)

    def test_other_entries_are_untouched(self):
        override = {"某个节点": {"pre_delay": 100}}
        self.assertIs(apply_pipeline_fixes("start_每日", override), override)

    def test_user_override_is_preserved(self):
        merged = apply_pipeline_fixes("start_6-24", {"开始行动": {"pre_delay": 300}})
        self.assertEqual(merged["开始行动"]["pre_delay"], 300)
        self.assertIn("检测体力回复框", merged["开始行动"]["next"])


if __name__ == "__main__":
    unittest.main()
