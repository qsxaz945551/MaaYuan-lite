"""Node-callback failures must reach the run log.

Swallowing them was the worst kind of silence: round counting stops updating
and the run looks stuck even though the task is fine.
"""

from __future__ import annotations

import unittest

from lite.session import LiteSession


def make_session() -> tuple[LiteSession, list[tuple[str, str]]]:
    session = LiteSession.__new__(LiteSession)
    notes: list[tuple[str, str]] = []
    session._logger = lambda message, level="info": notes.append((level, message))
    session._node_callback = None
    session._node_start_callback = None
    return session, notes


class CallbackErrorTest(unittest.TestCase):
    def test_node_callback_error_is_logged(self) -> None:
        session, notes = make_session()

        def boom(_name: str) -> None:
            raise RuntimeError("round counter exploded")

        session._node_callback = boom
        session._handle_node("💠 攻取结算")
        self.assertEqual(len(notes), 1)
        level, message = notes[0]
        self.assertEqual(level, "warn")
        self.assertIn("round counter exploded", message)
        self.assertIn("攻取结算", message)

    def test_node_start_callback_error_is_logged(self) -> None:
        session, notes = make_session()

        def boom(_name: str) -> None:
            raise ValueError("bad start hook")

        session._node_start_callback = boom
        session._handle_node_start("进入界面-地宫")
        self.assertEqual(len(notes), 1)
        self.assertIn("bad start hook", notes[0][1])

    def test_no_callback_is_silent(self) -> None:
        session, notes = make_session()
        session._handle_node("任意节点")
        session._handle_node_start("任意节点")
        self.assertEqual(notes, [])

    def test_logger_failure_does_not_propagate(self) -> None:
        session, _ = make_session()

        def broken_logger(_message: str, _level: str = "info") -> None:
            raise OSError("log sink gone")

        def boom(_name: str) -> None:
            raise RuntimeError("callback failed")

        session._logger = broken_logger
        session._node_callback = boom
        session._handle_node("节点")  # must not raise

    def test_missing_logger_does_not_raise(self) -> None:
        session = LiteSession.__new__(LiteSession)
        session._logger = None
        session._node_callback = lambda _name: (_ for _ in ()).throw(RuntimeError("x"))
        session._node_start_callback = None
        session._handle_node("节点")  # must not raise


if __name__ == "__main__":
    unittest.main()
