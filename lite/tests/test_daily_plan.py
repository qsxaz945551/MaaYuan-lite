from __future__ import annotations

import unittest
from datetime import datetime
from pathlib import Path

from lite.daily_plan import build_plan, load_profile

MORNING = datetime(2026, 11, 7, 9, 0)
AFTERNOON = datetime(2026, 11, 7, 16, 0)
MIDNIGHT = datetime(2026, 11, 8, 0, 30)


class DailyPlanTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.profile = load_profile(Path(__file__).resolve().parents[2] / "lite" / "daily-profile.json")

    def test_training_choice_is_exclusive(self):
        options = {
            "修为": "💎 修为历练",
            "铜钱": "💲 铜钱历练",
            "经验": "⚔️ 经验历练",
        }
        for short, full in options.items():
            with self.subTest(short=short):
                plan = build_plan(self.profile, training=short, now=MORNING)
                names = [task["name"] for task in plan["tasks"]]
                self.assertIn(full, names)
                others = set(options.values()) - {full}
                self.assertTrue(others.isdisjoint(names))

    def test_dungeon_slot_and_skip(self):
        plan = build_plan(self.profile, training="修为", include_seasonal=True, now=MORNING)
        names = [task["name"] for task in plan["tasks"]]
        self.assertLess(names.index("🗡 白鹄扫荡"), names.index("🗡 地宫助手"))
        self.assertLess(names.index("🗡 地宫助手"), names.index("🔶 日常收尾"))

        skipped_plan = build_plan(
            self.profile, training="修为", include_seasonal=False, now=MORNING
        )
        skipped_names = [task["name"] for task in skipped_plan["tasks"]]
        self.assertNotIn("🗡 地宫助手", skipped_names)
        reasons = {item["name"]: item["reason"] for item in skipped_plan["skipped"]}
        self.assertEqual(reasons["🗡 地宫助手"], "seasonal_daily_disabled")

    def test_default_plan_has_no_duplicates(self):
        plan = build_plan(self.profile, now=MORNING)
        names = [task["name"] for task in plan["tasks"]]
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(plan["count"], 9)
        self.assertEqual(names[-1], "🔶 日常收尾")
        self.assertEqual(names[-2], "🗡 地宫助手")
        # 鸢报提到历练之前：先把不花体力的收掉，再按剩余体力决定历练档位。
        self.assertLess(
            names.index("📜 鸢报四连 - 日常专用"), names.index("💎 修为历练")
        )

    def test_seasonal_daily_is_off_by_default(self):
        seasonal = [
            item
            for item in self.profile["daily_order"]
            if item["type"] == "optional_task" and item.get("group") == "seasonal_daily"
        ]
        self.assertEqual(len(seasonal), 1)
        self.assertFalse(seasonal[0]["default_enabled"])
        self.assertIn("probe", seasonal[0])

        # 每日进膳是另一种可选：按时间窗自动开关，不需要 probe
        timed = [
            item
            for item in self.profile["daily_order"]
            if item["type"] == "optional_task" and item.get("group") == "time_window"
        ]
        self.assertEqual(len(timed), 1)
        self.assertEqual(timed[0]["activity"]["start_hour"], 16)
        self.assertEqual(timed[0]["activity"]["end_hour"], 24)

    def test_lunch_task_is_time_gated(self):
        """每日进膳 16:00 开放、24:00 结束，由本地时间自动决定是否入链。"""
        def names_at(moment):
            plan = build_plan(self.profile, training="修为", now=moment)
            return [task["name"] for task in plan["tasks"]], plan

        morning, _ = names_at(MORNING)
        self.assertNotIn("🍚 每日进膳", morning)

        afternoon, plan = names_at(AFTERNOON)
        self.assertIn("🍚 每日进膳", afternoon)
        # 位置固定在「领月卡福利」之后
        self.assertEqual(
            afternoon.index("🍚 每日进膳"),
            afternoon.index("💰 领月卡福利") + 1,
        )

        midnight, _ = names_at(MIDNIGHT)
        self.assertNotIn("🍚 每日进膳", midnight)

    def test_closed_window_reports_reason(self):
        plan = build_plan(self.profile, training="修为", now=MORNING)
        reasons = {item["name"]: item["reason"] for item in plan["skipped"]}
        self.assertEqual(reasons.get("🍚 每日进膳"), "time_window_closed")

    def test_probe_and_budget_are_forwarded(self):
        plan = build_plan(self.profile, training="修为", include_seasonal=True, now=MORNING)
        dungeon = next(
            task for task in plan["tasks"] if task["name"] == "🗡 地宫助手"
        )
        self.assertIn("probe", dungeon)
        self.assertTrue(dungeon["probe"]["checks"])
        self.assertEqual(dungeon["retries"], 0)
        self.assertLessEqual(dungeon["timeout_sec"], 1800)


if __name__ == "__main__":
    unittest.main()
