"""`_auto_start` runs in a background thread, so a crash there used to vanish.

The settings screen offers 「启动时自动运行日常」; when the run failed the thread
died silently and the UI simply stayed idle. These tests pin the two outcomes:
success is silent, failure leaves an error line in the run log.
"""

from __future__ import annotations

import unittest
from unittest import mock

import app


class FakeService:
    def __init__(self, busy: bool = False) -> None:
        self.busy = busy
        self.calls: list[tuple] = []
        self.error: Exception | None = None

    def snapshot(self) -> dict:
        return {"busy": self.busy}

    def start_daily(self, **kwargs):
        self.calls.append(("start_daily", kwargs))
        if self.error is not None:
            raise self.error
        return True

    def note(self, message: str, level: str = "info") -> None:
        self.calls.append(("note", message, level))


class AutoStartTest(unittest.TestCase):
    def setUp(self) -> None:
        # _auto_start 内部 import time 后 sleep；测试里不需要真的等。
        self.sleep = mock.patch("time.sleep")
        self.sleep.start()

    def tearDown(self) -> None:
        self.sleep.stop()

    def test_success_runs_with_saved_preferences(self) -> None:
        service = FakeService()
        app._auto_start(
            service, {"last_training": "铜钱", "last_dungeon": True}, delay=1
        )
        call = next(item for item in service.calls if item[0] == "start_daily")
        self.assertEqual(call[1]["training"], "铜钱")
        self.assertTrue(call[1]["include_dungeon"])
        self.assertFalse([item for item in service.calls if item[0] == "note"])

    def test_failure_is_written_to_the_run_log(self) -> None:
        service = FakeService()
        service.error = RuntimeError("模拟器未就绪")
        app._auto_start(service, {"last_training": "修为"}, delay=1)
        notes = [item for item in service.calls if item[0] == "note"]
        self.assertEqual(len(notes), 1)
        self.assertIn("启动时自动运行失败", notes[0][1])
        self.assertIn("模拟器未就绪", notes[0][1])
        self.assertEqual(notes[0][2], "error")

    def test_busy_service_does_not_start_another_run(self) -> None:
        service = FakeService(busy=True)
        app._auto_start(service, {}, delay=1)
        self.assertFalse([item for item in service.calls if item[0] == "start_daily"])


if __name__ == "__main__":
    unittest.main()
