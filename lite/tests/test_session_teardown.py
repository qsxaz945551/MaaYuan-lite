"""Teardown must never block forever.

Symptom that prompted this: a task reported ``completed``, but the worker
thread was still inside ``session.stop()``. ``_busy()`` therefore stayed True
and every later run was rejected with 409 — the user could run one task per
service lifetime. Native ``Job.wait()`` / ``disconnect()`` have no timeout, so
the guard here is what keeps that from becoming permanent.
"""

from __future__ import annotations

import time
import unittest

from lite.session import LiteSession, _release_native


class Harness:
    """Just the two methods under test plus a logger sink."""

    _note = LiteSession._note
    _with_timeout = LiteSession._with_timeout

    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []
        self._logger = lambda message, level="warn": self.messages.append((message, level))


class WithTimeoutTest(unittest.TestCase):
    def test_slow_step_is_abandoned(self) -> None:
        harness = Harness()
        began = time.monotonic()
        harness._with_timeout("慢步骤", lambda: time.sleep(5), 0.2)
        elapsed = time.monotonic() - began

        self.assertLess(elapsed, 1.5, "超时后必须立刻返回，不能等原生调用自己结束")
        self.assertEqual(len(harness.messages), 1)
        message, level = harness.messages[0]
        self.assertEqual(level, "warn")
        self.assertIn("慢步骤", message)

    def test_fast_step_does_not_warn(self) -> None:
        harness = Harness()
        done = []
        harness._with_timeout("快步骤", lambda: done.append(True), 1.0)

        self.assertEqual(done, [True])
        self.assertEqual(harness.messages, [])

    def test_exception_does_not_escape(self) -> None:
        """收尾阶段的异常不能冒出来，否则 finally 会被打断。"""
        harness = Harness()

        def boom() -> None:
            raise RuntimeError("native call failed")

        harness._with_timeout("报错步骤", boom, 1.0)
        self.assertEqual(harness.messages, [])


class _Native:
    """Stand-in for maa.Tasker / maa.AgentClient: teardown lives in __del__."""

    def __init__(self, fail: bool = False) -> None:
        self._handle = object()
        self.destroys = 0
        self.fail = fail

    def __del__(self) -> None:
        if self._handle:
            self.destroys += 1
            if self.fail:
                raise RuntimeError("native destroy failed")


class ReleaseNativeTest(unittest.TestCase):
    """原生对象只能销毁一次，否则就是二次释放（0xc0000374）。"""

    def test_destructor_runs_once(self) -> None:
        native = _Native()
        _release_native(native)

        self.assertIsNone(native._handle)
        self.assertEqual(native.destroys, 1)

        # 引用归零时 CPython 会再调一次 __del__，必须变成空操作。
        _release_native(native)
        self.assertEqual(native.destroys, 1)

    def test_raising_destructor_still_disarms(self) -> None:
        native = _Native(fail=True)
        _release_native(native)

        self.assertIsNone(native._handle)
        self.assertEqual(native.destroys, 1)


if __name__ == "__main__":
    unittest.main()
