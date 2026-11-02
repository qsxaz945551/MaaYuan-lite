"""ANR handling: the one recovery path that touches a system dialog.

Verified against a real 720x1280 capture (2026-11-02): the dialog title sits at
y~478 and 等待 at (303, 688). The tests here pin the decision logic — probe hit
means one tap and a wait, probe miss means nothing happens at all.
"""

from __future__ import annotations

import threading
import unittest
from collections import deque

from lite import run_service
from lite.run_service import ANR_WAIT_POINT, RunService


class FakeSession:
    def __init__(self, hit: bool) -> None:
        self.hit = hit
        self.taps: list[tuple[int, int]] = []
        self.probes = 0

    def probe(self, checks, timeout_ms=1500):  # noqa: ANN001
        self.probes += 1
        assert checks[0]["type"] == "OCR"
        return self.hit

    def tap(self, x: int, y: int) -> bool:
        self.taps.append((x, y))
        return True


def make_service() -> RunService:
    """A RunService with just enough state for logging, no files touched."""
    service = RunService.__new__(RunService)
    service._lock = threading.Lock()
    service._logs = deque(maxlen=100)
    service._log_seq = 0
    return service


class HandleAnrTest(unittest.TestCase):
    def setUp(self) -> None:
        self._sleep = run_service.time.sleep
        run_service.time.sleep = lambda _seconds: None  # keep the test fast

    def tearDown(self) -> None:
        run_service.time.sleep = self._sleep

    def test_taps_wait_once_on_hit(self) -> None:
        session = FakeSession(hit=True)
        service = make_service()
        self.assertTrue(service._handle_anr(session))
        self.assertEqual(session.taps, [ANR_WAIT_POINT])
        self.assertEqual(service._logs[-1]["level"], "warn")
        self.assertIn("无响应", service._logs[-1]["message"])

    def test_does_nothing_without_dialog(self) -> None:
        session = FakeSession(hit=False)
        service = make_service()
        self.assertFalse(service._handle_anr(session))
        self.assertEqual(session.taps, [])
        self.assertEqual(len(service._logs), 0)

    def test_probe_exception_is_not_fatal(self) -> None:
        class Broken(FakeSession):
            def probe(self, checks, timeout_ms=1500):  # noqa: ANN001
                raise RuntimeError("controller gone")

        service = make_service()
        self.assertFalse(service._handle_anr(Broken(hit=True)))

    def test_keywords_cover_common_wording(self) -> None:
        self.assertIn("没有响应", run_service.ANR_KEYWORDS)
        self.assertIn("无响应", run_service.ANR_KEYWORDS)


if __name__ == "__main__":
    unittest.main()
