"""Tests for the resource manifest — the foundation of the update chain.

``downloader`` / ``updater`` / ``update_applier`` / ``sync_repo`` all depend on
this file being well formed, but it had no direct test. The cases below cover
"no git metadata", "models present", "pipeline counting" and the lookup order
used when deciding which resources are actually in use.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from lite.source_manifest import (
    MANIFEST_NAME,
    MODEL_FILES,
    REQUIRED_MODELS,
    build_manifest,
    find_manifest,
    write_manifest,
)


class ManifestBuildTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.base = self.root / "assets" / "resource" / "base"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _write_models(self, names=MODEL_FILES) -> None:
        for relative in names:
            path = self.base / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"model-bytes")

    def _write_pipelines(self, count: int = 2) -> None:
        for index in range(count):
            path = self.base / "pipeline" / "daily" / f"task_{index}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{}", encoding="utf-8")

    def test_missing_models_are_omitted_not_faked(self) -> None:
        """en_us 上游没有 det.onnx：缺的文件不能塞进 models，否则更新会 404。"""
        self._write_models([item for item in MODEL_FILES if "en/det" not in item])
        manifest = build_manifest(self.root)
        self.assertNotIn("model/ocr/en/det.onnx", manifest["models"])
        self.assertEqual(len(manifest["models"]), len(MODEL_FILES))

    def test_required_models_are_a_prefix_of_the_full_list(self) -> None:
        self.assertEqual(REQUIRED_MODELS, MODEL_FILES[:3])

    def test_pipeline_count_walks_subdirectories(self) -> None:
        self._write_pipelines(3)
        self.assertEqual(build_manifest(self.root)["pipelineCount"], 3)

    def test_interface_hash_only_when_present(self) -> None:
        self.assertEqual(build_manifest(self.root)["interfaceSha256"], "")
        interface = self.root / "assets" / "interface.json"
        interface.parent.mkdir(parents=True, exist_ok=True)
        interface.write_text("{}", encoding="utf-8")
        self.assertEqual(len(build_manifest(self.root)["interfaceSha256"]), 64)

    def test_missing_git_metadata_is_empty_not_an_exception(self) -> None:
        # 临时目录不是 git 仓库：更新链路不能因为拿不到 commit 就崩。
        manifest = build_manifest(self.root)
        self.assertEqual(manifest["commit"], "")
        self.assertEqual(manifest["branch"], "")
        self.assertIn("generatedAt", manifest)

    def test_write_manifest_creates_valid_json_with_newline(self) -> None:
        self._write_models()
        path = write_manifest(self.root)
        self.assertEqual(path, self.root / "assets" / MANIFEST_NAME)
        raw = path.read_text(encoding="utf-8")
        self.assertTrue(raw.endswith("\n"))
        self.assertEqual(json.loads(raw)["pipelineCount"], 0)


class ManifestLookupTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "assets").mkdir()
        (self.root / "vendor" / "MaaYuan-src" / "assets").mkdir(parents=True)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _manifest(self, folder: Path, commit: str) -> Path:
        path = folder / MANIFEST_NAME
        path.write_text(json.dumps({"commit": commit}), encoding="utf-8")
        return path

    def test_missing_returns_none(self) -> None:
        self.assertEqual(find_manifest(self.root), (None, None))

    def test_project_root_wins_over_vendor(self) -> None:
        live = self._manifest(self.root / "assets", "live")
        self._manifest(self.root / "vendor" / "MaaYuan-src" / "assets", "vendor")
        path, data = find_manifest(self.root)
        self.assertEqual(path, live)
        self.assertEqual(data["commit"], "live")

    def test_vendor_is_the_fallback(self) -> None:
        vendored = self._manifest(self.root / "vendor" / "MaaYuan-src" / "assets", "v")
        path, data = find_manifest(self.root)
        self.assertEqual(path, vendored)
        self.assertEqual(data["commit"], "v")

    def test_broken_manifest_falls_through(self) -> None:
        broken = self.root / "assets" / MANIFEST_NAME
        broken.write_text("{not json", encoding="utf-8")
        vendored = self._manifest(self.root / "vendor" / "MaaYuan-src" / "assets", "v")
        path, _ = find_manifest(self.root)
        self.assertEqual(path, vendored)


if __name__ == "__main__":
    unittest.main()
