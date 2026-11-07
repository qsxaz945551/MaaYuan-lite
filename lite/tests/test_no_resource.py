"""「跑完」不等于「拿到奖励」：资源不足要单独记一笔。

用户 2026-11-07 定的口径：
  · 成功的唯一指标是任务跑完，与奖励无关；
  · 资源不足导致提前收手 → skipped_no_resource，单记、不算失败；
  · 跨日以 05:00 为界，过界作废旧记录。
"""

from __future__ import annotations

import json
import tempfile
import threading
import time
import unittest
from collections import deque
from datetime import datetime, timedelta
from pathlib import Path

from lite.run_service import RunService, day_window_start, parse_stamp

ROOT = Path(__file__).resolve().parents[2]


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
    service.project_root = Path(".")
    service._last_node_time = time.monotonic()
    service._resource_hit = False
    service._guard_event = threading.Event()
    service._guard_node = ""
    service._cancel = threading.Event()
    service._session = None
    return service


class Session:
    """最小会话桩：成功路径不会碰它的任何方法。"""


class ResourceShortTest(unittest.TestCase):
    def test_bird_food_node_marks_the_run(self) -> None:
        service = make_service()
        handler = service._make_round_handler("start_日常鸢报启动")
        handler("小道消息不吃鸟食")
        self.assertTrue(service._resource_hit)

    def test_unrelated_node_does_not_mark(self) -> None:
        service = make_service()
        handler = service._make_round_handler("start_日常鸢报启动")
        handler("一键收取_小道消息")
        self.assertFalse(service._resource_hit)

    def test_success_with_bird_food_marker_is_not_counted_as_success(self) -> None:
        service = make_service()
        service._resource_hit = True
        outcome = service._classify_result(
            Session(), "📜 鸢报四连 - 日常专用", {"success": True}, 10.0
        )
        self.assertEqual(outcome["status"], "skipped_no_resource")
        self.assertIn("未领取", outcome["reason"])

    def test_plain_success_stays_success(self) -> None:
        service = make_service()
        outcome = service._classify_result(
            Session(), "📜 鸢报四连 - 日常专用", {"success": True}, 10.0
        )
        self.assertEqual(outcome["status"], "succeeded")

    def test_non_stamina_task_is_never_flagged(self) -> None:
        # `new不吃鸟食` 也被密探特训复用（行动次数耗尽），那不是"没拿到资源"。
        service = make_service()
        service._resource_hit = True
        outcome = service._classify_result(
            Session(), "🔶 日常收尾", {"success": True}, 10.0
        )
        self.assertEqual(outcome["status"], "succeeded")

    def test_grind_task_is_exempt(self) -> None:
        # 刷到体力耗尽的任务，目标就是把资源刷干，刷干即完成。
        service = make_service()
        service._resource_hit = True
        outcome = service._classify_result(
            Session(), "🔄 6-24/7-15 刷到体力耗尽", {"success": True}, 10.0
        )
        self.assertEqual(outcome["status"], "succeeded")

    def test_skipped_is_its_own_tally_bucket(self) -> None:
        service = make_service()
        service._tasks = [
            {"status": "succeeded"},
            {"status": "skipped_no_resource"},
            {"status": "failed"},
        ]
        self.assertEqual(service._tally(), (1, 1, 1))
        service._finalize_run(aborted=False, cancelled=False, succeeded=1, failed=1, skipped=1)
        self.assertEqual(
            service._summary, {"succeeded": 1, "failed": 1, "skipped": 1}
        )
        # 有失败才算「完成但有失败」，只有未领取仍然是 completed
        service._finalize_run(aborted=False, cancelled=False, succeeded=1, failed=0, skipped=1)
        self.assertEqual(service._status, "completed")


class CancelledStillResumableTest(unittest.TestCase):
    """用户 2026-11-07：手动停止依然算未完成，要能续跑。"""

    def test_cancelled_task_keeps_resume_available(self) -> None:
        service = make_service()
        service._tasks = [{"status": "succeeded"}, {"status": "cancelled"}]
        self.assertTrue(service.can_resume())

    def test_skipped_no_resource_does_not_offer_resume(self) -> None:
        service = make_service()
        service._tasks = [{"status": "succeeded"}, {"status": "skipped_no_resource"}]
        self.assertFalse(service.can_resume())


class DayWindowTest(unittest.TestCase):
    def test_before_five_still_belongs_to_yesterday(self) -> None:
        self.assertEqual(
            day_window_start(datetime(2026, 11, 7, 4, 59)), datetime(2026, 11, 6, 5, 0)
        )

    def test_after_five_is_today(self) -> None:
        self.assertEqual(
            day_window_start(datetime(2026, 11, 7, 5, 1)), datetime(2026, 11, 7, 5, 0)
        )

    def test_exact_boundary_counts_as_today(self) -> None:
        self.assertEqual(
            day_window_start(datetime(2026, 11, 7, 5, 0)), datetime(2026, 11, 7, 5, 0)
        )

    def test_parse_stamp_rejects_junk(self) -> None:
        self.assertIsNone(parse_stamp(""))
        self.assertIsNone(parse_stamp("2026-11-07"))
        self.assertEqual(
            parse_stamp("2026-11-07 05:00:00"), datetime(2026, 11, 7, 5, 0)
        )


class LoadLastRunTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "runtime").mkdir(parents=True)
        self.config = {"runtime_root": str(ROOT)}

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def write_state(self, stamp: str | None) -> None:
        payload = {
            "status": "interrupted",
            "finishedAt": stamp or "",
            "updatedAt": stamp or "",
            "tasks": [{"name": "🔮 观星", "status": "failed"}],
            "plan": {"tasks": []},
            "summary": {},
        }
        (self.root / "runtime" / "last-run.json").write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )

    def test_today_record_is_restored(self) -> None:
        self.write_state(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        service = RunService(self.root, self.config)
        self.assertEqual(service._status, "interrupted")
        self.assertTrue(service._tasks)

    def test_yesterday_record_is_discarded(self) -> None:
        stale = day_window_start() - timedelta(hours=1)
        self.write_state(stale.strftime("%Y-%m-%d %H:%M:%S"))
        service = RunService(self.root, self.config)
        self.assertEqual(service._status, "idle")
        self.assertFalse(service._tasks)
        # 作废后顺手删掉，避免每次启动都重复告警
        self.assertFalse((self.root / "runtime" / "last-run.json").exists())

    def test_missing_timestamp_is_discarded(self) -> None:
        self.write_state(None)
        service = RunService(self.root, self.config)
        self.assertFalse(service._tasks)


if __name__ == "__main__":
    unittest.main()
