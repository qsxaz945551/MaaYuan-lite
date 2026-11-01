from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from lite.session import LiteSession


ROOT = Path(__file__).resolve().parents[2]


class LogRotationTest(unittest.TestCase):
    def make_session(self, root: Path) -> LiteSession:
        with mock.patch.object(
            LiteSession, "_find_agent_binary", return_value=root / "agent-bin"
        ):
            return LiteSession(root, ROOT, ROOT / "adb.exe")

    def test_rotates_oversized_log_and_trims_agent_logs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "debug").mkdir()
            (root / "debug" / "maa.log").write_bytes(b"x" * 4096)
            logs = root / "runtime" / "logs"
            logs.mkdir(parents=True)
            for index in range(6):
                path = logs / f"agent-20261030-00000{index}.log"
                path.write_text("x", encoding="utf-8")
                path.touch()

            session = self.make_session(root)
            session.rotate_logs(
                max_maa_log_bytes=1024, keep_archives=2, keep_agent_logs=3
            )

            self.assertFalse((root / "debug" / "maa.log").exists())
            self.assertEqual(len(list((root / "debug").glob("maa-*.log"))), 1)
            self.assertEqual(len(list(logs.glob("agent-*.log"))), 3)

    def test_small_log_is_left_alone(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "debug").mkdir()
            (root / "debug" / "maa.log").write_bytes(b"x" * 128)
            (root / "runtime" / "logs").mkdir(parents=True)

            session = self.make_session(root)
            actions = session.rotate_logs(max_maa_log_bytes=1024)

            self.assertTrue((root / "debug" / "maa.log").is_file())
            self.assertEqual(actions, [])


if __name__ == "__main__":
    unittest.main()
