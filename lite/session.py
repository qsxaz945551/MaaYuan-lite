"""Reusable MaaFramework session for MaaYuan Lite.

This module deliberately has no UI dependencies. It owns the controller,
resource, tasker and Python Agent lifecycle so the scheduler and UI can stay
small and replaceable.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional


class SessionError(RuntimeError):
    pass


def _make_node_sink(
    on_success: Callable[[str], None],
    on_start: Optional[Callable[[str], None]] = None,
):
    """Build a tasker sink that reports pipeline node starts and successes."""
    from maa.tasker import TaskerEventSink

    class _NodeSink(TaskerEventSink):
        def on_raw_notification(self, tasker, msg: str, details: dict) -> None:
            name = details.get("name")
            if not name:
                return
            if msg == "Node.PipelineNode.Succeeded":
                on_success(str(name))
            elif msg == "Node.PipelineNode.Starting" and on_start is not None:
                on_start(str(name))

    return _NodeSink()


class LiteSession:
    def __init__(
        self,
        project_root: Path,
        maa_root: Path,
        adb_path: Path,
        serial: str = "emulator-5554",
        resource_path: Optional[Path] = None,
        python_executable: Optional[Path] = None,
        agent_root: Optional[Path] = None,
    ) -> None:
        self.project_root = project_root.resolve()
        self.maa_root = maa_root.resolve()
        self.adb_path = adb_path.resolve()
        self.serial = serial
        self.resource_path = (
            resource_path or self.project_root / "assets" / "resource" / "base"
        ).resolve()
        # Agent scripts may live in the upstream install so that resource
        # updates reach Lite without copying them again.
        self.agent_root = (
            Path(agent_root).resolve()
            if agent_root
            else self.project_root / "agent"
        )
        self.python_executable = Path(python_executable or sys.executable)

        self._controller: Any = None
        self._resource: Any = None
        self._tasker: Any = None
        self._agent_client: Any = None
        self._agent_process: Any = None
        self._agent_stdout = None
        self._agent_stderr = None
        self._started = False
        self._node_callback: Optional[Callable[[str], None]] = None
        self._node_start_callback: Optional[Callable[[str], None]] = None
        self._agent_identifier = ""
        self._sink = None
        self._sink_id: Optional[int] = None

        self.native_path = self._find_native()
        self.agent_binary = self._find_agent_binary()
        self.log_dir = self.project_root / "runtime" / "logs"

    @property
    def started(self) -> bool:
        return self._started

    def _find_native(self) -> Path:
        """Locate the MaaFramework native libraries.

        Order matters: a hand-placed ``native/`` wins, then the upstream-style
        ``runtimes/win-x64/native``, then the wheel layout (``maa/bin``) that a
        pip-installed ``maafw`` ships. The last one means the release does not
        need a duplicated 65 MB copy.
        """
        candidates = [
            self.maa_root / "native",
            self.maa_root / "runtimes" / "win-x64" / "native",
        ]
        try:
            spec = importlib.util.find_spec("maa")
            for location in list(spec.submodule_search_locations or []) if spec else []:
                candidates.append(Path(location) / "bin")
        except (ImportError, ValueError):
            pass

        for path in candidates:
            if (path / "MaaFramework.dll").is_file():
                return path
        raise SessionError(
            "MaaFramework native directory not found; looked in: "
            + ", ".join(str(path) for path in candidates)
        )

    def _find_agent_binary(self) -> Path:
        candidates = [
            self.maa_root / "libs" / "MaaAgentBinary",
            self.maa_root / "MaaAgentBinary",
            self.maa_root / "python" / "Lib" / "site-packages" / "MaaAgentBinary",
        ]
        try:
            spec = importlib.util.find_spec("MaaAgentBinary")
            for location in list(spec.submodule_search_locations or []) if spec else []:
                candidates.append(Path(location))
        except (ImportError, ValueError):
            pass
        for candidate in candidates:
            if candidate.is_dir():
                return candidate
        raise SessionError(
            "MaaAgentBinary directory not found; looked in: "
            + ", ".join(str(path) for path in candidates)
        )

    def _validate_assets(self) -> None:
        if not self.native_path.is_dir():
            raise SessionError(f"MaaFramework native directory not found: {self.native_path}")
        if not self.resource_path.is_dir():
            raise SessionError(f"Resource directory not found: {self.resource_path}")
        ocr_dir = self.resource_path / "model" / "ocr"
        required = [ocr_dir / "det.onnx", ocr_dir / "rec.onnx"]
        missing = [str(path) for path in required if not path.is_file()]
        if missing:
            raise SessionError(
                "OCR model is missing; tasks will not recognize text. Missing: "
                + ", ".join(missing)
            )

    def _import_maa(self):
        self._validate_assets()
        os.environ["MAAFW_BINARY_PATH"] = str(self.native_path)

        from maa.agent_client import AgentClient
        from maa.controller import AdbController
        from maa.resource import Resource
        from maa.tasker import Tasker

        return AgentClient, AdbController, Resource, Tasker

    def rotate_logs(
        self, max_maa_log_bytes: int = 20 * 1024 * 1024, keep_archives: int = 3,
        keep_agent_logs: int = 60,
    ) -> list[str]:
        """Keep debug/maa.log and runtime/logs bounded between runs.

        Only files this tool created are touched: ``debug/maa-*.log`` archives
        and ``runtime/logs/agent-*.log``. Returns a short description of what
        happened so the caller can log it.
        """
        actions: list[str] = []
        debug_dir = self.project_root / "debug"
        maa_log = debug_dir / "maa.log"
        try:
            if maa_log.is_file() and maa_log.stat().st_size > max_maa_log_bytes:
                stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
                target = debug_dir / f"maa-{stamp}.log"
                maa_log.rename(target)
                actions.append(f"archived debug/maa.log -> {target.name}")

            archives = sorted(
                debug_dir.glob("maa-*.log"), key=lambda p: p.stat().st_mtime, reverse=True
            )
            for stale in archives[keep_archives:]:
                stale.unlink(missing_ok=True)
                actions.append(f"removed {stale.name}")
        except OSError:
            pass

        try:
            agent_logs = sorted(
                self.log_dir.glob("agent-*.log"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            for stale in agent_logs[keep_agent_logs:]:
                stale.unlink(missing_ok=True)
                actions.append(f"removed runtime/logs/{stale.name}")
        except OSError:
            pass

        try:
            shots = sorted(
                (debug_dir / "on_error").glob("*.png"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            for stale in shots[40:]:
                stale.unlink(missing_ok=True)
                actions.append(f"removed debug/on_error/{stale.name}")
        except OSError:
            pass

        return actions

    def start(self, connect_timeout: float = 30.0) -> None:
        if self._started:
            return

        AgentClient, AdbController, Resource, Tasker = self._import_maa()
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.rotate_logs()

        try:
            self._controller = AdbController(
                adb_path=self.adb_path,
                address=self.serial,
                screencap_methods=4,
                input_methods=1,
                config={},
                agent_path=self.agent_binary,
            )
            connection = self._controller.post_connection().wait()
            if not connection.succeeded:
                # Emulators often need a moment after boot; retry a few times
                # before giving up on the whole run.
                for attempt in range(2, 4):
                    time.sleep(3.0)
                    connection = self._controller.post_connection().wait()
                    if connection.succeeded:
                        break
                if not connection.succeeded:
                    raise SessionError("ADB controller connection failed")

            self._resource = Resource()
            loading = self._resource.post_bundle(self.resource_path).wait()
            if not loading.succeeded:
                raise SessionError("Maa resource loading failed")

            self._tasker = Tasker()
            # Keep a screenshot of the failing recognition in debug/on_error;
            # otherwise a failure only leaves a node name in the log.
            self._tasker.set_save_on_error(True)
            if not self._tasker.bind(self._resource, self._controller):
                raise SessionError("Tasker failed to bind resource/controller")

            self._sink = _make_node_sink(self._handle_node, self._handle_node_start)
            self._sink_id = self._tasker.add_sink(self._sink)

            identifier = f"lite-{os.getpid()}-{int(time.time())}"
            self._agent_identifier = identifier
            self._agent_client = AgentClient(identifier)
            self._agent_client.set_timeout(120000)
            if not self._agent_client.bind(self._resource):
                raise SessionError("Agent failed to bind resource")
            if not self._agent_client.register_sink(
                self._resource, self._controller, self._tasker
            ):
                raise SessionError("Agent failed to register event sinks")

            self._start_agent(identifier)
            self._wait_for_agent(connect_timeout)
            self._started = True
        except Exception:
            self.stop()
            raise

    def _start_agent(self, identifier: str) -> None:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        stdout_path = self.log_dir / f"agent-{stamp}.stdout.log"
        stderr_path = self.log_dir / f"agent-{stamp}.stderr.log"
        self._agent_stdout = stdout_path.open("w", encoding="utf-8")
        self._agent_stderr = stderr_path.open("w", encoding="utf-8")

        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        env["MAAFW_BINARY_PATH"] = str(self.native_path)
        self._agent_process = subprocess.Popen(
            [
                str(self.python_executable),
                "-u",
                str(self.agent_root / "main.py"),
                identifier,
            ],
            cwd=str(self.agent_root),
            env=env,
            stdout=self._agent_stdout,
            stderr=self._agent_stderr,
        )

    def _wait_for_agent(self, timeout: float) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._agent_process is None or self._agent_process.poll() is not None:
                code = None if self._agent_process is None else self._agent_process.returncode
                raise SessionError(f"Agent exited before connecting (code={code})")
            if self._agent_client.connected and self._agent_client.alive:
                return
            if self._agent_client.connect():
                return
            time.sleep(0.25)
        raise SessionError("Agent connection timed out")

    def capture_png(self, output: Path) -> Path:
        if not self._started:
            raise SessionError("Session is not started")
        capture = self._controller.post_screencap().wait()
        if not capture.succeeded:
            raise SessionError("Screenshot capture failed")
        from PIL import Image

        output.parent.mkdir(parents=True, exist_ok=True)
        Image.fromarray(capture.get()).save(output)
        return output

    def probe(
        self,
        checks: list[dict[str, Any]],
        timeout_ms: int = 1500,
    ) -> bool:
        """Read-only screen probe.

        Runs a throwaway pipeline whose nodes only perform recognition and then
        DoNothing, so nothing is clicked and game state is untouched. Returns
        True when at least one check matches the current screen.
        """
        if not self._started:
            raise SessionError("Session is not started")
        if not checks:
            return True

        entry = "lite-probe"
        children: list[str] = []
        budget_ms = max(300, int(timeout_ms))
        override: dict[str, Any] = {
            entry: {
                "recognition": {"type": "DirectHit", "param": {}},
                "action": {"type": "DoNothing", "param": {}},
                "next": children,
                "pre_delay": 0,
                "post_delay": 0,
                # Bound the retry loop: without this the next-list keeps
                # re-checking and burns ~10s on a miss.
                "timeout": budget_ms * len(checks) + 800,
            }
        }
        for index, check in enumerate(checks):
            name = f"lite-probe-{index}"
            children.append(name)
            override[name] = {
                "recognition": check,
                "action": {"type": "DoNothing", "param": {}},
                "pre_delay": 0,
                "post_delay": 0,
                "timeout": budget_ms,
            }

        job = self._tasker.post_task(entry, override)
        deadline = time.monotonic() + (budget_ms * len(checks) + 5000) / 1000.0
        while not job.done:
            if time.monotonic() >= deadline:
                self._tasker.post_stop().wait()
                return False
            time.sleep(0.1)
        return bool(job.succeeded)

    def has_stamina_dialog(self) -> bool:
        """True when the stamina refill dialog is on screen.

        The button band sits around y=527 on a 720x1280 capture, so the probe
        is limited to that strip to avoid matching the words elsewhere in the
        interface.
        """
        return self.probe(
            [
                {
                    "type": "OCR",
                    "param": {
                        "expected": ["用道具回复", "用日金市回复", "体力回复"],
                        "roi": [98, 496, 560, 88],
                    },
                }
            ],
            1200,
        )

    def set_node_callback(self, callback: Optional[Callable[[str], None]]) -> None:
        """Watch succeeded pipeline nodes (used for loop progress counters)."""
        self._node_callback = callback

    def set_node_start_callback(
        self, callback: Optional[Callable[[str], None]]
    ) -> None:
        """Watch node starts (used by the stuck-loop guard)."""
        self._node_start_callback = callback

    def _handle_node(self, name: str) -> None:
        callback = self._node_callback
        if callback is None:
            return
        try:
            callback(name)
        except Exception:
            pass

    def _handle_node_start(self, name: str) -> None:
        callback = self._node_start_callback
        if callback is None:
            return
        try:
            callback(name)
        except Exception:
            pass

    def device_ready(self) -> bool:
        """Cheap ADB check used before each task."""
        try:
            output = subprocess.run(
                [str(self.adb_path), "devices"],
                capture_output=True,
                text=True,
                timeout=8,
                encoding="utf-8",
                errors="ignore",
            ).stdout
        except Exception:
            return False
        for line in output.splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[0] == self.serial and parts[1] == "device":
                return True
        return False

    def reconnect(self, attempts: int = 3, delay: float = 3.0) -> bool:
        """Try to restore the ADB connection after the emulator dropped."""
        if ":" in self.serial:
            try:
                subprocess.run(
                    [str(self.adb_path), "connect", self.serial],
                    capture_output=True,
                    timeout=8,
                )
            except Exception:
                pass
        for attempt in range(attempts):
            if self.device_ready():
                try:
                    if self._controller.post_connection().wait().succeeded:
                        return True
                except Exception:
                    pass
            if attempt < attempts - 1:
                time.sleep(delay)
        return False

    def agent_alive(self) -> bool:
        if not self._started or self._agent_process is None:
            return False
        if self._agent_process.poll() is not None:
            return False
        try:
            return bool(
                self._agent_client
                and self._agent_client.connected
                and self._agent_client.alive
            )
        except Exception:
            return False

    def restart_agent(self, connect_timeout: float = 30.0) -> bool:
        """Restart the Python Agent after it exited unexpectedly."""
        if not self._started or not self._agent_client or not self._agent_identifier:
            return False
        self._stop_agent_process()
        try:
            self._start_agent(self._agent_identifier)
            self._wait_for_agent(connect_timeout)
            return True
        except Exception:
            return False

    def _stop_agent_process(self) -> None:
        if self._agent_process is not None and self._agent_process.poll() is None:
            self._agent_process.terminate()
            try:
                self._agent_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._agent_process.kill()
        self._agent_process = None
        for stream in (self._agent_stdout, self._agent_stderr):
            if stream is not None:
                try:
                    stream.close()
                except Exception:
                    pass
        self._agent_stdout = None
        self._agent_stderr = None

    def request_stop(self) -> None:
        if self._tasker is not None:
            try:
                if self._tasker.running:
                    self._tasker.post_stop()
            except Exception:
                pass

    def run_task(
        self,
        entry: str,
        pipeline_override: Optional[dict[str, Any]] = None,
        timeout_sec: Optional[float] = 900,
        retries: int = 0,
        should_stop: Optional[Callable[[], bool]] = None,
        agent_check: Optional[Callable[[], bool]] = None,
    ) -> dict[str, Any]:
        if not self._started:
            raise SessionError("Session is not started")
        attempts = max(0, retries) + 1
        last_status: Any = None

        for attempt in range(1, attempts + 1):
            job = self._tasker.post_task(entry, pipeline_override or {})
            deadline = (
                None if timeout_sec is None else time.monotonic() + timeout_sec
            )
            timed_out = False
            cancelled = False
            agent_died = False
            next_agent_check = time.monotonic() + 2.0
            while not job.done:
                if should_stop is not None and should_stop():
                    cancelled = True
                    self._tasker.post_stop().wait()
                    break
                if agent_check is not None and time.monotonic() >= next_agent_check:
                    next_agent_check = time.monotonic() + 2.0
                    alive = True
                    try:
                        alive = bool(agent_check())
                    except Exception:
                        alive = True
                    if not alive:
                        # Custom actions cannot run without the agent; stop the
                        # task so the caller can restart the agent and move on.
                        agent_died = True
                        self._tasker.post_stop().wait()
                        break
                if deadline is not None and time.monotonic() >= deadline:
                    timed_out = True
                    self._tasker.post_stop().wait()
                    break
                time.sleep(0.25)

            last_status = job.status
            if cancelled:
                return {
                    "entry": entry,
                    "success": False,
                    "timed_out": False,
                    "cancelled": True,
                    "agent_died": False,
                    "attempt": attempt,
                    "attempts": attempts,
                }
            if agent_died:
                return {
                    "entry": entry,
                    "success": False,
                    "timed_out": False,
                    "cancelled": False,
                    "agent_died": True,
                    "attempt": attempt,
                    "attempts": attempts,
                }
            if timed_out:
                result = {
                    "entry": entry,
                    "success": False,
                    "timed_out": True,
                    "cancelled": False,
                    "agent_died": False,
                    "attempt": attempt,
                    "attempts": attempts,
                }
            else:
                result = {
                    "entry": entry,
                    "success": bool(job.succeeded),
                    "timed_out": False,
                    "cancelled": False,
                    "agent_died": False,
                    "attempt": attempt,
                    "attempts": attempts,
                }
            if result["success"]:
                return result

        assert last_status is not None
        return result

    def stop(self) -> None:
        if self._tasker is not None and self._sink_id is not None:
            try:
                self._tasker.remove_sink(self._sink_id)
            except Exception:
                pass
            self._sink_id = None
        self._node_callback = None

        if self._tasker is not None:
            try:
                if self._tasker.running:
                    self._tasker.post_stop().wait()
            except Exception:
                pass

        if self._agent_client is not None:
            try:
                self._agent_client.disconnect()
            except Exception:
                pass

        self._stop_agent_process()
        self._node_start_callback = None
        self._started = False
