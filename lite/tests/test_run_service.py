from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from lite.run_service import RunService


ROOT = Path(__file__).resolve().parents[2]


class FakeSession:
    probe_ok = True
    device_ok = True
    agent_ok = True
    agent_calls = 0
    agent_die_at_call = 0
    restart_count = 0
    fail_entries: set[str] = set()
    timeout_entries: set[str] = set()
    node_events: dict[str, list[str]] = {}
    node_start_events: dict[str, list[str]] = {}
    step_texts: dict[str, str] = {}
    instances: list["FakeSession"] = []

    def __init__(self, **kwargs):
        self.calls: list[str] = []
        self.stopped = False
        self._node_callback = None
        self._node_start_callback = None
        self._step_callback = None
        FakeSession.instances.append(self)

    def start(self, connect_timeout: float = 30.0) -> None:
        return None

    def stop(self) -> None:
        self.stopped = True

    def set_node_callback(self, callback) -> None:
        self._node_callback = callback

    def set_node_start_callback(self, callback) -> None:
        self._node_start_callback = callback

    def set_step_callback(self, callback) -> None:
        self._step_callback = callback

    def device_ready(self) -> bool:
        return FakeSession.device_ok

    def reconnect(self, attempts: int = 3, delay: float = 3.0) -> bool:
        return FakeSession.device_ok

    def agent_alive(self) -> bool:
        FakeSession.agent_calls += 1
        if (
            FakeSession.agent_die_at_call
            and FakeSession.agent_calls >= FakeSession.agent_die_at_call
        ):
            return False
        return FakeSession.agent_ok

    def restart_agent(self, connect_timeout: float = 30.0) -> bool:
        FakeSession.restart_count += 1
        return FakeSession.agent_ok

    def probe(self, checks, timeout_ms: int = 1500) -> bool:
        return FakeSession.probe_ok

    def capture_png(self, output):
        return output

    def run_task(
        self,
        entry,
        pipeline_override=None,
        timeout_sec=900,
        retries=0,
        should_stop=None,
        agent_check=None,
        stall_check=None,
    ):
        self.calls.append(entry)
        for node in FakeSession.node_events.get(entry, []):
            if self._node_callback is not None:
                self._node_callback(node)
        for node in FakeSession.node_start_events.get(entry, []):
            if self._node_start_callback is not None:
                self._node_start_callback(node)
            if self._step_callback is not None:
                self._step_callback(node, FakeSession.step_texts.get(node))
        if should_stop is not None and should_stop():
            return {
                "entry": entry,
                "success": False,
                "timed_out": False,
                "cancelled": True,
                "agent_died": False,
                "attempt": 1,
                "attempts": 1,
            }
        if agent_check is not None and not agent_check():
            return {
                "entry": entry,
                "success": False,
                "timed_out": False,
                "cancelled": False,
                "agent_died": True,
                "attempt": 1,
                "attempts": 1,
            }
        timed_out = entry in FakeSession.timeout_entries
        succeeded = entry not in FakeSession.fail_entries and not timed_out
        return {
            "entry": entry,
            "success": succeeded,
            "timed_out": timed_out,
            "cancelled": False,
            "agent_died": False,
            "attempt": 1,
            "attempts": 1,
        }


def entry_map() -> dict[str, str]:
    interface = json.loads(
        (ROOT / "build" / "generated" / "interface.json").read_text(encoding="utf-8")
    )
    return {task["name"]: task["entry"] for task in interface["task"]}


