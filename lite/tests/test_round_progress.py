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
        from types import SimpleNamespace

        from maa.event_sink import NotificationType

        seen: list[str] = []
        try:
            sink = _make_node_sink(seen.append)
        except ImportError:  # system Python without MaaFramework
            self.skipTest("maa framework not installed in this interpreter")
        # 5.6.0 delivers node events through ContextEventSink; TaskerEventSink
        # only ever received Tasker.Task.*, so this path must be exercised
        # through on_node_pipeline_node.
        sink.on_node_pipeline_node(
            None, NotificationType.Succeeded, SimpleNamespace(name="战斗结束")
        )
        sink.on_node_pipeline_node(
            None, NotificationType.Starting, SimpleNamespace(name="战斗结束")
        )
        sink.on_node_pipeline_node(
            None, NotificationType.Succeeded, SimpleNamespace(name="")
        )
        self.assertEqual(seen, ["战斗结束"])

    def test_sink_is_a_context_sink(self):
        """Guard the regression that left the watchdog without a heartbeat."""
        try:
            from maa.context import ContextEventSink

            sink = _make_node_sink(lambda _name: None)
        except ImportError:  # system Python without MaaFramework
            self.skipTest("maa framework not installed in this interpreter")
        self.assertIsInstance(sink, ContextEventSink)

    def test_sink_reports_focus_text_on_node_start(self):
        """The console step line reads ``focus``; nodes without it fall back."""
        from types import SimpleNamespace

        from maa.event_sink import NotificationType

        steps: list[tuple[str, str | None]] = []
        try:
            sink = _make_node_sink(
                lambda _name: None, None, lambda name, text: steps.append((name, text))
            )
        except ImportError:  # system Python without MaaFramework
            self.skipTest("maa framework not installed in this interpreter")

        sink.on_node_pipeline_node(
            None,
            NotificationType.Starting,
            SimpleNamespace(
                name="领取密探特训奖励启动", focus="开始领取密探特训奖励"
            ),
        )
        sink.on_node_pipeline_node(
            None, NotificationType.Starting, SimpleNamespace(name="检测点击_前往收集")
        )
        sink.on_node_pipeline_node(
            None,
            NotificationType.Starting,
            SimpleNamespace(name="选择训练任务", focus={"start": "选任务", "toast": "选任务"}),
        )
        self.assertEqual(
            steps,
            [
                ("领取密探特训奖励启动", "开始领取密探特训奖励"),
                ("检测点击_前往收集", None),
                ("选择训练任务", "选任务"),
            ],
        )


if __name__ == "__main__":
    unittest.main()
