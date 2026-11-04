from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from lite import agent_guard


class RecordClearTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_record_then_clear(self) -> None:
        agent_guard.record(self.root, pid=1234, port=8765)
        path = self.root / "runtime" / "agent.json"
        self.assertTrue(path.is_file())
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(data["pid"], 1234)
        self.assertEqual(data["port"], 8765)
        agent_guard.clear(self.root)
        self.assertFalse(path.exists())

    def test_reap_dead_pid_only_clears_file(self) -> None:
        agent_guard.record(self.root, pid=999999999)
        actions = agent_guard.reap_orphans(self.root)
        self.assertEqual(actions, [])
        self.assertFalse((self.root / "runtime" / "agent.json").exists())

    def test_reap_missing_file_is_noop(self) -> None:
        self.assertEqual(agent_guard.reap_orphans(self.root), [])

    def test_reap_corrupt_file_clears(self) -> None:
        path = self.root / "runtime" / "agent.json"
        path.parent.mkdir(parents=True)
        path.write_text("not json", encoding="utf-8")
        self.assertEqual(agent_guard.reap_orphans(self.root), [])
        self.assertFalse(path.exists())


class RotateTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _seed(self, folder: str, count: int) -> None:
        target = self.root / folder
        target.mkdir(parents=True, exist_ok=True)
        for index in range(count):
            path = target / f"f-{index:03d}.log"
            path.write_text("x", encoding="utf-8")
            # 显式时间戳：同一次循环里创建的文件 mtime 可能完全相同，
            # 排序就退化成目录顺序，测试会随机成败。
            stamp = 1_700_000_000 + index
            os.utime(path, (stamp, stamp))

    def test_trims_to_keep(self) -> None:
        self._seed("runtime/logs", 60)
        removed = agent_guard.rotate_logs(self.root)
        self.assertEqual(removed["agentLogs"], 60 - agent_guard.LOG_KEEP)
        remaining = list((self.root / "runtime" / "logs").iterdir())
        self.assertEqual(len(remaining), agent_guard.LOG_KEEP)

    def test_keeps_newest(self) -> None:
        self._seed("runtime/logs", 45)
        agent_guard.rotate_logs(self.root)
        # newest file must survive
        self.assertTrue((self.root / "runtime" / "logs" / "f-044.log").is_file())
        self.assertFalse((self.root / "runtime" / "logs" / "f-000.log").exists())

    def test_missing_folders_ok(self) -> None:
        removed = agent_guard.rotate_logs(self.root)
        self.assertEqual(removed, {"agentLogs": 0, "debug": 0, "cache": 0})

    def test_summarize_counts(self) -> None:
        self._seed("runtime/logs", 3)
        data = agent_guard.summarize(self.root)
        self.assertEqual(data["agentLogs"]["files"], 3)


if __name__ == "__main__":
    unittest.main()
