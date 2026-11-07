"""Route-level tests for the hand-written HTTP layer.

``make_handler`` is the largest single block in the project (14 routes) and had
no test at all: status codes, body parsing and the code/message split were only
covered by manual smoke scripts. These tests start a real server on an
ephemeral port and drive it over HTTP, so the contract is exercised end to end.
"""

from __future__ import annotations

import json
import threading
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

import app
from lite import settings
from lite.version import API_VERSION, VERSION


class FakeService:
    """Only the members the tested routes touch."""

    def __init__(self) -> None:
        self.config = {"host": "127.0.0.1", "port": 0}
        self.calls: list[tuple] = []
        self.start_result = True
        self.start_error: Exception | None = None
        self.sequence_error: Exception | None = None
        self.snapshot_value = {
            "status": "idle",
            "currentTask": "",
            "tasks": [],
            "logSeq": 7,
            "logs": [],
        }

    def snapshot(self, since: int = 0) -> dict:
        self.calls.append(("snapshot", since))
        return dict(self.snapshot_value)

    def log_cursor(self) -> int:
        return 7

    def note(self, message: str, level: str = "info") -> None:
        self.calls.append(("note", message, level))

    def start_daily(self, **kwargs):
        self.calls.append(("start_daily", kwargs))
        if self.start_error is not None:
            raise self.start_error
        return self.start_result

    def run_sequence(self, names: list[str]) -> bool:
        self.calls.append(("run_sequence", names))
        if self.sequence_error is not None:
            raise self.sequence_error
        return True


class HTTPApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.config_path = Path(self.temp.name) / "runtime-config.json"
        self.config_path.write_text(
            json.dumps({"automation": {}}, ensure_ascii=False), encoding="utf-8"
        )
        self.config_patch = mock.patch.object(settings, "CONFIG_FILE", self.config_path)
        self.config_patch.start()

        self.service = FakeService()
        self.server = app.LiteHTTPServer(
            ("127.0.0.1", 0), app.make_handler(self.service, [])
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        host, port = self.server.server_address[:2]
        self.base = f"http://{host}:{port}"
        # Localhost traffic must never go through a system proxy.
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        self.config_patch.stop()
        self.temp.cleanup()

    def request(self, method: str, path: str, payload=None, raw: bytes | None = None):
        data = raw
        headers = {}
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        if data is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            self.base + path, data=data, headers=headers, method=method
        )
        try:
            with self.opener.open(request, timeout=5) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            body = error.read().decode("utf-8")
            return error.code, json.loads(body) if body else {}

    # ---- GET ----

    def test_meta_exposes_only_consumed_fields(self) -> None:
        status, body = self.request("GET", "/api/meta")
        self.assertEqual(status, 200)
        self.assertEqual(set(body), {"version", "apiVersion", "pid"})
        self.assertEqual(body["version"], VERSION)
        self.assertEqual(body["apiVersion"], API_VERSION)

    def test_settings_get_is_camel_case_only(self) -> None:
        status, body = self.request("GET", "/api/settings")
        self.assertEqual(status, 200)
        self.assertIn("startupAction", body)
        self.assertIn("lastTraining", body)
        # 网页控制台退役后不再输出 snake_case 副本
        self.assertNotIn("startup_action", body)

    def test_state_since_latest_uses_log_cursor(self) -> None:
        status, body = self.request("GET", "/api/state?since=latest")
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "idle")
        self.assertIn(("snapshot", 7), self.service.calls)

    def test_unknown_get_returns_404_with_code(self) -> None:
        status, body = self.request("GET", "/api/nope")
        self.assertEqual(status, 404)
        self.assertEqual(body["code"], "NOT_FOUND")

    # ---- POST ----

    def test_settings_post_persists_and_returns_camel(self) -> None:
        status, body = self.request(
            "POST", "/api/settings", {"startupAction": "auto_run"}
        )
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertEqual(body["settings"]["startupAction"], "auto_run")
        stored = json.loads(self.config_path.read_text(encoding="utf-8"))
        self.assertEqual(stored["automation"]["startup_action"], "auto_run")

    def test_note_is_written_with_prefix(self) -> None:
        status, body = self.request(
            "POST", "/api/note", {"message": "保存失败", "level": "error"}
        )
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertIn(("note", "界面：保存失败", "error"), self.service.calls)

    def test_note_rejects_empty_message(self) -> None:
        status, body = self.request("POST", "/api/note", {"message": "   "})
        self.assertEqual(status, 200)
        self.assertFalse(body["ok"])
        self.assertFalse([call for call in self.service.calls if call[0] == "note"])

    def test_invalid_json_returns_bad_json(self) -> None:
        status, body = self.request("POST", "/api/note", raw=b"{not json")
        self.assertEqual(status, 400)
        self.assertEqual(body["code"], "BAD_JSON")

    def test_start_forwards_selection_and_saves_defaults(self) -> None:
        status, _ = self.request(
            "POST",
            "/api/start",
            {
                "training": "铜钱",
                "dungeon": True,
                "names": ["🔮 观星"],
                "extra": ["🏯 据点日常"],
            },
        )
        self.assertEqual(status, 200)
        call = next(item for item in self.service.calls if item[0] == "start_daily")
        kwargs = call[1]
        self.assertEqual(kwargs["training"], "铜钱")
        self.assertTrue(kwargs["include_dungeon"])
        self.assertEqual(kwargs["names"], ["🔮 观星"])
        self.assertEqual(kwargs["extra"], ["🏯 据点日常"])

    def test_start_rejects_empty_selection_as_bad_selection(self) -> None:
        self.service.start_error = ValueError("没有选中任何任务")
        status, body = self.request(
            "POST", "/api/start", {"training": "修为", "names": []}
        )
        self.assertEqual(status, 400)
        self.assertEqual(body["code"], "BAD_SELECTION")

    def test_start_when_busy_returns_409(self) -> None:
        self.service.start_result = False
        status, body = self.request("POST", "/api/start", {"training": "修为"})
        self.assertEqual(status, 409)
        self.assertEqual(body["code"], "BUSY")

    def test_run_task_accepts_single_name_and_reports_unknown(self) -> None:
        self.service.sequence_error = ValueError("未知任务：X")
        status, body = self.request("POST", "/api/run-task", {"name": "X"})
        self.assertEqual(status, 400)
        self.assertEqual(body["code"], "TASK_UNKNOWN")
        call = next(item for item in self.service.calls if item[0] == "run_sequence")
        self.assertEqual(call[1], ["X"])

    def test_unknown_post_returns_404(self) -> None:
        status, body = self.request("POST", "/api/nope", {})
        self.assertEqual(status, 404)
        self.assertEqual(body["code"], "NOT_FOUND")


if __name__ == "__main__":
    unittest.main()
