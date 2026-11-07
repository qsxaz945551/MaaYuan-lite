"""升级白名单：KEEP 里的文件在 --apply 阶段也必须真的留下。

原来 KEEP 只影响预演（plan），真正执行时 `_copy_tree` 直接把整个
assets/resource 盖过去 —— 预演说"不动"，执行完文件却没了。
Lite 自己加的 activity_title.png 正好落在这个盲区里。
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "devtools"))

import upgrade  # noqa: E402


class KeepListTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self.source = base / "source"
        self.target = base / "target"
        image_src = self.source / "assets" / "resource" / "base" / "image"
        image_dst = self.target / "assets" / "resource" / "base" / "image"
        image_src.mkdir(parents=True)
        image_dst.mkdir(parents=True)

        # 补丁图（KEEP）与普通资源图（应被覆盖）
        (image_src / "activity_title.png").write_bytes(b"NEW-PATCH")
        (image_dst / "activity_title.png").write_bytes(b"OLD-PATCH")
        (image_src / "eventicon.png").write_bytes(b"NEW-UPSTREAM-BIGGER")
        (image_dst / "eventicon.png").write_bytes(b"OLD-UPSTREAM")

        (image_src / "added_by_upstream.png").write_bytes(b"NEW-FILE")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_kept_file_is_not_overwritten(self) -> None:
        src = self.source / "assets" / "resource" / "base" / "image"
        dst = self.target / "assets" / "resource" / "base" / "image"
        upgrade._copy_tree(src, dst, "assets/resource/base/image")
        self.assertEqual((dst / "activity_title.png").read_bytes(), b"OLD-PATCH")

    def test_normal_resource_is_still_replaced(self) -> None:
        src = self.source / "assets" / "resource" / "base" / "image"
        dst = self.target / "assets" / "resource" / "base" / "image"
        upgrade._copy_tree(src, dst, "assets/resource/base/image")
        self.assertEqual((dst / "eventicon.png").read_bytes(), b"NEW-UPSTREAM-BIGGER")

    def test_new_upstream_file_is_added(self) -> None:
        src = self.source / "assets" / "resource" / "base" / "image"
        dst = self.target / "assets" / "resource" / "base" / "image"
        upgrade._copy_tree(src, dst, "assets/resource/base/image")
        self.assertTrue((dst / "added_by_upstream.png").is_file())

    def test_dry_run_and_apply_agree(self) -> None:
        # 预演不该把补丁图算成"会被改动"
        changes = upgrade.plan(self.source, self.target)
        self.assertNotIn("assets/resource/base/image/activity_title.png", changes)
        self.assertIn("assets/resource/base/image/eventicon.png", changes)


if __name__ == "__main__":
    unittest.main()
