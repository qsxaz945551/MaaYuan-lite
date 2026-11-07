"""HTTP routes for the Lite control service.

Kept separate from ``app.py`` so the composition root stays readable and the
routes can be exercised by ``lite/tests/test_http_api.py`` without importing the
whole bootstrap. ``make_handler`` still closes over ``service`` / ``server_ref``;
moving the class out of the function would have dragged six boot helpers along.
"""

from __future__ import annotations

import json
import os
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from typing import Any
from urllib.parse import parse_qs, urlparse

from .constants import DEFAULT_TRAINING
from .daily_plan import (
    build_plan,
    daily_task_names,
    load_profile,
    seasonal_default_enabled,
)
from .http_body import read_body
from .resource_boot import ROOT, bundle_owns_resources, load_interface, rebuild_interface
from .run_service import RunService
from .settings import from_wire, load_settings, save_settings, to_wire
from .task_options_service import (
    DEFAULT_INPUTS,
    DEFAULT_SELECTION,
    apply_change,
    describe_tasks,
    load_inputs,
    load_selection,
    write_json,
)
from .version import API_VERSION, VERSION

APP_VERSION = VERSION
OPTION_LOCK = threading.Lock()
_HEALTH_CACHE: dict[str, Any] = {"at": 0.0, "data": None}


