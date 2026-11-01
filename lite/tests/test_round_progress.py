from __future__ import annotations

import unittest

from lite.round_progress import marker_labels
from lite.session import _make_node_sink


class RoundProgressTest(unittest.TestCase):
    def test_six_two_four_counts_battles(self):
        self.assertEqual(marker_labels("start_6-24"), {"战斗结束": "战斗"})

    def test_unknown_entry_has_no_markers(self):
        self.assertEqual(marker_labels("start_每日"), {})

    def test_sink_reports_only_succeeded_nodes(self):
        seen: list[str] = []
        try:
            sink = _make_node_sink(seen.append)
        except ImportError:  # system Python without MaaFramework
            self.skipTest("maa framework not installed in this interpreter")
        sink.on_raw_notification(None, "Node.PipelineNode.Succeeded", {"name": "战斗结束"})
        sink.on_raw_notification(None, "Node.PipelineNode.Starting", {"name": "战斗结束"})
        sink.on_raw_notification(None, "Node.PipelineNode.Succeeded", {})
        self.assertEqual(seen, ["战斗结束"])


if __name__ == "__main__":
    unittest.main()
