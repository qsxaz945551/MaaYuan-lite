"""The parent guard must never kill a healthy service, and must say why it kills.

A silent self-kill was invisible for hours: the process disappeared with no
traceback and no log line, so it read as a crash. These tests pin both the
verdict (alive/dead) and the presence of an explanation.
"""

from __future__ import annotations

import os
import unittest

from lite.process_guard import parent_alive, watch_parent


class ParentAliveTest(unittest.TestCase):
    def test_self_is_alive(self) -> None:
        self.assertTrue(parent_alive(os.getpid()))

    def test_missing_pid_is_dead(self) -> None:
        # A PID no process can own; OpenProcess fails with ERROR_INVALID_PARAMETER.
        self.assertFalse(parent_alive(999_999))


class WatchParentTest(unittest.TestCase):
    def test_logs_reason_before_shutting_down(self) -> None:
        lines: list[tuple[str, str]] = []
        called = []

        watch_parent(
            999_999,
            lambda: called.append(True),
            interval=0.01,
            logger=lambda message, level: lines.append((message, level)),
        )

        for _ in range(200):
            if called:
                break
            import time

            time.sleep(0.01)

        self.assertEqual(called, [True], "父进程不在时必须触发关闭")
        self.assertEqual(len(lines), 1, "关闭前必须写一条日志说明原因")
        message, level = lines[0]
        self.assertEqual(level, "warn")
        self.assertIn("999999", message)
        self.assertIn("父进程", message)

    def test_survives_a_broken_logger(self) -> None:
        """日志通道本身出错也不能影响关闭流程。"""
        called = []

        def broken(message: str, level: str) -> None:
            raise RuntimeError("logger exploded")

        watch_parent(999_999, lambda: called.append(True), interval=0.01, logger=broken)

        for _ in range(200):
            if called:
                break
            import time

            time.sleep(0.01)

        self.assertEqual(called, [True])


if __name__ == "__main__":
    unittest.main()
