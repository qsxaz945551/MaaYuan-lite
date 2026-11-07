"""Reusable MaaFramework session for MaaYuan Lite.

This module deliberately has no UI dependencies. It owns the controller,
resource, tasker and Python Agent lifecycle so the scheduler and UI can stay
small and replaceable.
"""

from __future__ import annotations

import importlib.util
import os
import threading
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

from .step_text import focus_text


class SessionError(RuntimeError):
    pass


def _release_native(obj: Any) -> None:
    """Destroy one Maa native object exactly once.

    ``maa`` wraps a C handle and exposes *only* ``__del__`` as teardown. Calling
    it by hand works, but the object is still alive afterwards: when the last
    reference drops, CPython runs ``__del__`` again and the framework destroys a
    handle that is already freed. That double release is what crashed the
    service right after a run finished — ``0xc0000374`` in ``MaaTaskerDestroy``
    and an access violation in ``MaaAgentClientDestroy``
    (``runtime/crash.log``, 2026-11-06 08:18:17).

    Clearing ``_handle`` after the first call turns the second one into the
    no-op the destructors already check for (``if self._handle``).
    """
    finalize = getattr(obj, "__del__", None)
    try:
        if callable(finalize):
            finalize()
    except Exception:  # noqa: BLE001 - teardown must not raise
        pass
    finally:
        try:
            obj._handle = None
        except Exception:  # noqa: BLE001 - a read-only handle must not abort teardown
            pass


