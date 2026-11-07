"""Stall watchdog: no node finished for STALL_SECONDS ⇒ stop the task.

Without it a task stuck behind an unrecognised dialog (the 气力值回复 box was the
real case) sat there until the 30-minute timeout. The watchdog turns that into
a 150-second failure, and lets the stamina check end it cleanly when that is
what actually happened.
"""

from __future__ import annotations

import tempfile
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

    def test_reason_reports_actual_stall_duration(self) -> None:
        # 阈值是 150 秒，但真正卡了 400 秒要如实写出来。
        import time as _time

        service = make_service()
        service._last_node_time = _time.monotonic() - 400
        outage = service._classify_result(
            NoDialogSession(), "🚀 启动游戏", {"stalled": True}, 400.0
        )
        self.assertIn("40", outage["reason"])  # 400 ± 取整
        self.assertNotIn("150", outage["reason"])

    def test_stalled_with_stamina_dialog_ends_cleanly(self) -> None:
        service = make_service()
        session = StaminaSession()
        outcome = service._classify_result(
            session, "📜 鸢报四连 - 日常专用", {"stalled": True}, 150.0
        )
        # 2026-11-07 起：体力耗尽不再是"成功"，而是单独记「未领取到资源」。
        self.assertEqual(outcome["status"], "skipped_no_resource")
        self.assertIn("资源", outcome["reason"])
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


class LandscapeSession(NoDialogSession):
    """capture_png 写一张横屏帧——模拟器被重启、游戏没了时的真实形态。"""

    def __init__(self, size: tuple[int, int] = (1280, 720)) -> None:
        self.size = size

    def capture_png(self, path):
        from PIL import Image

        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", self.size, (20, 20, 20)).save(path)
        return True


class LandscapeAbortTest(unittest.TestCase):
    """横屏 + 完全无进展 ⇒ 游戏没在跑，整轮直接中止。

    否则日常链会把 150 秒乘以任务数：8 项约 20 分钟，全都花在等一个不会
    出现的界面上。
    """

    def _classify(self, size: tuple[int, int]):
        service = make_service()
        self.addCleanup(lambda: None)
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        service.project_root = root
        service._project_root = root
        service._last_screenshot = root / "last.png"
        outcome = service._classify_result(
            LandscapeSession(size), "🚀 启动游戏", {"stalled": True}, 150.0
        )
        return service, outcome

    def test_landscape_stall_aborts(self) -> None:
        service, outcome = self._classify((1280, 720))
        self.assertEqual(outcome["status"], "failed")
        self.assertTrue(outcome.get("aborted"), "横屏时应当中止整轮")
        messages = [line["message"] for line in service._logs]
        self.assertTrue(any("横屏" in text for text in messages), messages)

    def test_portrait_stall_does_not_abort(self) -> None:
        service, outcome = self._classify((720, 1280))
        self.assertEqual(outcome["status"], "failed")
        self.assertFalse(outcome.get("aborted"), "竖屏时只是普通失败，应继续下一项")


class BackToMainTest(unittest.TestCase):
    """体力耗尽算成功，但界面可能停在活动页/结算页，下一项就会一个节点都识别不到。

    2026-11-05 实测：鸢报「体力耗尽」结束后，日常收尾在密探特训页上耗满了 150 秒
    看门狗窗口。收尾从主界面重跑 150 秒即成功，说明只要先退回主界面就好。
    """

    class _Session(NoDialogSession):
        def __init__(self, already_main: bool) -> None:
            self._main = already_main
            self.backs = 0

        def is_main_screen(self) -> bool:
            return self._main

        def press_back(self) -> bool:
            self.backs += 1
            self._main = True
            return True

    def test_leaves_activity_page(self) -> None:
        service = make_service()
        session = self._Session(already_main=False)
        service._back_to_main(session, "📜 鸢报四连")
        self.assertEqual(session.backs, 1)
        messages = [line["message"] for line in service._logs]
        self.assertTrue(any("退回主界面" in text for text in messages), messages)

    def test_does_nothing_on_main_screen(self) -> None:
        service = make_service()
        session = self._Session(already_main=True)
        service._back_to_main(session, "📜 鸢报四连")
        self.assertEqual(session.backs, 0, "已在主界面时不能乱按返回键")


if __name__ == "__main__":
    unittest.main()
