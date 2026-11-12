from __future__ import annotations

import unittest
from pathlib import Path

from lite.pipeline_fixes import (
    ACTIVITY_TITLE_ROI,
    ACTIVITY_TITLE_TEMPLATE,
    ACTIVITY_TITLE_THRESHOLD,
    SPECIAL_TRAINING_TEMPLATE,
    SPECIAL_TRAINING_THRESHOLD,
    apply_pipeline_fixes,
)

ROOT = Path(__file__).resolve().parents[2]


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


class ActivityPageTest(unittest.TestCase):
    """活动页判页修的是「OCR 读不出书法体标题 → 退出活动页 → 死循环」。"""

    def test_page_is_detected_by_training_card(self):
        override = apply_pipeline_fixes("日常收尾启动", {})
        recognition = override["已在界面-活动"]["recognition"]

        self.assertEqual(recognition["type"], "TemplateMatch")
        self.assertEqual(
            recognition["param"]["template"], SPECIAL_TRAINING_TEMPLATE
        )

    def test_page_check_covers_the_whole_card_area(self):
        """卡片在活动页里是纵向滚动的，ROI 必须覆盖整片可滚动区域。"""
        override = apply_pipeline_fixes("日常收尾启动", {})
        roi = override["已在界面-活动"]["recognition"]["param"]["roi"]

        self.assertLessEqual(roi[0], 10)
        self.assertGreaterEqual(roi[2], 700)
        self.assertGreaterEqual(roi[3], 800)

    def test_card_threshold_has_margin(self):
        """实测命中分 0.810，阈值必须留出余量而不是卡在 0.8。"""
        override = apply_pipeline_fixes("日常收尾启动", {})

        self.assertEqual(
            override["进入密探特训页面"]["recognition"]["param"]["threshold"],
            SPECIAL_TRAINING_THRESHOLD,
        )
        self.assertLess(SPECIAL_TRAINING_THRESHOLD, 0.8)

    def test_scroll_branch_uses_the_title_template(self):
        """卡片在折叠线下方时要靠「向下滑」，而这条分支原来用 OCR 认书法体。"""
        override = apply_pipeline_fixes("日常收尾启动", {})
        recognition = override["已在界面-活动-向下滑"]["recognition"]

        self.assertEqual(recognition["type"], "TemplateMatch")
        self.assertEqual(recognition["param"]["template"], ACTIVITY_TITLE_TEMPLATE)
        self.assertEqual(recognition["param"]["threshold"], ACTIVITY_TITLE_THRESHOLD)

    def test_enter_activity_page_drops_the_exit_fallback(self):
        """活动下线后 `进入界面-活动` 会与 `退出各类popups` 互相震荡，必须断开。

        2026-11-12：卡面 0.55（阈值 0.72）匹配不上 → 判页全失败 →
        `退出各类popups` 命中 `返回主界面` 把界面退出去 → `[JumpBack]` 回来重试 →
        该节点跑了 121 次、收尾 790.9 s 后判失败。
        """
        override = apply_pipeline_fixes("日常收尾启动", {})
        next_list = override["进入界面-活动"]["next"]

        self.assertNotIn("[JumpBack]退出各类popups", next_list)
        self.assertNotIn("退出各类popups", next_list)
        # 找入口的两条必须留着，活动在线时照常导航
        self.assertIn("已在界面-活动", next_list)
        self.assertIn("[JumpBack]找到入口-活动", next_list)
        self.assertIn("[JumpBack]找到入口-活动2", next_list)
        # 只改跳转，不动识别
        self.assertEqual(set(override["进入界面-活动"]), {"next"})

    def test_exit_popups_keeps_its_return_nodes(self):
        """`退出各类popups` 本身不能动：心纸君/密探/名册都靠它退出再进。"""
        override = apply_pipeline_fixes("日常收尾启动", {})
        self.assertNotIn("退出各类popups", override)

    def test_special_training_never_jumpbacks_into_activity(self):
        """`[JumpBack]进入界面-活动` 失败会把整个节点从头重跑，形成死循环。

        2026-11-12 08:02 / 08:07 两次实测：加了 `stop` 也轮不到，因为控制权
        被交回节点开头重新遍历。必须改成不带 JumpBack 的普通项。
        """
        override = apply_pipeline_fixes("日常收尾启动", {})
        next_list = override["领取密探特训奖励启动"]["next"]

        self.assertNotIn("[JumpBack]进入界面-活动", next_list)
        self.assertIn("进入界面-活动", next_list)
        self.assertEqual(next_list[-1], "stop")
        # 导航成功后还要再识别一次卡片
        self.assertEqual(next_list.count("进入密探特训页面"), 2)

    def test_scroll_branch_keeps_the_upstream_swipe(self):
        """只换识别，滑动动作由上游保留（override 里不该出现 action）。"""
        override = apply_pipeline_fixes("日常收尾启动", {})
        self.assertNotIn("action", override["已在界面-活动-向下滑"])

    def test_title_roi_covers_the_crop(self):
        """模板是从 ROI 里裁的：ROI 必须能容纳它，否则永远匹配不上。"""
        from PIL import Image

        path = Path(ROOT / "assets" / "resource" / "base" / "image" / ACTIVITY_TITLE_TEMPLATE)
        self.assertTrue(path.is_file(), "模板图不在资源目录里")
        width, height = Image.open(path).size
        self.assertLessEqual(width, ACTIVITY_TITLE_ROI[2])
        self.assertLessEqual(height, ACTIVITY_TITLE_ROI[3])


class IrReportBatchCollectTest(unittest.TestCase):
    """鸢报四连：批量收集要等倒计时结束，且四分支跑完应正常成功。"""

    ENTRY = "start_日常鸢报启动"

    def test_confirm_batch_enters_poll_loop(self):
        override = apply_pipeline_fixes(self.ENTRY, {})
        self.assertEqual(
            override["确定批量收集小道消息"]["next"], ["等待小道消息收集完成"]
        )

    def test_poll_loop_waits_before_giving_up(self):
        override = apply_pipeline_fixes(self.ENTRY, {})
        next_list = override["等待小道消息收集完成"]["next"]

        self.assertEqual(next_list[0], "一键收取_小道消息")
        self.assertIn("[JumpBack]小道消息收集中", next_list)
        # 收集中的等待必须排在「不可用」兜底之前，否则又会提前结束分支。
        self.assertLess(
            next_list.index("[JumpBack]小道消息收集中"),
            next_list.index("识别不可用的一键收取"),
        )

    def test_entry_ends_with_success_sink(self):
        override = apply_pipeline_fixes(self.ENTRY, {})
        next_list = override[self.ENTRY]["next"]

        self.assertEqual(next_list[-1], "end_鸢报四连完成")
        self.assertEqual(override["end_鸢报四连完成"]["next"], [])
        self.assertEqual(
            override["end_鸢报四连完成"]["recognition"]["type"], "DirectHit"
        )

    def test_branches_keep_their_order(self):
        override = apply_pipeline_fixes(self.ENTRY, {})
        next_list = override[self.ENTRY]["next"]

        self.assertEqual(next_list[0], "[JumpBack]start_突发情况启动")
        self.assertEqual(next_list[3], "[JumpBack]start_小道消息")


if __name__ == "__main__":
    unittest.main()
