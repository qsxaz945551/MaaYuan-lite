"""Offline checks for the downloader's tree handling.

Nothing here touches the network: the archive is a synthetic zip and model
"download" is exercised through the reuse branch, which is the path every
routine update takes when the submodule pin has not moved.
"""

from __future__ import annotations

import json
import tempfile
import unittest
import unittest.mock
import zipfile
from pathlib import Path

from lite import downloader
from lite.source_manifest import MANIFEST_NAME


def _zip(path: Path, entries: dict[str, str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as bundle:
        for name, text in entries.items():
            bundle.writestr(name, text)
    return path


class ExtractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_keeps_only_assets_and_agent(self) -> None:
        archive = _zip(
            self.root / "a.zip",
            {
                "MaaYuan-abc123/assets/interface.json": "{}",
                "MaaYuan-abc123/assets/resource/base/pipeline/x.json": "{}",
                "MaaYuan-abc123/agent/main.py": "print(1)",
                "MaaYuan-abc123/docs/readme.md": "noise",
                "MaaYuan-abc123/tools/x.py": "noise",
            },
        )
        target = self.root / "out"
        downloader._extract(archive, target)

        self.assertTrue((target / "assets" / "interface.json").is_file())
        self.assertTrue((target / "assets" / "resource" / "base" / "pipeline" / "x.json").is_file())
        self.assertTrue((target / "agent" / "main.py").is_file())
        self.assertFalse((target / "docs").exists())
        self.assertFalse((target / "tools").exists())

    def test_rejects_zip_slip(self) -> None:
        archive = _zip(
            self.root / "b.zip",
            {"MaaYuan-abc/agent/../../evil.py": "x", "MaaYuan-abc/agent/main.py": "x"},
        )
        target = self.root / "out"
        downloader._extract(archive, target)
        self.assertFalse((self.root / "evil.py").exists())

    def test_two_roots_rejected(self) -> None:
        archive = _zip(
            self.root / "c.zip",
            {"A/agent/main.py": "x", "B/agent/main.py": "x"},
        )
        with self.assertRaises(RuntimeError):
            downloader._extract(archive, self.root / "out")


class VerifyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_missing_pieces_are_named(self) -> None:
        problems = downloader._verify(self.root)
        joined = "；".join(problems)
        self.assertIn("interface.json", joined)
        self.assertIn("pipeline", joined)
        self.assertIn("agent/main.py", joined)

    def test_complete_tree_passes(self) -> None:
        part = self.root
        (part / "assets").mkdir(parents=True, exist_ok=True)
        (part / "assets" / "interface.json").write_text("{}", encoding="utf-8")
        pipeline = part / "assets" / "resource" / "base" / "pipeline"
        pipeline.mkdir(parents=True)
        for index in range(120):
            (pipeline / f"n{index}.json").write_text("{}", encoding="utf-8")
        (part / "agent").mkdir()
        (part / "agent" / "main.py").write_text("x", encoding="utf-8")
        for relative in (
            "model/ocr/det.onnx",
            "model/ocr/rec.onnx",
            "model/ocr/keys.txt",
        ):
            path = part / "assets" / "resource" / "base" / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"model")
        self.assertEqual(downloader._verify(part), [])


class ModelReuseTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.pin = "p" * 40

        live = self.root / "assets" / "resource" / "base"
        for relative, names in (
            ("model/ocr", ("det.onnx", "rec.onnx", "keys.txt")),
            ("model/ocr/operator_names", ("det.onnx", "rec.onnx", "keys.txt")),
            ("model/ocr/en", ("rec.onnx", "keys.txt")),
        ):
            for name in names:
                path = live / relative / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"live-" + name.encode())

        (self.root / "assets" / MANIFEST_NAME).write_text(
            json.dumps({"modelsCommit": self.pin}), encoding="utf-8"
        )
        self.part = self.root / "assets.next.part"
        (self.part / "assets" / "resource" / "base").mkdir(parents=True)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_same_pin_copies_instead_of_downloading(self) -> None:
        reused = downloader._sync_models(self.root, self.part, self.pin)
        self.assertEqual(reused, 8)
        sample = self.part / "assets" / "resource" / "base" / "model" / "ocr" / "det.onnx"
        self.assertEqual(sample.read_bytes(), b"live-det.onnx")

    def test_unknown_pin_without_models_fails_loudly(self) -> None:
        with self.assertRaises(RuntimeError):
            downloader._sync_models(self.root, self.part, "")


if __name__ == "__main__":
    unittest.main()


class _InlineThread:
    """Run the background worker on the calling thread so tests are deterministic."""

    def __init__(self, target=None, name=None, daemon=None):  # noqa: ANN001
        self._target = target

    def start(self) -> None:
        if self._target is not None:
            self._target()


class AutoCheckLogTest(unittest.TestCase):
    """auto_check now reports what it decided; silence was the original complaint."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.lines: list[tuple[str, str]] = []
        downloader._thread = None

    def tearDown(self) -> None:
        self.temp.cleanup()
        downloader._thread = None

    def _run(self, resource: dict, *, staged: bool = False) -> None:
        import types

        if staged:
            (self.root / downloader.STAGE).mkdir(parents=True)
        fake_updater = types.SimpleNamespace(
            check_updates=lambda _root: {"resource": resource}
        )
        with (
            unittest.mock.patch.dict("sys.modules", {"lite.updater": fake_updater}),
            unittest.mock.patch.object(
                downloader, "threading", types.SimpleNamespace(Thread=_InlineThread)
            ),
            unittest.mock.patch.object(downloader, "start", return_value={}) as start,
        ):
            downloader.auto_check(
                self.root, delay=0, log=lambda msg, level="info": self.lines.append((msg, level))
            )
        self.start = start

    def test_up_to_date_is_reported(self) -> None:
        self._run({"available": False, "local": "abc123", "error": None})
        self.assertTrue(any("资源已是最新（abc123）" in msg for msg, _ in self.lines))
        self.start.assert_not_called()

    def test_available_update_starts_download_and_says_so(self) -> None:
        self._run(
            {
                "available": True,
                "local": "abc123",
                "remote": "def456",
                "remoteDate": "2026-11-06",
                "error": None,
            }
        )
        messages = " ".join(msg for msg, _ in self.lines)
        self.assertIn("资源有更新", messages)
        self.assertIn("def456", messages)
        self.start.assert_called_once()

    def test_staged_tree_is_left_alone(self) -> None:
        self._run({"available": True, "local": "abc123", "remote": "def456"}, staged=True)
        self.assertTrue(any("待生效" in msg for msg, _ in self.lines))
        self.start.assert_not_called()

    def test_offline_is_a_warning_not_a_crash(self) -> None:
        self._run({"available": False, "local": None, "error": "URLError: offline"})
        self.assertTrue(
            any("检查资源更新失败" in msg and level == "warn" for msg, level in self.lines)
        )