def make_handler(service: RunService, server_ref: list):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            return

        def _json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK):
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _error(self, code: str, message: str, status: HTTPStatus) -> None:
            """Stable machine code + human message.

            ``error`` keeps its string form so the existing HTML console keeps
            working; ``code`` is what the WPF client branches on.
            """
            self._json({"ok": False, "error": message, "code": code}, status)

        def _sse(self, service: RunService) -> None:
            """Server-sent events: status + new log lines, one event per second.

            The JSON payload mirrors /api/state for the fields a client needs to
            update live; tasks are still fetched from /api/state because they
            change rarely and the array is large.
            """
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            cursor = service.log_cursor()
            last_ping = time.monotonic()
            try:
                while True:
                    snapshot = service.snapshot(cursor)
                    logs = snapshot.get("logs") or []
                    payload = {
                        "status": snapshot.get("status"),
                        "currentTask": snapshot.get("currentTask"),
                        "summary": snapshot.get("summary"),
                        "logSeq": snapshot.get("logSeq"),
                        "logs": logs,
                    }
                    body = json.dumps(payload, ensure_ascii=False)
                    self.wfile.write(f"event: state\ndata: {body}\n\n".encode("utf-8"))
                    self.wfile.flush()
                    if logs:
                        cursor = int(snapshot.get("logSeq") or cursor)
                    if time.monotonic() - last_ping > 15:
                        self.wfile.write(b": ping\n\n")
                        self.wfile.flush()
                        last_ping = time.monotonic()
                    time.sleep(1.0)
            except (BrokenPipeError, ConnectionResetError, OSError):
                return
            finally:
                self.close_connection = True

        def _read_json(self) -> dict:
            raw = read_body(self.rfile, self.headers)
            if not raw:
                return {}
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError as error:
                # 编码错是另一类问题；JSON 语法错要让它落到 BAD_JSON 分支，
                # 否则客户端只能拿到笼统的 BAD_REQUEST。
                raise ValueError(f"请求体不是合法 UTF-8：{error}") from error
            return json.loads(text)

        # 路由表：do_GET / do_POST 只负责分发。每个分支原来挤在 375 行里，
        # 改一个路由要在几百行里找位置；拆出来后行为完全不变，测试按路径点。
        def do_GET(self):
            parsed = urlparse(self.path)
            routes = {
                "/api/state": self._get_state,
                "/api/plan": self._get_plan,
                "/api/events": self._get_events,
                "/api/updates": self._get_updates,
                "/api/health": self._get_health,
                "/api/meta": self._get_meta,
                "/api/settings": self._get_settings,
                "/api/task-options": self._get_task_options,
                "/api/screenshot": self._get_screenshot,
            }
            route = routes.get(parsed.path)
            if route is None:
                self._error("NOT_FOUND", "接口不存在", HTTPStatus.NOT_FOUND)
                return
            route(parsed)

        def _get_state(self, parsed) -> None:
            query = parse_qs(parsed.query)
            raw_since = query.get("since", ["0"])[0]
            if raw_since == "latest":
                since = service.log_cursor()
            else:
                try:
                    since = int(raw_since)
                except ValueError:
                    since = 0
            self._json(service.snapshot(since))

        def _get_plan(self, parsed) -> None:
            query = parse_qs(parsed.query)
            training = query.get("training", [DEFAULT_TRAINING])[0]
            dungeon_raw = query.get("dungeon")
            dungeon = (
                seasonal_default_enabled()
                if dungeon_raw is None
                else dungeon_raw[0] != "0"
            )
            try:
                plan = build_plan(
                    load_profile(), training=training, include_seasonal=dungeon
                )
                self._json(plan)
            except Exception as error:
                self._error("PLAN_FAILED", str(error), HTTPStatus.BAD_REQUEST)

        def _get_events(self, parsed) -> None:
            self._sse(service)

        def _get_updates(self, parsed) -> None:
            query = parse_qs(parsed.query)
            force = query.get("refresh", ["0"])[0] == "1"
            from lite import downloader
            from lite.update_applier import has_staged
            from lite.updater import check_updates

            data = check_updates(ROOT, force=force)
            data["download"] = downloader.state()
            data["staged"] = has_staged(ROOT)
            self._json(data)

        def _get_health(self, parsed) -> None:
            query = parse_qs(parsed.query)
            force = query.get("refresh", ["0"])[0] == "1"
            now = time.time()
            if (
                force
                or _HEALTH_CACHE["data"] is None
                or now - float(_HEALTH_CACHE["at"]) > 30
            ):
                from lite.selftest import collect

                _HEALTH_CACHE["data"] = collect(ROOT, service.config)
                _HEALTH_CACHE["at"] = now
            self._json(_HEALTH_CACHE["data"])

        def _get_meta(self, parsed) -> None:
            self._json(
                {
                    "version": APP_VERSION,
                    "apiVersion": API_VERSION,
                    # 稳定性脚本（devtools/smoke/stability_run.py）用它给自己的
                    # 进程采句柄与内存，省掉从 netstat 反查 PID 的脆弱路径。
                    "pid": os.getpid(),
                }
            )

        def _get_settings(self, parsed) -> None:
            self._json(to_wire(load_settings()))

        def _get_task_options(self, parsed) -> None:
            query = parse_qs(parsed.query)
            scope = query.get("scope", ["daily"])[0]
            try:
                interface = load_interface()
                profile = load_profile()
                hidden = list(profile.get("hidden_in_library") or [])
                pinned = list(profile.get("pinned_in_library") or [])
                if scope == "all":
                    names = [
                        task["name"]
                        for task in interface["task"]
                        if task.get("entry") != "stop"
                    ]
                else:
                    scope = "daily"
                    names = daily_task_names()
                self._json(
                    {
                        "scope": scope,
                        "tasks": describe_tasks(
                            interface, names, load_selection(), load_inputs()
                        ),
                        "hidden": hidden,
                        "pinned": pinned,
                    }
                )
            except Exception as error:
                self._error("OPTIONS_FAILED", str(error), HTTPStatus.BAD_REQUEST)

        def _get_screenshot(self, parsed) -> None:
            if service._last_screenshot.is_file():
                body = service._last_screenshot.read_bytes()
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
            else:
                self._error("NO_SCREENSHOT", "还没有截图", HTTPStatus.NOT_FOUND)

        def do_POST(self):
            parsed = urlparse(self.path)
            routes = {
                "/api/note": self._post_note,
                "/api/task-options": self._post_task_options,
                "/api/settings": self._post_settings,
                "/api/run-task": self._post_run_task,
                "/api/start": self._post_start,
                "/api/updates/download": self._post_download,
                "/api/updates/apply": self._post_apply,
                "/api/updates/rollback": self._post_rollback,
                "/api/check": self._post_check,
                "/api/stop": self._post_stop,
                "/api/exit": self._post_exit,
            }
            try:
                payload = self._read_json()
                route = routes.get(parsed.path)
                if route is None:
                    self._error("NOT_FOUND", "接口不存在", HTTPStatus.NOT_FOUND)
                    return
                route(payload)
            except json.JSONDecodeError as error:
                self._error(
                    "BAD_JSON", f"请求体不是合法 JSON：{error}", HTTPStatus.BAD_REQUEST
                )
            except Exception as error:
                self._error("BAD_REQUEST", str(error), HTTPStatus.BAD_REQUEST)

        def _post_note(self, payload: dict) -> None:
            # 即时提示行会被下一次操作覆盖；失败提示要留一条运行日志，
            # 前缀「界面：」用来和运行事件区分开。
            message = str(payload.get("message") or "").strip()
            level = str(payload.get("level") or "warn")
            if level not in {"info", "warn", "error"}:
                level = "warn"
            if message:
                service.note(f"界面：{message}", level)
            self._json({"ok": bool(message)})

        def _post_task_options(self, payload: dict) -> None:
            with OPTION_LOCK:
                interface = load_interface()
                selection = load_selection()
                inputs = load_inputs()
                selection, inputs = apply_change(
                    interface, payload, selection, inputs
                )
                write_json(DEFAULT_SELECTION, selection)
                group = interface.get("option", {}).get(payload.get("group"), {})
                if group.get("type") == "input":
                    write_json(DEFAULT_INPUTS, inputs)
                updated = describe_tasks(
                    interface, [payload.get("task")], selection, inputs
                )
            self._json({"ok": True, "task": updated[0] if updated else None})

        def _post_settings(self, payload: dict) -> None:
            patch = from_wire(payload) if isinstance(payload, dict) else {}
            self._json({"ok": True, "settings": to_wire(save_settings(patch))})

        def _post_run_task(self, payload: dict) -> None:
            names = payload.get("names")
            if not isinstance(names, list):
                names = [str(payload.get("name", ""))]
            names = [str(name) for name in names if str(name).strip()]
            try:
                started = service.run_sequence(names)
            except ValueError as error:
                self._error("TASK_UNKNOWN", str(error), HTTPStatus.BAD_REQUEST)
                return
            if not started:
                self._error("BUSY", "已有任务在运行", HTTPStatus.CONFLICT)
                return
            self._json({"ok": True})

        def _post_start(self, payload: dict) -> None:
            dungeon_value = payload.get("dungeon")
            # 界面可以只跑勾选的子集；不传 names 就是整条日常（旧行为）。
            raw_names = payload.get("names")
            names = (
                [str(name) for name in raw_names if str(name).strip()]
                if isinstance(raw_names, list)
                else None
            )
            # 「其他任务」的勾选：和日常一起提交，接在计划末尾执行。
            raw_extra = payload.get("extra")
            extra = (
                [str(name) for name in raw_extra if str(name).strip()]
                if isinstance(raw_extra, list)
                else None
            )
            try:
                started = service.start_daily(
                    training=str(payload.get("training", DEFAULT_TRAINING)),
                    include_dungeon=(
                        seasonal_default_enabled()
                        if dungeon_value is None
                        else bool(dungeon_value)
                    ),
                    resume=bool(payload.get("resume", False)),
                    names=names,
                    extra=extra,
                )
            except ValueError as error:
                self._error("BAD_SELECTION", str(error), HTTPStatus.BAD_REQUEST)
                return
            if started and not payload.get("resume"):
                save_settings(
                    {
                        "last_training": str(
                            payload.get("training", DEFAULT_TRAINING)
                        ),
                        "last_dungeon": bool(dungeon_value),
                    }
                )
            if not started:
                self._error("BUSY", "已有任务在运行", HTTPStatus.CONFLICT)
                return
            self._json({"ok": True})

        def _post_download(self, payload: dict) -> None:
            from lite.downloader import start as start_download

            result = start_download(ROOT, sha=str(payload.get("sha") or ""))
            self._json(
                result,
                HTTPStatus.OK if result.get("started") else HTTPStatus.CONFLICT,
            )

        def _post_apply(self, payload: dict) -> None:
            from lite.update_applier import apply_staged

            if not bundle_owns_resources(service.config):
                self._error(
                    "DEV_MANAGED",
                    "当前资源来自开发目录，自动切换只对发布包生效",
                    HTTPStatus.CONFLICT,
                )
                return
            if service.snapshot().get("busy"):
                self._error("BUSY", "任务运行中，停止后再切换资源", HTTPStatus.CONFLICT)
                return
            result = apply_staged(ROOT, str(service.config.get("interface_source", "")))
            if result.get("ok"):
                built, detail = rebuild_interface()
                result["interfaceRebuilt"] = built
                if not built:
                    from lite.update_applier import rollback

                    result = {
                        "ok": False,
                        "error": f"新资源无法生成 interface，已回滚：{detail}",
                        "code": "APPLY_REJECTED",
                        "rolledBack": rollback(ROOT),
                    }
                    rebuild_interface()
            if not result.get("ok"):
                result.setdefault("code", "APPLY_FAILED")
            self._json(
                result, HTTPStatus.OK if result.get("ok") else HTTPStatus.BAD_REQUEST
            )

        def _post_rollback(self, payload: dict) -> None:
            from lite.update_applier import rollback

            if not bundle_owns_resources(service.config):
                self._error(
                    "DEV_MANAGED", "当前资源来自开发目录，无需回滚", HTTPStatus.CONFLICT
                )
                return
            if service.snapshot().get("busy"):
                self._error("BUSY", "任务运行中，停止后再回滚", HTTPStatus.CONFLICT)
                return
            ok = rollback(ROOT)
            if not ok:
                self._error(
                    "ROLLBACK_FAILED", "没有可回滚的备份", HTTPStatus.BAD_REQUEST
                )
                return
            rebuild_interface()
            self._json({"ok": True})

        def _post_check(self, payload: dict) -> None:
            started = service.check_connection()
            if not started:
                self._error(
                    "BUSY", "已有任务在运行，无法检查连接", HTTPStatus.CONFLICT
                )
                return
            self._json({"ok": True})

        def _post_stop(self, payload: dict) -> None:
            service.stop()
            self._json({"ok": True})

        def _post_exit(self, payload: dict) -> None:
            self._json({"ok": True})
            threading.Thread(target=server_ref[0].shutdown, daemon=True).start()

    return Handler
