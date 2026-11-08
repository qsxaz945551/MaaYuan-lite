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

    def test_no_limit_semantics_survive(self) -> None:
        """表里可以写 None 表示"不设上限"，这条语义不能丢。"""
        from lite import run_service

        run_service.DEFAULT_TIMEOUTS["测试无限任务"] = None
        try:
            self.assertIsNone(timeout_for("测试无限任务"))
        finally:
            del run_service.DEFAULT_TIMEOUTS["测试无限任务"]

    def test_unknown_task_falls_back(self) -> None:
        self.assertEqual(timeout_for("上游以后加的新任务"), DEFAULT_TASK_TIMEOUT)

    def test_override_wins(self) -> None:
        self.assertEqual(timeout_for("🚀 启动游戏", 60), 60)

    def test_override_none_means_use_table(self) -> None:
        # The API passes None when the caller did not ask for a specific limit.
        self.assertEqual(timeout_for("💲 铜钱历练", None), 1200)

    def test_override_applies_to_table_task(self) -> None:
        self.assertEqual(timeout_for("🔮 观星", 600), 600)


if __name__ == "__main__":
    unittest.main()
