from __future__ import annotations

import unittest
from pathlib import Path

from lite.daily_plan import build_plan, load_profile


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
                plan = build_plan(self.profile, training=short)
                names = [task["name"] for task in plan["tasks"]]
                self.assertIn(full, names)
                others = set(options.values()) - {full}
                self.assertTrue(others.isdisjoint(names))

    def test_dungeon_slot_and_skip(self):
        plan = build_plan(self.profile, training="修为", include_seasonal=True)
        names = [task["name"] for task in plan["tasks"]]
        self.assertLess(names.index("🗡 白鹄扫荡"), names.index("🗡 地宫助手"))
        self.assertLess(names.index("🗡 地宫助手"), names.index("🔶 日常收尾"))

        skipped_plan = build_plan(
            self.profile, training="修为", include_seasonal=False
        )
        skipped_names = [task["name"] for task in skipped_plan["tasks"]]
        self.assertNotIn("🗡 地宫助手", skipped_names)
        self.assertEqual(skipped_plan["skipped"][0]["reason"], "seasonal_daily_disabled")

    def test_default_plan_has_no_duplicates(self):
        plan = build_plan(self.profile)
        names = [task["name"] for task in plan["tasks"]]
        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(plan["count"], 9)
        self.assertEqual(names[-1], "🔶 日常收尾")
        self.assertEqual(names[-2], "📜 鸢报四连 - 日常专用")

    def test_seasonal_daily_is_off_by_default(self):
        items = [
            item
            for item in self.profile["daily_order"]
            if item["type"] == "optional_task"
        ]
        self.assertEqual(len(items), 1)
        self.assertFalse(items[0]["default_enabled"])
        self.assertIn("probe", items[0])

    def test_probe_and_budget_are_forwarded(self):
        plan = build_plan(self.profile, training="修为", include_seasonal=True)
        dungeon = next(
            task for task in plan["tasks"] if task["name"] == "🗡 地宫助手"
        )
        self.assertIn("probe", dungeon)
        self.assertTrue(dungeon["probe"]["checks"])
        self.assertEqual(dungeon["retries"], 0)
        self.assertLessEqual(dungeon["timeout_sec"], 1800)


if __name__ == "__main__":
    unittest.main()
