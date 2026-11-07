"""The update panel must not promise what it cannot do.

The framework is pinned by the release bundle, so comparing it against the
newest PyPI upload made the badge show an update forever (5.6.0 vs 5.15.0) with
no way to install it. These tests pin the corrected semantics.
"""

from __future__ import annotations

import tempfile
import unittest
import unittest.mock
from pathlib import Path

from lite.updater import FRAMEWORK_PINNED, check_updates


class FrameworkPinTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _check(self, installed: str, latest: str = "5.15.0") -> dict:
        with (
            unittest.mock.patch(
                "lite.updater.find_manifest", return_value=(None, None)
            ),
            unittest.mock.patch(
                "lite.updater._fetch_remote_commit",
                return_value={"sha": "a" * 12, "date": "2026-11-06"},
            ),
            unittest.mock.patch(
                "lite.updater._fetch_pypi_version", return_value=latest
            ),
            unittest.mock.patch("importlib.metadata.version", return_value=installed),
        ):
            return check_updates(self.root, force=True)

    def test_pypi_latest_alone_is_not_an_update(self) -> None:
        """装的就是发布包钉住的版本时，PyPI 再新也不算"有更新"。"""
        data = self._check(FRAMEWORK_PINNED)
        self.assertFalse(data["framework"]["available"])
        self.assertEqual(data["framework"]["pinned"], FRAMEWORK_PINNED)
        self.assertEqual(data["framework"]["latest"], "5.15.0")

    def test_drifted_install_is_flagged(self) -> None:
        data = self._check("5.14.0")
        self.assertTrue(data["framework"]["available"])

    def test_unknown_install_is_not_flagged(self) -> None:
        """读不到版本时不要凭空报警。"""
        data = self._check("?")
        self.assertFalse(data["framework"]["available"])

    def test_pinned_version_matches_requirements(self) -> None:
        """两处 5.6.0 必须同步：装环境用的 requirements 与运行时判断的 pin。"""
        root = Path(__file__).resolve().parents[2]
        text = (root / "requirements.txt").read_text(encoding="utf-8")
        self.assertIn(f"maafw=={FRAMEWORK_PINNED}", text)


class ResourceAvailabilityTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _check(self, local: str, remote: str) -> dict:
        with (
            unittest.mock.patch(
                "lite.updater.find_manifest",
                return_value=(self.root / "manifest.json", {"commit": local, "commitDate": "2026-11-05"}),
            ),
            unittest.mock.patch(
                "lite.updater._fetch_remote_commit",
                return_value={"sha": remote, "date": "2026-11-06"},
            ),
            unittest.mock.patch("lite.updater._fetch_pypi_version", return_value="5.15.0"),
            unittest.mock.patch("importlib.metadata.version", return_value=FRAMEWORK_PINNED),
        ):
            return check_updates(self.root, force=True)

    def test_same_commit_is_up_to_date(self) -> None:
        data = self._check("a" * 40, "a" * 40)
        self.assertFalse(data["resource"]["available"])

    def test_new_commit_is_available(self) -> None:
        data = self._check("a" * 40, "b" * 40)
        self.assertTrue(data["resource"]["available"])
        self.assertEqual(data["resource"]["local"], "a" * 12)
        self.assertEqual(data["resource"]["remote"], "b" * 12)