def _make_node_sink(
    on_success: Callable[[str], None],
    on_start: Optional[Callable[[str], None]] = None,
    on_step: Optional[Callable[[str, Optional[str]], None]] = None,
):
    """Build a context sink that reports pipeline node starts and successes.

    ``TaskerEventSink`` + ``Tasker.add_sink`` only delivers ``Tasker.Task.*``
    notifications in maafw 5.6.0; pipeline node events go to
    ``ContextEventSink`` + ``Tasker.add_context_sink``. Using the tasker sink
    left the stall watchdog and the loop guard without any node heartbeat, so
    every task longer than ``STALL_SECONDS`` was killed as "no progress" even
    while nodes kept succeeding.

    ``on_step`` additionally receives the node's ``focus`` text (the progress
    description upstream embeds in the pipeline) so the console can show what
    the task is doing instead of an internal node name.
    """
    from maa.context import ContextEventSink
    from maa.event_sink import NotificationType

    class _NodeSink(ContextEventSink):
        def on_node_pipeline_node(self, context, noti_type, detail) -> None:
            name = getattr(detail, "name", None)
            if not name:
                return
            if noti_type == NotificationType.Succeeded:
                on_success(str(name))
            elif noti_type == NotificationType.Starting:
                if on_start is not None:
                    on_start(str(name))
                if on_step is not None:
                    # ``focus`` is only attached to the live node detail, and
                    # the shape varies by node, so normalise it here.
                    #
                    # A node with ``focus`` produces *two* Starting events
                    # (measured: 2 Starting / 1 Succeeded) — that is the extra
                    # "focus callback" the framework documents. Succeeded is
                    # unaffected, so round counters stay accurate; the step line
                    # just receives the same text twice.
                    on_step(
                        str(name),
                        focus_text(getattr(detail, "focus", None), str(name)),
                    )

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
        logger: Any = None,
    ) -> None:
        # Injected so a callback failure can be reported into the run log
        # instead of vanishing; the session has no logger of its own.
        self._logger = logger
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
        self._step_callback: Optional[Callable[[str, Optional[str]], None]] = None
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
        # onnxruntime sizes its CPU arena per OpenMP thread. Measured on a
        # 16-core box: the two OCR models commit ~1.5 GB at the default thread
        # count vs ~1.1 GB at 4 threads, while throughput is unchanged
        # (511 ms/op at 4 vs 544 ms at 16 -- if anything slightly better).
        # Cap it unless the caller pinned a value.
        os.environ.setdefault("OMP_NUM_THREADS", str(min(4, os.cpu_count() or 4)))

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
            # Keep a screenshot of the failing recognition, and keep it inside
            # runtime/: the framework defaults the log dir to the working
            # directory, which littered the project root with on_error/.
            debug_dir = self.project_root / "runtime" / "debug"
            try:
                debug_dir.mkdir(parents=True, exist_ok=True)
                Tasker.set_log_dir(str(debug_dir))
            except Exception:  # noqa: BLE001 - a missing log dir must not block
                pass
            # Nothing in Lite reads RecoDetail raw/draws, so the per-recognition
            # frame cache is pure cost. The framework default is 4096 frames;
            # a small window keeps the debug affordance without hoarding memory.
            try:
                Tasker.set_reco_image_cache_limit(64)
            except Exception:  # noqa: BLE001 - older bindings may lack it
                pass
            self._tasker.set_save_on_error(True)
            if not self._tasker.bind(self._resource, self._controller):
                raise SessionError("Tasker failed to bind resource/controller")

            self._sink = _make_node_sink(
                self._handle_node, self._handle_node_start, self._handle_step
            )
            self._sink_id = self._tasker.add_context_sink(self._sink)

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
        # The PID survives us: if this process is killed, the next start reaps
        # the orphan before it grabs the adb socket again.
        from . import agent_guard

        agent_guard.record(self.project_root, self._agent_process.pid)

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

    def _run_action(self, action: dict[str, Any], timeout_ms: int = 4000) -> bool:
        """Run one action through a throwaway pipeline.

        Used by the unknown-screen recovery: it must not depend on any upstream
        node, and it must never leave a task running behind it.
        """
        if not self._started:
            return False
        entry = "lite-action"
        override = {
            entry: {
                "recognition": {"type": "DirectHit", "param": {}},
                "action": action,
                "next": [],
                "pre_delay": 0,
                "post_delay": 0,
                "timeout": timeout_ms,
            }
        }
        job = self._tasker.post_task(entry, override)
        deadline = time.monotonic() + (timeout_ms + 3000) / 1000.0
        while not job.done:
            if time.monotonic() >= deadline:
                self._tasker.post_stop().wait()
                return False
            time.sleep(0.1)
        return bool(job.succeeded)

    def press_back(self) -> bool:
        """Send the Android back key: the safest way out of an unknown popup."""
        return self._run_action({"type": "ClickKey", "param": {"key": [4]}})

    def tap(self, x: int, y: int) -> bool:
        return self._run_action({"type": "Click", "param": {"target": [x, y, 1, 1]}})

    def is_main_screen(self, timeout_ms: int = 1500) -> bool:
        """Read-only check for the two main-map anchors.

        No ROI: the emulator may be landscape before the game starts, and a
        hard-coded portrait ROI makes MaaFramework log ``roi is out of range``
        on every frame until the probe times out. A full-screen template match
        simply fails on a non-matching resolution.
        """
        return self.probe(
            [
                {
                    "type": "TemplateMatch",
                    "param": {"template": "mainmap/xinzhi.png", "threshold": 0.8},
                },
                {
                    "type": "TemplateMatch",
                    "param": {"template": "mainmap/judian.png", "threshold": 0.8},
                },
            ],
            timeout_ms,
        )

    def has_stamina_dialog(self) -> bool:
        """True when the stamina refill dialog is on screen.

        Measured on a 720x1280 capture (2026-11-04): the title 气力值回复 sits
        at y~315 and the two buttons at y~450. The old strip (y 496-584) missed
        the buttons entirely, and the game had renamed 日金市 to 白金币, so the
        probe never fired and a farming task just failed instead of stopping
        cleanly.
        """
        return self.probe(
            [
                {
                    "type": "OCR",
                    "param": {
                        "expected": [
                            "用道具回复",
                            "用日金市回复",
                            "用白金币回复",
                            "体力回复",
                            "气力值回复",
                        ],
                        "roi": [60, 280, 620, 230],
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

    def set_step_callback(
        self, callback: Optional[Callable[[str, Optional[str]], None]]
    ) -> None:
        """Watch node starts together with their ``focus`` text (console step).

        The second argument is the human-readable progress line upstream stores
        in the node's ``focus`` field, or ``None`` when the node has none.
        """
        self._step_callback = callback

    def _note(self, message: str, level: str = "warn") -> None:
        if self._logger is not None:
            try:
                self._logger(message, level)
            except Exception:  # noqa: BLE001 - logging must never break a run
                pass

    def _handle_node(self, name: str) -> None:
        callback = self._node_callback
        if callback is None:
            return
        try:
            callback(name)
        except Exception as error:  # noqa: BLE001
            # Swallowing this loses round counts silently, which looks like the
            # loop stopped making progress.
            self._note(f"节点完成回调出错（{name}）：{error}")

    def _handle_node_start(self, name: str) -> None:
        callback = self._node_start_callback
        if callback is None:
            return
        try:
            callback(name)
        except Exception as error:  # noqa: BLE001
            self._note(f"节点开始回调出错（{name}）：{error}")

    def _handle_step(self, name: str, text: Optional[str]) -> None:
        callback = self._step_callback
        if callback is None:
            return
        try:
            callback(name, text)
        except Exception as error:  # noqa: BLE001
            # A broken display callback must not take the run down with it.
            self._note(f"步骤进度回调出错（{name}）：{error}")

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
        from . import agent_guard

        agent_guard.clear(self.project_root)
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
        stall_check: Optional[Callable[[], bool]] = None,
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
            stalled = False
            next_agent_check = time.monotonic() + 2.0
            while not job.done:
                if should_stop is not None and should_stop():
                    cancelled = True
                    self._tasker.post_stop().wait()
                    break
                if stall_check is not None and stall_check():
                    # No node finished for a long time. The usual cause is a
                    # dialog nobody recognises covering the screen; waiting for
                    # the task timeout (30 min) wastes the whole run.
                    stalled = True
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
            if stalled:
                return {
                    "entry": entry,
                    "success": False,
                    "timed_out": False,
                    "cancelled": False,
                    "agent_died": False,
                    "stalled": True,
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

    def _with_timeout(self, label: str, action: Callable[[], Any], seconds: float) -> None:
        """Run a teardown step with a deadline.

        ``Job.wait()`` and ``AgentClient.disconnect()`` are native calls with no
        timeout of their own. One of them blocked forever once: the task showed
        ``completed`` but the worker thread never returned, so ``_busy()`` stayed
        True and every later run was rejected with 409. Skipping a stuck step
        leaves a daemon thread behind, which is far cheaper than a service that
        can never start another task.
        """
        finished = threading.Event()

        def runner() -> None:
            try:
                action()
            except Exception:  # noqa: BLE001 - teardown must not raise
                pass
            finally:
                finished.set()

        threading.Thread(target=runner, name=f"teardown-{label}", daemon=True).start()
        if not finished.wait(seconds):
            self._note(f"关闭步骤「{label}」超过 {seconds:.0f} 秒未完成，已跳过继续清理。")

    def _guarded_step(self, label: str, action: Callable[[], Any], seconds: float) -> None:
        """Teardown step with a deadline and a slow-step note.

        Every native call in `stop()` is unbounded. One of them blocked forever
        once: the task reported ``completed`` but the worker thread never came
        back, so ``_busy()`` stayed True and every later run got 409. Knowing
        *which* step is slow is the whole point — hence the per-step timing.
        """
        began = time.monotonic()
        self._with_timeout(label, action, seconds)
        spent = time.monotonic() - began
        if spent > 2.0:
            self._note(f"关闭步骤「{label}」耗时 {spent:.1f} 秒。", "info")

    def stop(self) -> None:
        if self._tasker is not None and self._sink_id is not None:
            self._guarded_step(
                "移除监听", lambda: self._tasker.remove_context_sink(self._sink_id), 5.0
            )
            self._sink_id = None
        self._node_callback = None
        self._step_callback = None

        if self._tasker is not None:
            try:
                if self._tasker.running:
                    self._guarded_step(
                        "停止任务", lambda: self._tasker.post_stop().wait(), 8.0
                    )
            except Exception:
                pass

        if self._agent_client is not None:
            self._guarded_step("断开 Agent", self._agent_client.disconnect, 8.0)

        self._guarded_step("结束 Agent 进程", self._stop_agent_process, 15.0)

        # Release native handles while the DLLs are still loaded. Relying on
        # __del__ at interpreter shutdown runs after MaaFramework has been
        # unloaded and crashes with an access violation (seen in
        # AgentClient.__del__). Order: client, tasker, resource, controller.
        #
        # These destructors are native and can block forever:
        # MaaAgentClientDestroy waits on a thread that never joins once the
        # device died mid-task (stack captured in runtime/crash.log). Blocking
        # `stop()` on that left `_busy()` true, so the next run was rejected
        # with 409 until the timeout expired. Destroy in background instead:
        # order is kept when it works, and a stuck destructor only leaks itself.
        self._sink = None
        pending = {}
        for attribute in ("_agent_client", "_tasker", "_resource", "_controller"):
            obj = getattr(self, attribute, None)
            if obj is not None:
                pending[attribute] = obj
                setattr(self, attribute, None)

        if pending:
            agent_done = threading.Event()
            if "_agent_client" not in pending:
                # 没有 agent 就没人会 set，release_rest 会白等 3 秒。
                agent_done.set()

            def destroy(name: str, obj: Any) -> None:
                # 只销毁一次：句柄清空后 GC 再调 __del__ 就是空操作。
                _release_native(obj)
                if name == "_agent_client":
                    agent_done.set()

            if "_agent_client" in pending:
                threading.Thread(
                    target=destroy, args=("_agent_client", pending["_agent_client"]),
                    name="release-agent", daemon=True,
                ).start()

            def release_rest() -> None:
                # 正常情况瞬间返回；agent 析构卡住时最多等 3 秒，
                # 再按原顺序销毁其余对象（此时顺序只能算尽力而为）。
                agent_done.wait(3.0)
                for name in ("_tasker", "_resource", "_controller"):
                    obj = pending.get(name)
                    if obj is not None:
                        destroy(name, obj)

            threading.Thread(
                target=release_rest, name="release-runtime", daemon=True
            ).start()

        self._node_start_callback = None
        self._started = False
