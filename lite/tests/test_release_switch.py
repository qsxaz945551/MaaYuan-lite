"""Rollback (Q3) depends on two small guarantees: the pointer wins, and
`previous` always moves somewhere else. A silent no-op here would mean the user
"rolls back" and keeps running the broken build.
"""

from __future__ import annotations

import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "devtools"))

import release_switch as rs  # noqa: E402


def make_release(root: Path, version: str) -> Path:
    path = root / f"MaaYuan-Lite-{version}"
    path.mkdir(parents=True)
    (path / "start-lite.bat").write_text("@echo off\n", encoding="utf-8")
    return path


class ReleaseSwitchTest(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.root = Path(self._temp.name)
        make_release(self.root, "0.1.9")
        make_release(self.root, "0.2.0")

    def tearDown(self) -> None:
        self._temp.cleanup()

    def test_newest_first(self) -> None:
        names = [path.name for path in rs.versions(self.root)]
        self.assertEqual(names, ["MaaYuan-Lite-0.2.0", "MaaYuan-Lite-0.1.9"])

    def test_switch_by_version_and_by_directory_name(self) -> None:
        rs.write_active(self.root, rs.resolve(self.root, "0.1.9").name)
        self.assertEqual(rs.read_active(self.root), "MaaYuan-Lite-0.1.9")
        rs.write_active(self.root, rs.resolve(self.root, "MaaYuan-Lite-0.2.0").name)
        self.assertEqual(rs.read_active(self.root), "MaaYuan-Lite-0.2.0")

    def test_pointer_has_no_trailing_newline(self) -> None:
        """A CR in the pointer file breaks the launcher's `set /p` check."""
        rs.write_active(self.root, "MaaYuan-Lite-0.2.0")
        raw = (self.root / rs.POINTER).read_bytes()
        self.assertNotIn(b"\r", raw)
        self.assertNotIn(b"\n", raw)

    def test_previous_without_pointer_is_second_newest(self) -> None:
        self.assertEqual(rs.resolve(self.root, "previous").name, "MaaYuan-Lite-0.1.9")

    def test_previous_toggles(self) -> None:
        rs.write_active(self.root, "MaaYuan-Lite-0.2.0")
        first = rs.resolve(self.root, "previous")
        self.assertEqual(first.name, "MaaYuan-Lite-0.1.9")
        rs.write_active(self.root, first.name)
        second = rs.resolve(self.root, "previous")
        self.assertEqual(second.name, "MaaYuan-Lite-0.2.0")

    def test_single_version_cannot_roll_back(self) -> None:
        lone = self.root / "solo"
        make_release(lone, "1.0.0")
        with self.assertRaises(SystemExit):
            rs.resolve(lone, "previous")

    def test_unknown_version_is_rejected(self) -> None:
        with self.assertRaises(SystemExit):
            rs.resolve(self.root, "9.9.9")

    def test_prune_never_deletes_the_active_version(self) -> None:
        rs.write_active(self.root, "MaaYuan-Lite-0.1.9")
        with contextlib.redirect_stdout(io.StringIO()):
            rs.cmd_prune(self.root, keep=1, dry_run=False)
        self.assertTrue((self.root / "MaaYuan-Lite-0.1.9").is_dir())
        self.assertTrue((self.root / "MaaYuan-Lite-0.2.0").is_dir())

    def test_prune_removes_older_versions(self) -> None:
        rs.write_active(self.root, "MaaYuan-Lite-0.2.0")
        with contextlib.redirect_stdout(io.StringIO()):
            rs.cmd_prune(self.root, keep=1, dry_run=False)
        self.assertTrue((self.root / "MaaYuan-Lite-0.2.0").is_dir())
        self.assertFalse((self.root / "MaaYuan-Lite-0.1.9").exists())


if __name__ == "__main__":
    unittest.main()