class RunServiceTest(unittest.TestCase):
    def setUp(self):
        FakeSession.probe_ok = True
        FakeSession.device_ok = True
        FakeSession.agent_ok = True
        FakeSession.agent_calls = 0
        FakeSession.agent_die_at_call = 0
        FakeSession.restart_count = 0
        FakeSession.fail_entries = set()
        FakeSession.timeout_entries = set()
        FakeSession.node_events = {}
        FakeSession.node_start_events = {}
        FakeSession.step_texts = {}
        FakeSession.instances = []
        self.entries = entry_map()

        # Isolated project root so runtime/last-run.json never touches the real one.
        # 把「现在」钉在上午：每日进膳 16:00 后才入链，否则测试结果随采样时刻漂移。
        import lite.run_service as _rs
        from lite.daily_plan import build_plan as _build_plan

        self._plan_patch = mock.patch(
            "lite.run_service.build_plan",
            lambda profile, **kwargs: _build_plan(
                profile, now=datetime(2026, 11, 7, 9, 0), **kwargs
            ),
        )
        self._plan_patch.start()
        self._rs = _rs

        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "build" / "generated").mkdir(parents=True)
        shutil.copy(
            ROOT / "build" / "generated" / "interface.json",
            self.root / "build" / "generated" / "interface.json",
        )
        self.config = {
            "runtime_root": str(ROOT),
            "adb_path": str(ROOT / "adb.exe"),
            "adb_serial": "emulator-5554",
            "resource_path": "assets/resource/base",
        }

    def tearDown(self):
        self._plan_patch.stop()
        self._tmp.cleanup()

    def run_daily(self, service: RunService, **kwargs) -> None:
        self.assertTrue(service.start_daily(**kwargs))
        service._thread.join(30)
        self.assertFalse(service._thread.is_alive())

    def test_snapshot_returns_incremental_logs(self):
        service = RunService(self.root, self.config)
        service._reset_logs()
        service._log("a")
        service._log("b")

        full = service.snapshot(0)
        self.assertEqual([line["message"] for line in full["logs"]], ["a", "b"])
        self.assertEqual(full["logSeq"], 2)

        partial = service.snapshot(1)
        self.assertEqual([line["message"] for line in partial["logs"]], ["b"])

        service._log("c")
        self.assertEqual(
            [line["message"] for line in service.snapshot(2)["logs"]], ["c"]
        )

        # Client counter ahead of the server (process restart) -> full resend.
        ahead = service.snapshot(99)
        self.assertEqual(len(ahead["logs"]), 3)

        # Starting a new run keeps the previous lines and appends a separator.
        run_before = service.snapshot(0)["runId"]
        service._reset_logs()
        reset = service.snapshot(0)
        self.assertEqual(reset["runId"], run_before)
        self.assertEqual(reset["logSeq"], 4)
        self.assertEqual(
            [line["message"] for line in reset["logs"]],
            ["a", "b", "c", "—— 新的一次运行 ——"],
        )

    def test_step_handler_feeds_snapshot_and_clears(self):
        service = RunService(self.root, self.config)
        self.assertIsNone(service.snapshot(0)["step"])

        handler = service._make_step_handler("🔶 日常收尾")
        handler("领取密探特训奖励启动", "开始领取密探特训奖励")
        step = service.snapshot(0)["step"]
        self.assertEqual(step["task"], "🔶 日常收尾")
        self.assertEqual(step["node"], "领取密探特训奖励启动")
        self.assertEqual(step["label"], "开始领取密探特训奖励")
        self.assertTrue(step["focus"])
        self.assertTrue(step["at"])

        # Nodes without focus fall back to their name, flagged for the UI.
        handler("检测点击_前往收集", None)
        step = service.snapshot(0)["step"]
        self.assertEqual(step["label"], "检测点击_前往收集")
        self.assertFalse(step["focus"])

        service._clear_step()
        self.assertIsNone(service.snapshot(0)["step"])

    def test_run_publishes_step_during_task(self):
        """_execute_job must wire the step callback, not just define a handler."""
        service = RunService(self.root, self.config)
        name = "🗡 白鹄扫荡"
        entry = self.entries[name]
        FakeSession.node_start_events = {entry: ["准备扫荡"]}
        FakeSession.step_texts = {"准备扫荡": "开始扫荡"}
        # Keep the value around after the run so the last step is observable;
        # in production it is cleared as soon as the task ends.
        service._clear_step = lambda: None

        with mock.patch("lite.run_service.LiteSession", FakeSession):
            self.assertTrue(service.run_single(name))
            service._thread.join(30)

        step = service.snapshot(0)["step"]
        self.assertIsNotNone(step)
        self.assertEqual(step["task"], name)
        self.assertEqual(step["node"], "准备扫荡")
        self.assertEqual(step["label"], "开始扫荡")
        self.assertTrue(step["focus"])

    def test_log_cursor_skips_existing_history(self):
        service = RunService(self.root, self.config)
        service._reset_logs()
        service._log("a")
        service._log("b")
        cursor = service.log_cursor()
        self.assertEqual(service.snapshot(cursor)["logs"], [])
        service._log("c")
        self.assertEqual(
            [line["message"] for line in service.snapshot(cursor)["logs"]], ["c"]
        )

    def test_node_loop_guard_stops_task(self):
        service = RunService(self.root, self.config)
        name = "🗡 白鹄扫荡"
        entry = self.entries[name]
        FakeSession.node_start_events = {entry: ["卡住的节点"] * 130}
        with mock.patch("lite.run_service.LiteSession", FakeSession):
            self.assertTrue(service.run_single(name))
            service._thread.join(30)

        state = service.snapshot()
        self.assertEqual(state["single"]["results"][0]["status"], "failed")
        messages = [line["message"] for line in state["logs"]]
        self.assertTrue(any("疑似死循环" in m for m in messages))

    def test_agent_death_restarts_and_continues(self):
        service = RunService(self.root, self.config)
        FakeSession.agent_die_at_call = 2
        with mock.patch("lite.run_service.LiteSession", FakeSession):
            self.assertTrue(service.run_single("🔮 观星"))
            service._thread.join(30)

        state = service.snapshot()
        self.assertEqual(state["single"]["results"][0]["status"], "failed")
        messages = [line["message"] for line in state["logs"]]
        self.assertTrue(any("Agent 异常退出" in m for m in messages))
        self.assertTrue(any("Agent 已重启" in m for m in messages))
        self.assertEqual(FakeSession.restart_count, 1)

    def test_adb_loss_stops_run(self):
        service = RunService(self.root, self.config)
        FakeSession.device_ok = False
        with mock.patch("lite.run_service.LiteSession", FakeSession):
            self.assertTrue(service.run_single("🔮 观星"))
            service._thread.join(30)

        state = service.snapshot()
        self.assertEqual(state["status"], "error")
        messages = [line["message"] for line in state["logs"]]
        self.assertTrue(any("重连失败" in m for m in messages))

    def test_loop_task_logs_one_line_per_round(self):
        service = RunService(self.root, self.config)
        name = "🔄 6-24/7-15 刷到体力耗尽"
        entry = self.entries[name]
        FakeSession.node_events = {
            entry: ["战斗结束", "无关节点", "战斗结束", "战斗结束"]
        }
        with mock.patch("lite.run_service.LiteSession", FakeSession):
            self.assertTrue(service.run_single(name))
            service._thread.join(30)

        messages = [line["message"] for line in service.snapshot(0)["logs"]]
        rounds = [m for m in messages if m.startswith("第 ")]
        self.assertEqual(
            rounds,
            ["第 1 轮完成（战斗）", "第 2 轮完成（战斗）", "第 3 轮完成（战斗）"],
        )

    def test_single_run_keeps_daily_progress(self):
        service = RunService(self.root, self.config)
        with mock.patch("lite.run_service.LiteSession", FakeSession):
            self.run_daily(service, training="修为", include_dungeon=False)
            before = service.snapshot()
            self.assertEqual(before["summary"], {"succeeded": 8, "failed": 0, "skipped": 0})

            target = "🔮 观星"
            self.assertTrue(service.run_single(target))
            service._thread.join(30)

        state = service.snapshot()
        self.assertIsNotNone(state["single"])
        self.assertEqual(state["single"]["name"], target)
        self.assertEqual(state["single"]["status"], "succeeded")
        self.assertEqual([task["status"] for task in state["tasks"]], ["succeeded"] * 8)
        self.assertFalse(state["canResume"])
        self.assertEqual(FakeSession.instances[-1].calls, [self.entries[target]])

    def test_sequence_runs_tasks_in_order(self):
        service = RunService(self.root, self.config)
        names = ["🎲 爱乐之村", "🔮 观星"]
        with mock.patch("lite.run_service.LiteSession", FakeSession):
            self.assertTrue(service.run_sequence(names))
            service._thread.join(30)

        state = service.snapshot()
        self.assertEqual(state["single"]["total"], 2)
        self.assertEqual(
            [item["name"] for item in state["single"]["results"]], names
        )
        self.assertEqual(FakeSession.instances[-1].calls, [self.entries[n] for n in names])
        self.assertEqual(state["status"], "completed")

    def test_timeout_is_reported_separately(self):
        watch = self.entries["🔮 观星"]
        FakeSession.timeout_entries = {watch}
        service = RunService(self.root, self.config)
        with mock.patch("lite.run_service.LiteSession", FakeSession):
            self.run_daily(service, training="修为", include_dungeon=False)

        state = service.snapshot()
        statuses = {task["name"]: task["status"] for task in state["tasks"]}
        self.assertEqual(statuses["🔮 观星"], "timed_out")
        self.assertEqual(state["summary"]["failed"], 1)
        self.assertTrue(state["canResume"])

    def test_unknown_single_task_is_rejected(self):
        service = RunService(self.root, self.config)
        with self.assertRaises(ValueError):
            service.run_single("不存在的任务")

    def test_clean_run_has_nothing_to_resume(self):
        service = RunService(self.root, self.config)
        with mock.patch("lite.run_service.LiteSession", FakeSession):
            self.run_daily(service, training="修为", include_dungeon=False)

        state = service.snapshot()
        self.assertEqual(state["status"], "completed")
        self.assertEqual(state["summary"], {"succeeded": 8, "failed": 0, "skipped": 0})
        self.assertFalse(state["canResume"])

        restarted = RunService(self.root, self.config)
        restored = restarted.snapshot()
        self.assertEqual(restored["status"], "completed")
        self.assertFalse(restored["canResume"])

    def test_probe_miss_skips_dungeon_without_failing(self):
        FakeSession.probe_ok = False
        service = RunService(self.root, self.config)
        with mock.patch("lite.run_service.LiteSession", FakeSession):
            self.run_daily(service, training="修为", include_dungeon=True)

        state = service.snapshot()
        statuses = {task["name"]: task["status"] for task in state["tasks"]}
        self.assertEqual(statuses["🗡 地宫助手"], "skipped")
        # 界面上要能看出"为什么跳过"：开关是持久化的，不标注用户不会想到去关它。
        notes = {task["name"]: task.get("note", "") for task in state["tasks"]}
        self.assertEqual(notes["🗡 地宫助手"], "本期未开放")
        self.assertEqual(state["status"], "completed")
        self.assertEqual(state["summary"]["failed"], 0)
        self.assertFalse(state["canResume"])
        self.assertNotIn(self.entries["🗡 地宫助手"], FakeSession.instances[-1].calls)

    def test_only_selected_daily_tasks_run(self):
        """界面勾选哪几项就只跑哪几项，顺序仍按日常链。"""
        service = RunService(self.root, self.config)
        picked = ["🔮 观星", "🔶 日常收尾"]
        with mock.patch("lite.run_service.LiteSession", FakeSession):
            self.run_daily(
                service, training="修为", include_dungeon=False, names=picked
            )

        self.assertEqual(
            FakeSession.instances[-1].calls, [self.entries[name] for name in picked]
        )
        self.assertEqual(
            [task["name"] for task in service.snapshot()["tasks"]], picked
        )

    def test_extra_tasks_run_after_the_daily_selection(self):
        """一个按钮：先按日常顺序跑勾选的日常，再跑「其他任务」的勾选。"""
        service = RunService(self.root, self.config)
        with mock.patch("lite.run_service.LiteSession", FakeSession):
            self.run_daily(
                service,
                training="修为",
                include_dungeon=False,
                names=["🔮 观星"],
                extra=["🏯 据点日常"],
            )

        self.assertEqual(
            FakeSession.instances[-1].calls,
            [self.entries["🔮 观星"], self.entries["🏯 据点日常"]],
        )
        self.assertEqual(
            [(task["name"], task["kind"]) for task in service.snapshot()["tasks"]],
            [("🔮 观星", "daily"), ("🏯 据点日常", "extra")],
        )
        self.assertEqual(service.snapshot()["summary"]["failed"], 0)

    def test_extra_only_selection_is_allowed(self):
        """只勾了「其他任务」时不该被拒绝，也不该跑整条日常。"""
        service = RunService(self.root, self.config)
        with mock.patch("lite.run_service.LiteSession", FakeSession):
            self.run_daily(
                service,
                training="修为",
                include_dungeon=False,
                names=[],
                extra=["🏯 据点日常"],
            )

        self.assertEqual(
            FakeSession.instances[-1].calls, [self.entries["🏯 据点日常"]]
        )

    def test_extra_duplicating_a_daily_task_runs_once(self):
        service = RunService(self.root, self.config)
        with mock.patch("lite.run_service.LiteSession", FakeSession):
            self.run_daily(
                service,
                training="修为",
                include_dungeon=False,
                names=["🔮 观星"],
                extra=["🔮 观星"],
            )

        self.assertEqual(
            FakeSession.instances[-1].calls, [self.entries["🔮 观星"]]
        )

    def test_empty_selection_is_rejected(self):
        service = RunService(self.root, self.config)
        with self.assertRaises(ValueError):
            service.start_daily("修为", False, names=[])

    def test_resume_reruns_only_unfinished_tasks(self):
        watch = self.entries["🔮 观星"]
        FakeSession.fail_entries = {watch}
        service = RunService(self.root, self.config)
        with mock.patch("lite.run_service.LiteSession", FakeSession):
            self.run_daily(service, training="修为", include_dungeon=False)
            self.assertTrue(service.snapshot()["canResume"])

            FakeSession.fail_entries = set()
            self.run_daily(
                service, training="修为", include_dungeon=False, resume=True
            )

        self.assertEqual(FakeSession.instances[-1].calls, [watch])
        state = service.snapshot()
        self.assertEqual(state["status"], "completed")
        self.assertEqual(state["summary"], {"succeeded": 8, "failed": 0, "skipped": 0})

    def test_unfinished_run_survives_restart(self):
        watch = self.entries["🔮 观星"]
        FakeSession.fail_entries = {watch}
        service = RunService(self.root, self.config)
        with mock.patch("lite.run_service.LiteSession", FakeSession):
            self.run_daily(service, training="修为", include_dungeon=False)

        # Simulate closing and reopening the control panel.
        restarted = RunService(self.root, self.config)
        state = restarted.snapshot()
        self.assertEqual(state["status"], "interrupted")
        self.assertTrue(state["canResume"])
        statuses = {task["name"]: task["status"] for task in state["tasks"]}
        self.assertEqual(statuses["🔮 观星"], "failed")
        self.assertEqual(statuses["🚀 启动游戏"], "succeeded")

        FakeSession.fail_entries = set()
        with mock.patch("lite.run_service.LiteSession", FakeSession):
            self.run_daily(
                restarted, training="修为", include_dungeon=False, resume=True
            )

        self.assertEqual(FakeSession.instances[-1].calls, [watch])
        self.assertEqual(restarted.snapshot()["summary"], {"succeeded": 8, "failed": 0, "skipped": 0})

    def test_connection_check_keeps_daily_record(self):
        """A connection check must not wipe the record "继续未完成" relies on."""
        service = RunService(self.root, self.config)
        with mock.patch("lite.run_service.LiteSession", FakeSession):
            FakeSession.fail_entries = {self.entries["🔮 观星"]}
            self.run_daily(service, training="修为", include_dungeon=False)

            before = service.snapshot()
            self.assertTrue(before["canResume"])
            statuses = [task["status"] for task in before["tasks"]]
            summary = dict(before["summary"])

            self.assertTrue(service.check_connection())
            service._thread.join(30)
            after = service.snapshot()

        self.assertEqual([task["status"] for task in after["tasks"]], statuses)
        self.assertEqual(after["summary"], summary)
        self.assertTrue(after["canResume"])
        self.assertEqual(after["status"], before["status"])

    def test_stop_during_last_task_marks_run_cancelled(self):
        """Stop pressed while the final task runs must not report 完成."""
        service = RunService(self.root, self.config)
        last_entry = self.entries["🔶 日常收尾"]

        class CancelOnLast(FakeSession):
            def run_task(self, entry, **kwargs):
                result = super().run_task(entry, **kwargs)
                if entry == last_entry:
                    service._cancel.set()
                return result

        with mock.patch("lite.run_service.LiteSession", CancelOnLast):
            self.run_daily(service, training="修为", include_dungeon=False)

        state = service.snapshot()
        self.assertEqual(state["status"], "cancelled")
        self.assertEqual(state["tasks"][-1]["status"], "succeeded")


class StaminaScopeTest(unittest.TestCase):
    """Only farming tasks can end a run by running out of stamina."""

    def test_farming_tasks_are_checked(self) -> None:
        from lite.run_service import _consumes_stamina

        for name in ("💎 修为历练", "💲 铜钱历练", "🗡 白鹄扫荡", "🗡 地宫助手"):
            self.assertTrue(_consumes_stamina(name), name)

    def test_other_tasks_are_not(self) -> None:
        from lite.run_service import _consumes_stamina

        for name in ("🚀 启动游戏", "💰 领月卡福利", "🏯 据点日常", "🔮 观星", "🔶 日常收尾"):
            self.assertFalse(_consumes_stamina(name), name)


if __name__ == "__main__":
    unittest.main()
