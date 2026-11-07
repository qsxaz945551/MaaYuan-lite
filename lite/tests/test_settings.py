from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from lite import settings


class SettingsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "runtime-config.json"
        self.path.write_text(
            json.dumps({"adb_serial": "emulator-5554"}, ensure_ascii=False),
            encoding="utf-8",
        )
        self.settings_path = Path(self.temp.name) / "runtime" / "settings.json"
        self.patch = mock.patch.object(settings, "CONFIG_FILE", self.path)
        self.patch.start()
        self.settings_patch = mock.patch.object(
            settings, "SETTINGS_FILE", self.settings_path
        )
        self.settings_patch.start()

    def tearDown(self):
        self.settings_patch.stop()
        self.patch.stop()
        self.temp.cleanup()

    def test_defaults_when_missing(self):
        values = settings.load_settings()
        self.assertEqual(values["startup_action"], "none")
        self.assertEqual(values["shutdown_action"], "none")
        self.assertEqual(values["last_training"], "修为")

    def test_roundtrip_and_unknown_values(self):
        settings.save_settings({"startup_action": "auto_run"})
        self.assertEqual(settings.load_settings()["startup_action"], "auto_run")
        settings.save_settings({"shutdown_action": "bogus"})
        self.assertEqual(settings.load_settings()["shutdown_action"], "none")

    def test_deploy_config_is_never_rewritten(self):
        # 装机配置（路径、串号）只在装机时写一次；用户改设置不该动它，
        # 否则工作区每改一个下拉框就脏一次。
        settings.save_settings({"shutdown_action": "close_both"})
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(raw["adb_serial"], "emulator-5554")
        self.assertNotIn("automation", raw)
        saved = json.loads(self.settings_path.read_text(encoding="utf-8"))
        self.assertEqual(saved["shutdown_action"], "close_both")

    def test_legacy_flags_are_migrated(self):
        self.path.write_text(
            json.dumps(
                {
                    "automation": {
                        "auto_start": True,
                        "start_minimized": True,
                        "close_emulator": True,
                    }
                }
            ),
            encoding="utf-8",
        )
        values = settings.load_settings()
        self.assertEqual(values["startup_action"], "auto_run_minimized")
        self.assertEqual(values["shutdown_action"], "close_both")
        self.assertNotIn("auto_start", values)

    def test_removed_close_emulator_option_falls_back(self):
        self.path.write_text(
            json.dumps({"automation": {"shutdown_action": "close_emulator"}}),
            encoding="utf-8",
        )
        self.assertEqual(settings.load_settings()["shutdown_action"], "none")
        settings.save_settings({"shutdown_action": "close_emulator"})
        self.assertEqual(settings.load_settings()["shutdown_action"], "none")

    def test_last_run_arguments(self):
        saved = settings.save_settings(
            {"last_training": "铜钱", "last_dungeon": True}
        )
        self.assertEqual(saved["last_training"], "铜钱")
        self.assertTrue(saved["last_dungeon"])

    def test_wire_format_is_camel_only(self):
        values = settings.load_settings()
        wire = settings.to_wire(values)
        self.assertEqual(wire["startupAction"], values["startup_action"])
        self.assertEqual(wire["shutdownAction"], values["shutdown_action"])
        self.assertEqual(wire["lastTraining"], values["last_training"])
        self.assertEqual(wire["autoUpdateResources"], values["auto_update_resources"])
        # 网页控制台退役后不再导出 snake_case 副本，避免两种拼写漂移
        self.assertNotIn("startup_action", wire)
        self.assertNotIn("auto_update_framework", wire)

    def test_from_wire_accepts_camel(self):
        normalized = settings.from_wire({"startupAction": "auto_run", "lastDungeon": True})
        self.assertEqual(normalized["startup_action"], "auto_run")
        self.assertTrue(normalized["last_dungeon"])

    def test_from_wire_keeps_snake(self):
        normalized = settings.from_wire({"startup_action": "minimize_only"})
        self.assertEqual(normalized["startup_action"], "minimize_only")

    def test_save_through_camel(self):
        settings.save_settings(settings.from_wire({"startupAction": "auto_run_minimized"}))
        self.assertEqual(settings.load_settings()["startup_action"], "auto_run_minimized")


    def test_concurrent_saves_keep_both_fields(self):
        # Two dropdowns changed within the same second used to lose one write.
        import threading

        errors = []

        def worker(key, value):
            try:
                settings.save_settings({key: value})
            except Exception as error:  # noqa: BLE001
                errors.append(error)

        first = threading.Thread(target=worker, args=("startup_action", "minimize_only"))
        second = threading.Thread(target=worker, args=("shutdown_action", "close_maa"))
        first.start()
        second.start()
        first.join()
        second.join()

        self.assertEqual(errors, [])
        values = settings.load_settings()
        self.assertEqual(values["startup_action"], "minimize_only")
        self.assertEqual(values["shutdown_action"], "close_maa")

    def test_atomic_write_leaves_no_temp_file(self):
        settings.save_settings({"last_training": "经验"})
        leftovers = list(settings.SETTINGS_FILE.parent.glob("settings.json.tmp"))
        self.assertEqual(leftovers, [])

    def test_legacy_automation_moves_to_runtime_file(self):
        # 0.3.2 及更早：偏好写在 runtime-config.json 的 automation 段里。
        self.path.write_text(
            json.dumps({"automation": {"last_training": "铜钱"}}, ensure_ascii=False),
            encoding="utf-8",
        )
        self.assertEqual(settings.load_settings()["last_training"], "铜钱")
        self.assertFalse(self.settings_path.exists())
        settings.save_settings({"last_dungeon": True})
        saved = json.loads(self.settings_path.read_text(encoding="utf-8"))
        self.assertEqual(saved["last_training"], "铜钱")
        self.assertTrue(saved["last_dungeon"])


if __name__ == "__main__":
    unittest.main()
