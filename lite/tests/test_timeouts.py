"""One place decides how long a task may run.

Before this, the daily chain preferred the plan item, the ad-hoc queue preferred
the table, and both fell back to a literal 1800. The rules are pinned here.
"""

from __future__ import annotations

import unittest

from lite.run_service import DEFAULT_TASK_TIMEOUT, timeout_for


class TimeoutTest(unittest.TestCase):
    def test_table_value_wins_over_default(self) -> None:
        self.assertEqual(timeout_for("🚀 启动游戏"), 300)

    def test_no_limit_task_stays_none(self) -> None:
        # 邺城 runs until stopped by hand; a number here would silently cut it off.
        self.assertIsNone(timeout_for("🏰 邺城之战V3"))

    def test_unknown_task_falls_back(self) -> None:
        self.assertEqual(timeout_for("上游以后加的新任务"), DEFAULT_TASK_TIMEOUT)

    def test_override_wins(self) -> None:
        self.assertEqual(timeout_for("🚀 启动游戏", 60), 60)

    def test_override_none_means_use_table(self) -> None:
        # The API passes None when the caller did not ask for a specific limit.
        self.assertEqual(timeout_for("💲 铜钱历练", None), 1200)

    def test_override_applies_to_no_limit_task(self) -> None:
        self.assertEqual(timeout_for("🏰 邺城之战V3", 600), 600)


if __name__ == "__main__":
    unittest.main()
