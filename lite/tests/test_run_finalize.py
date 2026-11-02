"""Terminal status and task-field writes.

These two paths used to be duplicated between the daily chain and the ad-hoc
queue. The cases here pin the decision table so the two cannot drift again:
a stopped run must never be reported as an error, and a run with one timeout
must never be reported as clean.
"""

from __future__ import annotations

import threading
import unittest
from collections import deque

from lite.run_service import RunService


def make_service(tasks: list[dict] | None = None) -> RunService:
    service = RunService.__new__(RunService)
    service._lock = threading.RLock()
    service._status = "running"
    service._summary = {}
    service._current_task = "工作中"
    service._tasks = tasks if tasks is not None else []
    service._logs = deque(maxlen=50)
    service._log_seq = 0
    return service


class FinalizeTest(unittest.TestCase):
    def test_aborted_is_error(self) -> None:
        service = make_service()
        status = service._finalize_run(
            aborted=True, cancelled=False, succeeded=2, failed=1
        )
        self.assertEqual(status, "error")
        self.assertEqual(service._summary, {"succeeded": 2, "failed": 1})

    def test_cancelled_is_not_error(self) -> None:
        # Stop pressed by the user must not look like a failure.
        service = make_service()
        status = service._finalize_run(
            aborted=False, cancelled=True, succeeded=3, failed=0
        )
        self.assertEqual(status, "cancelled")

    def test_failures_mark_completed_with_errors(self) -> None:
        service = make_service()
        status = service._finalize_run(
            aborted=False, cancelled=False, succeeded=6, failed=2
        )
        self.assertEqual(status, "completed_with_errors")

    def test_clean_run(self) -> None:
        service = make_service()
        status = service._finalize_run(
            aborted=False, cancelled=False, succeeded=8, failed=0
        )
        self.assertEqual(status, "completed")

    def test_aborted_wins_over_cancelled(self) -> None:
        service = make_service()
        status = service._finalize_run(
            aborted=True, cancelled=True, succeeded=0, failed=0
        )
        self.assertEqual(status, "error")


class TallyTest(unittest.TestCase):
    def test_counts_only_terminal_states(self) -> None:
        service = make_service(
            [
                {"status": "succeeded"},
                {"status": "succeeded"},
                {"status": "failed"},
                {"status": "timed_out"},
                {"status": "skipped"},
                {"status": "pending"},
                {"status": "running"},
            ]
        )
        self.assertEqual(service._tally(), (2, 2))

    def test_empty(self) -> None:
        self.assertEqual(make_service()._tally(), (0, 0))


class UpdateTaskTest(unittest.TestCase):
    def test_writes_all_fields_at_once(self) -> None:
        service = make_service([{"status": "running", "duration": 0, "attempts": 0}])
        service._update_task(0, status="succeeded", duration=12.5, attempts=2)
        self.assertEqual(
            service._tasks[0],
            {"status": "succeeded", "duration": 12.5, "attempts": 2},
        )

    def test_out_of_range_is_ignored(self) -> None:
        service = make_service([])
        service._update_task(3, status="failed")  # must not raise
        self.assertEqual(service._tasks, [])


class UpdateRunTest(unittest.TestCase):
    def test_none_leaves_field_alone(self) -> None:
        service = make_service()
        service._update_run(status="error")
        self.assertEqual(service._status, "error")
        self.assertEqual(service._current_task, "工作中")

    def test_sets_all_three(self) -> None:
        service = make_service()
        service._update_run(
            status="completed", current_task="", summary={"succeeded": 8, "failed": 0}
        )
        self.assertEqual(service._status, "completed")
        self.assertEqual(service._current_task, "")
        self.assertEqual(service._summary, {"succeeded": 8, "failed": 0})


if __name__ == "__main__":
    unittest.main()
