"""Tests for the node-repeat guard used by the runner's dead-loop detection."""

from __future__ import annotations

import unittest

from lite.guards import NODE_REPEAT_BUDGET, NodeRepeatGuard


class NodeRepeatGuardTest(unittest.TestCase):
    def test_default_budget_is_documented_value(self) -> None:
        self.assertEqual(NODE_REPEAT_BUDGET, 120)

    def test_trips_exactly_once_when_budget_is_exceeded(self) -> None:
        guard = NodeRepeatGuard(budget=2)
        self.assertFalse(guard.hit("node"))
        self.assertFalse(guard.hit("node"))
        self.assertTrue(guard.hit("node"))  # 第 budget+1 次才算卡死
        self.assertEqual(guard.tripped_node, "node")
        # 已经触发后不再重复报告，调用方只处理一次
        self.assertFalse(guard.hit("node"))
        self.assertFalse(guard.hit("other"))

    def test_nodes_are_counted_independently(self) -> None:
        guard = NodeRepeatGuard(budget=2)
        guard.hit("a")
        guard.hit("a")
        guard.hit("b")
        self.assertEqual(guard.tripped_node, "")
        self.assertTrue(guard.hit("a"))
        self.assertEqual(guard.tripped_node, "a")

    def test_zero_budget_trips_on_first_hit(self) -> None:
        guard = NodeRepeatGuard(budget=0)
        self.assertTrue(guard.hit("first"))


if __name__ == "__main__":
    unittest.main()
