"""adb 探测链的优先级测试。

顺序是 配置 → LDPLAYER_PATH → 注册表 → 常见安装目录 → 内置副本。任何一环
「找到了但文件不存在」都必须继续往下走，不能直接判失败——用户重装模拟器
换了盘符时，旧配置里的路径就是失效的，但环境里往往还有可用副本。
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from lite import adb_finder


class FindAdbTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.registry = mock.patch.object(adb_finder, "_from_registry", return_value=None)
        self.registry.start()
        self.common = mock.patch.object(
            adb_finder, "_from_common_folders", return_value=None
        )
        self.common.start()
        self.env = mock.patch.dict(os.environ, {"LDPLAYER_PATH": ""})
        self.env.start()

    def tearDown(self) -> None:
        self.env.stop()
        self.common.stop()
        self.registry.stop()
        self.temp.cleanup()

    def _adb(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"")
        return path

    def test_configured_absolute_path_wins(self) -> None:
        adb = self._adb(self.root / "ld" / "adb.exe")
        path, source = adb_finder.find_adb(str(adb), self.root)
        self.assertEqual(path, adb)
        self.assertEqual(source, "配置")

    def test_configured_relative_path_is_resolved(self) -> None:
        adb = self._adb(self.root / "ld" / "adb.exe")
        path, source = adb_finder.find_adb("ld/adb.exe", self.root)
        self.assertEqual(path, adb)
        self.assertEqual(source, "配置")

    def test_missing_configured_path_falls_through(self) -> None:
        bundled = self._adb(self.root / "runtime_env" / "platform-tools" / "adb.exe")
        path, source = adb_finder.find_adb("Z:/gone/adb.exe", self.root)
        self.assertEqual(path, bundled)
        self.assertEqual(source, "内置 platform-tools")

    def test_environment_variable_is_second(self) -> None:
        folder = self.root / "env-ld"
        adb = self._adb(folder / "adb.exe")
        with mock.patch.dict(os.environ, {"LDPLAYER_PATH": str(folder)}):
            path, source = adb_finder.find_adb("", self.root)
        self.assertEqual(path, adb)
        self.assertEqual(source, "环境变量 LDPLAYER_PATH")

    def test_registry_beats_common_folders(self) -> None:
        adb = self._adb(self.root / "reg" / "adb.exe")
        with mock.patch.object(adb_finder, "_from_registry", return_value=adb):
            path, source = adb_finder.find_adb("", self.root)
        self.assertEqual(path, adb)
        self.assertEqual(source, "注册表")

    def test_common_folders_are_last_resort_before_bundled(self) -> None:
        adb = self._adb(self.root / "common" / "adb.exe")
        with mock.patch.object(adb_finder, "_from_common_folders", return_value=adb):
            path, source = adb_finder.find_adb("", self.root)
        self.assertEqual(path, adb)
        self.assertEqual(source, "常见安装目录")

    def test_nothing_found(self) -> None:
        path, source = adb_finder.find_adb("", self.root)
        self.assertIsNone(path)
        self.assertEqual(source, "未找到")


if __name__ == "__main__":
    unittest.main()
