"""Repeat one task N times and watch the service for leaks (Q1).

Q1 asks for "100% success, handles and memory not climbing monotonically". That
cannot be judged from a single run, and reading it off a live process by hand is
guesswork. This script drives the loop through the HTTP API, samples the service
process after every round, and prints an explicit verdict.

The process is located through ``/api/meta``'s ``pid``: reverse-looking it up
from netstat was both slow and wrong on this machine.

Usage:
    python devtools/smoke/stability_run.py --spawn --task "🔮 观星" --times 10
    python devtools/smoke/stability_run.py --task "💰 领月卡福利" --times 5 --gap 3

``--spawn`` starts the service as a child of this script and shuts it down at
the end. Use it by default: a service left running from an earlier shell dies
with that shell, and then every round fails with "connection refused" — a
failure that looks like a Lite bug but is really a test-harness artifact.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_READ = 0x0010
SIZE_T = ctypes.c_size_t

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
psapi = ctypes.WinDLL("psapi", use_last_error=True)

kernel32.OpenProcess.restype = ctypes.c_void_p
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.CloseHandle.restype = wintypes.BOOL
kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
kernel32.GetProcessHandleCount.restype = wintypes.BOOL
kernel32.GetProcessHandleCount.argtypes = [
    ctypes.c_void_p,
    ctypes.POINTER(wintypes.DWORD),
]


class ProcessMemoryCounters(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("PageFaultCount", wintypes.DWORD),
        ("PeakWorkingSetSize", SIZE_T),
        ("WorkingSetSize", SIZE_T),
        ("QuotaPeakPagedPoolUsage", SIZE_T),
        ("QuotaPagedPoolUsage", SIZE_T),
        ("QuotaPeakNonPagedPoolUsage", SIZE_T),
        ("QuotaNonPagedPoolUsage", SIZE_T),
        ("PagefileUsage", SIZE_T),
        ("PeakPagefileUsage", SIZE_T),
    ]


psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
psapi.GetProcessMemoryInfo.argtypes = [
    ctypes.c_void_p,
    ctypes.POINTER(ProcessMemoryCounters),
    wintypes.DWORD,
]


def sample_process(pid: int) -> tuple[int | None, float | None]:
    """(handle count, working set MB) — ``None`` when the process is unreachable."""
    handle = kernel32.OpenProcess(
        PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid
    )
    if not handle:
        return None, None
    try:
        count = wintypes.DWORD()
        handles = count.value if kernel32.GetProcessHandleCount(handle, ctypes.byref(count)) else None

        counters = ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(counters)
        ok = psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb)
        rss = counters.WorkingSetSize / 1048576.0 if ok else None
        return handles, rss
    finally:
        kernel32.CloseHandle(handle)


class Client:
    """Minimal HTTP client that ignores proxy environment variables."""

    def __init__(self, port: int) -> None:
        self.base = f"http://127.0.0.1:{port}"
        self._opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({})
        )

    def get(self, path: str) -> dict:
        with self._opener.open(self.base + path, timeout=15) as response:
            return json.loads(response.read().decode("utf-8"))

    def post(self, path: str, payload: dict) -> dict:
        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            self.base + path,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self._opener.open(request, timeout=15) as response:
            return json.loads(response.read().decode("utf-8"))


def read_port(explicit: int | None) -> int:
    if explicit:
        return explicit
    pointer = ROOT / "runtime" / "port.txt"
    if pointer.is_file():
        text = pointer.read_text(encoding="utf-8").strip()
        if text.isdigit():
            return int(text)
    return 8765


RUNNING_STATES = {"starting", "running"}


def start_run(client: Client, task: str, patience: float = 90.0) -> None:
    """Start a run, retrying while the previous one is still winding down.

    ``_busy()`` asks whether the worker thread is still alive, while ``status``
    turns to ``completed`` a little earlier (the ``finally`` block still has to
    close the session). Polling the status is therefore not enough: the first
    attempt after a finished round can legitimately return 409.
    """
    deadline = time.monotonic() + patience
    while True:
        try:
            client.post("/api/run-task", {"names": [task]})
            return
        except urllib.error.HTTPError as error:
            if error.code != 409 or time.monotonic() > deadline:
                raise
            time.sleep(2)


def wait_until_idle(client: Client, timeout: float) -> dict:
    """Wait for the run to start, then for it to leave the running states.

    Checking only ``status != "running"`` was wrong: the first poll lands while
    the run is still ``starting``, so the loop returned immediately and every
    following round hit 409 BUSY.
    """
    deadline = time.monotonic() + timeout
    observed_running = False
    begin = time.monotonic()
    while time.monotonic() < deadline:
        state = client.get("/api/state?since=0")
        status = state.get("status")
        if status in RUNNING_STATES:
            observed_running = True
        elif observed_running:
            return state
        elif time.monotonic() - begin > 10:
            # A run so short it never showed up as running, or a rejected
            # request: either way there is nothing more to wait for.
            return state
        time.sleep(1.5)
    raise SystemExit(f"任务在 {timeout:.0f} 秒内没有结束，请检查日志")


def verdict(samples: list[tuple[int, float]], results: list[str]) -> list[str]:
    """Turn the raw samples into the two sentences Q1 actually asks for."""
    notes: list[str] = []
    ok = sum(1 for item in results if item == "completed")
    notes.append(f"成功率 {ok}/{len(results)}（{ok / len(results) * 100:.0f}%）")

    handles = [item[0] for item in samples]
    memory = [item[1] for item in samples]

    delta_h = handles[-1] - handles[0]
    rising = all(b > a for a, b in zip(handles, handles[1:]))
    if delta_h > 20 or rising:
        notes.append(
            f"⚠ 句柄从 {handles[0]} 涨到 {handles[-1]}（+{delta_h}，"
            f"{'持续单调上涨' if rising else '有波动但净增明显'}）"
        )
    else:
        notes.append(f"句柄 {handles[0]} → {handles[-1]}（{delta_h:+d}），未持续上涨")

    delta_m = memory[-1] - memory[0]
    if delta_m > 50:
        notes.append(f"⚠ 内存从 {memory[0]:.0f} MB 涨到 {memory[-1]:.0f} MB（{delta_m:+.0f} MB）")
    else:
        notes.append(f"内存 {memory[0]:.0f} → {memory[-1]:.0f} MB（{delta_m:+.0f} MB），正常")
    return notes


def main() -> int:
    parser = argparse.ArgumentParser(description="重复执行同一任务并观测进程指标")
    parser.add_argument("--task", required=True, help="任务名，要和 interface 里的一致")
    parser.add_argument("--times", type=int, default=10)
    parser.add_argument("--port", type=int)
    parser.add_argument("--gap", type=float, default=4.0, help="两轮之间的间隔秒数")
    parser.add_argument("--timeout", type=float, default=900.0, help="单轮上限")
    parser.add_argument(
        "--spawn", action="store_true", help="由本脚本启动并收尾服务（推荐）"
    )
    args = parser.parse_args()

    port = read_port(args.port)
    service = spawn_service(port) if args.spawn else None
    try:
        return run_rounds(args, port, kill_service if service else None)
    finally:
        if service is not None:
            stop_service(service)


def spawn_service(port: int) -> subprocess.Popen:
    """Start app.py as a child and wait until it answers.

    stdout/stderr go to a file, never to a pipe: an unread pipe fills up and
    blocks the service — the exact bug the WPF shell had.
    """
    log_path = ROOT / "runtime" / "stability-service.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(log_path, "ab")
    process = subprocess.Popen(
        [sys.executable, "app.py", "--port", str(port)],
        cwd=str(ROOT),
        stdout=handle,
        stderr=subprocess.STDOUT,
    )
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise SystemExit(
                f"服务启动即退出（code {process.returncode}），见 runtime/stability-service.log"
            )
        try:
            Client(port).get("/api/meta")
            print(f"服务已就绪（PID {process.pid}，端口 {port}）")
            return process
        except OSError:
            time.sleep(1.5)
    process.kill()
    raise SystemExit("服务 90 秒内没有就绪")


def stop_service(process: subprocess.Popen) -> None:
    """Ask the service to exit, then make sure it is gone."""
    if process.poll() is not None:
        return
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{read_port(None)}/api/exit", method="POST", data=b"{}"
        )
        urllib.request.build_opener(urllib.request.ProxyHandler({})).open(
            request, timeout=5
        )
    except OSError:
        pass
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        process.kill()


def kill_service() -> None:
    """Placeholder so the round runner can be called without a spawned child."""


def run_rounds(args: argparse.Namespace, port: int, _stopper) -> int:
    client = Client(port)
    try:
        meta = client.get("/api/meta")
    except OSError as error:
        raise SystemExit(f"连不上服务 {client.base}：{error}") from error

    pid = meta.get("pid")
    if not pid:
        raise SystemExit("服务没有返回 pid，无法采样（旧版本？）")

    print(f"服务端口 {port} / PID {pid} / 任务「{args.task}」× {args.times} 轮")
    print(f"{'轮':>3}  {'结果':<22} {'耗时':>7}  {'句柄':>6}  {'内存':>8}")

    samples: list[tuple[int, float]] = []
    results: list[str] = []

    for index in range(1, args.times + 1):
        started = time.monotonic()
        try:
            start_run(client, args.task)
            state = wait_until_idle(client, args.timeout)
        except SystemExit:
            raise
        except OSError as error:
            hint = "（上一轮还没结束）" if "409" in str(error) else ""
            print(f"{index:>3}  请求失败{hint}：{error}")
            results.append("error")
            continue

        elapsed = time.monotonic() - started
        status = state.get("status", "?")
        summary = state.get("summary") or {}
        results.append(status)
        handles, rss = sample_process(int(pid))
        if handles is not None and rss is not None:
            samples.append((handles, rss))
        print(
            f"{index:>3}  {status + ' ' + str(summary):<22} {elapsed:>6.0f}s  "
            f"{handles if handles is not None else '-':>6}  "
            f"{(f'{rss:.0f} MB' if rss is not None else '-'):>8}"
        )
        if index < args.times:
            time.sleep(args.gap)

    print()
    if len(samples) >= 2:
        for line in verdict(samples, results):
            print(f"  {line}")
    else:
        print("  采样点不足，无法判断趋势")
    return 0 if results and all(r == "completed" for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
