"""`stop()` must return promptly, whatever the native destructors do.

MaaAgentClientDestroy blocks forever once the device disappeared mid-task (the
stack is in runtime/crash.log). While `stop()` waited for it, the worker thread
stayed alive — and `_busy()` is defined as "the worker thread is alive" — so the
UI rejected every later run with 409 until the timeout expired. Destroying in
the background is the fix; these tests keep it from silently regressing.
"""

from __future__ import annotations

import tempfile
import threading
import time
import unittest
from pathlib import Path

from lite.session import LiteSession


class SlowNative:
    """Stands in for a MaaFramework object whose destructor never returns."""

    def __init__(self) -> None:
        self.entered = threading.Event()
        self.finished = threading.Event()

    def disconnect(self) -> None:
        """真实 AgentClient 有这个接口，stop() 会先调它再析构。"""
        return None

    def __del__(self) -> None:
        self.entered.set()
        time.sleep(3)
        self.finished.set()


def make_session(root: Path) -> tuple[LiteSession, list[tuple[str, str]]]:
    session = LiteSession.__new__(LiteSession)
    messages: list[tuple[str, str]] = []
    session._logger = lambda message, level="warn": messages.append((message, level))
    session.project_root = root
    session._sink = None
    session._sink_id = None
    session._node_callback = None
    session._node_start_callback = None
    session._started = True
    session._agent_process = None
    session._agent_stdout = None
    session._agent_stderr = None
    session._tasker = None
    session._resource = None
    session._controller = None
    session._agent_client = SlowNative()
    return session, messages


class StopNonBlockingTest(unittest.TestCase):
    def test_stop_returns_before_native_destroy_finishes(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            session, _messages = make_session(Path(temp))
            client = session._agent_client

            began = time.monotonic()
            session.stop()
            elapsed = time.monotonic() - began

            self.assertLess(elapsed, 1.0, "stop() 不能等原生析构，否则服务会一直「忙」")
            # 析构确实在后台跑起来了，只是没被等待
            self.assertTrue(client.entered.wait(1.0), "后台线程应当已经进入析构")
            self.assertFalse(client.finished.is_set(), "此时析构应当仍在阻塞中")

    def test_native_attributes_are_cleared(self) -> None:
        """引用必须先摘掉，否则后台线程和 GC 会同时持有同一个句柄。"""
        with tempfile.TemporaryDirectory() as temp:
            session, _messages = make_session(Path(temp))
            session.stop()
            self.assertIsNone(session._agent_client)


class StopOrderTest(unittest.TestCase):
    def test_stop_without_objects_is_harmless(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            session, _messages = make_session(Path(temp))
            session._agent_client = None
            session.stop()  # 不该抛异常
            self.assertTrue(session._started is False)


if __name__ == "__main__":
    unittest.main()
