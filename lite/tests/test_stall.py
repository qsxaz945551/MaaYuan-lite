"""Stall watchdog: no node finished for STALL_SECONDS ⇒ stop the task.

Without it a task stuck behind an unrecognised dialog (the 气力值回复 box was the
real case) sat there until the 30-minute timeout. The watchdog turns that into
a 150-second failure, and lets the stamina check end it cleanly when that is
what actually happened.
"""

from __future__ import annotations

import threading
import time
import unittest
from collections import deque
from pathlib import Path
from unittest import mock

from lite import run_service
from lite.run_service import STALL_SECONDS, RunService


def make_service() -> RunService:
    service = RunService.__new__(RunService)
    service._lock = threading.RLock()
    service._status = "running"
    service._summary = {}
    service._current_task = ""
    service._tasks = []
    service._logs = deque(maxlen=50)
    service._log_seq = 0
    service._log_path = None
    service._project_root = Path(".")
    service.project_root = Path(".")
    service._last_node_time = time.monotonic()
    # 失败路径会经过护栏与取消判定，补齐这两个事件对象。
    service._guard_event = threading.Event()
    service._guard_node = ""
    service._cancel = threading.Event()
    service._session = None
    service._single = None
    return service


class NoDialogSession:
    """Nothing on screen the recovery paths recognise."""

    def probe(self, *_args, **_kwargs):
        return False

    def tap(self, *_args):
        return True

    def press_back(self):
        return True

    def capture_png(self, _path):
        return None

    def has_stamina_dialog(self):
        return False


class StaminaSession(NoDialogSession):
    def __init__(self) -> None:
        self.taps: list[tuple[int, int]] = []

    def has_stamina_dialog(self):
        return True

    def tap(self, x, y):
        self.taps.append((x, y))
        return True


class StallThresholdTest(unittest.TestCase):
    def test_not_stalled_immediately(self) -> None:
        self.assertFalse(make_service()._stalled())

    def test_stalled_past_threshold(self) -> None:
        service = make_service()
        service._last_node_time = time.monotonic() - (STALL_SECONDS + 1)
        self.assertTrue(service._stalled())

    def test_heartbeat_resets_timer(self) -> None:
        service = make_service()
        service._last_node_time = time.monotonic() - (STALL_SECONDS + 1)
        handler = service._make_round_handler("any-entry")
        handler("不是轮次标记节点")  # 无 marker 的任务也要心跳
        self.assertFalse(service._stalled())

    def test_marker_less_task_still_returns_handler(self) -> None:
        # 曾经对没有轮次标记的任务返回 None，看门狗因此完全失明。
        self.assertIsNotNone(make_service()._make_round_handler("no-markers"))


class StallClassificationTest(unittest.TestCase):
    def setUp(self) -> None:
        self._sleep = run_service.time.sleep
        run_service.time.sleep = lambda _s: None

    def tearDown(self) -> None:
        run_service.time.sleep = self._sleep

    def test_stalled_without_dialog_is_failed(self) -> None:
        service = make_service()
        outage = service._classify_result(
            NoDialogSession(), "🚀 启动游戏", {"stalled": True}, 150.0
        )
        self.assertEqual(outage["status"], "failed")
        self.assertIn("无响应", outage["reason"])

    def test_stalled_with_stamina_dialog_ends_cleanly(self) -> None:
        service = make_service()
        session = StaminaSession()
        outcome = service._classify_result(
            session, "📜 鸢报四连 - 日常专用", {"stalled": True}, 150.0
        )
        self.assertEqual(outcome["status"], "succeeded")
        self.assertIn("体力", outcome["reason"])
        # 对话框必须被关掉，否则它会挡住后面每一项任务
        self.assertEqual(session.taps, [run_service.STAMINA_DIALOG_CLOSE])

    def test_stalled_on_non_stamina_task_ignores_dialog(self) -> None:
        service = make_service()
        session = StaminaSession()
        outcome = service._classify_result(
            session, "💰 领月卡福利", {"stalled": True}, 150.0
        )
        self.assertEqual(outcome["status"], "failed")
        self.assertEqual(session.taps, [])


if __name__ == "__main__":
    unittest.main()
