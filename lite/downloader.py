"""Download upstream resources into ``assets.next/`` without touching live files.

The archive from GitHub contains pipeline JSON, images, ``interface.json`` and
the ``agent`` scripts, but **not** the OCR models: those live in the
``MaaCommonAssets`` submodule and are fetched separately at the exact commit the
parent repo pins.

Two cost savers matter in practice:

* an archive already downloaded for this commit is reused from ``runtime/cache``;
* when the submodule pin did not move, model files are copied from the current
  resources instead of being downloaded again (38 MB per update).

Everything happens in ``assets.next.part`` and is renamed only after the tree
passes verification, so an interrupted run never looks like a staged update.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import threading
import time
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from .source_manifest import MANIFEST_NAME, MODEL_FILES, REQUIRED_MODELS, find_manifest

REPO = "syoius/MaaYuan"
BRANCH = "v5"
ARCHIVE = f"https://github.com/{REPO}/archive/{{sha}}.zip"
COMMITS = f"https://api.github.com/repos/{REPO}/commits?sha={BRANCH}&per_page=1"
CONTENTS = f"https://api.github.com/repos/{REPO}/contents/{{path}}?ref={{sha}}"
SUB_REPO = "MaaXYZ/MaaCommonAssets"
RAW = "https://raw.githubusercontent.com/{repo}/{ref}/{path}"

MODEL_SETS: dict[str, tuple[str, tuple[str, ...]]] = {
    # upstream set -> (target folder, files that actually exist upstream)
    "ppocr_v6/small": ("model/ocr", ("det.onnx", "rec.onnx", "keys.txt")),
    "ppocr_v5/zh_cn": ("model/ocr/operator_names", ("det.onnx", "rec.onnx", "keys.txt")),
    "ppocr_v4/en_us": ("model/ocr/en", ("rec.onnx", "keys.txt")),
}

STAGE_PART = "assets.next.part"
STAGE = "assets.next"
CACHE = Path("runtime") / "cache"
USER_AGENT = "maayuan-lite"

_lock = threading.Lock()
_state: dict[str, Any] = {
    "state": "idle",
    "phase": "",
    "message": "",
    "doneBytes": 0,
    "totalBytes": 0,
    "sha": "",
    "startedAt": "",
    "finishedAt": "",
    "error": None,
}
_thread: threading.Thread | None = None


def state() -> dict[str, Any]:
    with _lock:
        return dict(_state)


def _update(**patch: Any) -> None:
    with _lock:
        _state.update(patch)


def _add_bytes(count: int) -> None:
    with _lock:
        _state["doneBytes"] = int(_state.get("doneBytes", 0)) + count


def _add_total(count: int) -> None:
    with _lock:
        _state["totalBytes"] = int(_state.get("totalBytes", 0)) + count


def running() -> bool:
    with _lock:
        return _thread is not None and _thread.is_alive()


def start(
    project_root: Path,
    sha: str = "",
    on_done: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Kick off a background download. Returns the current state either way."""
    global _thread
    if running():
        return {"started": False, "reason": "已在下载中", "state": state()}

    part = project_root / STAGE_PART
    if part.exists():
        shutil.rmtree(part, ignore_errors=True)

    _update(
        state="running",
        phase="start",
        message="准备下载",
        doneBytes=0,
        totalBytes=0,
        sha=sha,
        startedAt=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        finishedAt="",
        error=None,
    )
    _thread = threading.Thread(
        target=_run,
        args=(project_root, sha, on_done),
        name="resource-download",
        daemon=True,
    )
    _thread.start()
    return {"started": True, "state": state()}


def _wait_until_idle(
    wait_while: Callable[[], bool], limit: float = 3600.0, interval: float = 20.0
) -> bool:
    """等到 ``wait_while()`` 返回 False；超过 ``limit`` 秒放弃并返回 False。"""
    deadline = time.time() + limit
    while time.time() < deadline:
        try:
            if not wait_while():
                return True
        except Exception:  # noqa: BLE001 - 判定失败就当空闲，别把更新卡死
            return True
        time.sleep(interval)
    return False


def auto_check(
    project_root: Path,
    enabled: bool = True,
    delay: float = 6.0,
    log: Callable[[str, str], None] | None = None,
    wait_while: Callable[[], bool] | None = None,
) -> None:
    """Check upstream in the background and download without asking.

    Runs after the console is already serving requests, so a slow or offline
    network never delays startup. A staged tree that is already waiting is left
    alone: it will be applied on the next start.

    Everything it decides is reported through ``log`` (the service's run log):
    a silent background download is indistinguishable from "nothing happened",
    which is exactly the confusion that made a user ask why resources had
    already been fetched.
    """
    if not enabled:
        return

    def say(message: str, level: str = "info") -> None:
        if log is None:
            return
        try:
            log(message, level)
        except Exception:  # noqa: BLE001 - logging must never kill the check
            pass

    def done(result: dict[str, Any]) -> None:
        if result.get("state") == "done":
            say("资源下载完成并校验通过，重启 Lite 后生效。")
        else:
            say(f"资源下载失败：{result.get('error') or result.get('message')}", "warn")

    def loop() -> None:
        time.sleep(delay)
        try:
            from .updater import check_updates

            data = check_updates(project_root)
            resource = data.get("resource", {})
            if (project_root / STAGE).is_dir():
                say("资源已下载待生效，重启 Lite 后切换。")
                return
            if running():
                say("资源正在后台下载，完成后会提示重启。")
                return
            if not resource.get("available"):
                if resource.get("error"):
                    say(f"检查资源更新失败：{resource['error']}", "warn")
                else:
                    say(f"资源已是最新（{resource.get('local') or '未知版本'}）。")
                return
            if wait_while is not None and wait_while():
                # 「启动时自动运行」会让任务和更新检查几乎同时开始。下载本身是隔离的
                # （只写 assets.next.part），但 58 MB 会和 OCR 抢带宽和 CPU，让人以为
                # 任务变慢了；等这一轮跑完再下，代价只是晚几分钟生效。
                say("资源有更新，等本轮任务结束后再后台下载。")
                if not _wait_until_idle(wait_while):
                    say("等待任务结束超过 60 分钟，本次跳过资源下载。", "warn")
                    return
                if wait_while():  # 刚结束又被用户点起来了
                    say("任务又开始了，本次跳过资源下载，下次启动再查。", "warn")
                    return
            say(
                f"资源有更新：本地 {resource.get('local')} → 上游 {resource.get('remote')}"
                f"（{resource.get('remoteDate')}），开始后台下载。"
            )
            start(project_root, sha="", on_done=done)
        except Exception as error:  # noqa: BLE001 - background convenience only
            say(f"检查资源更新失败：{error}", "warn")

    threading.Thread(target=loop, name="update-check", daemon=True).start()


def _run(
    project_root: Path, sha: str, on_done: Callable[[dict[str, Any]], None] | None
) -> None:
    try:
        result = _download(project_root, sha)
        _update(
            state="done",
            phase="done",
            message=str(result.pop("message", "资源已就绪，下次启动生效")),
            finishedAt=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            error=None,
            **result,
        )
    except Exception as error:  # noqa: BLE001 - every failure is reported as state
        shutil.rmtree(project_root / STAGE_PART, ignore_errors=True)
        _update(
            state="failed",
            phase="failed",
            message="更新失败，已保留旧版",
            error=f"{type(error).__name__}: {error}",
            finishedAt=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )
    if on_done is not None:
        try:
            on_done(state())
        except Exception:  # noqa: BLE001
            pass


def _download(project_root: Path, sha: str) -> dict[str, Any]:
    commit_date = ""
    if not sha:
        head = _remote_head()
        sha = head["sha"]
        commit_date = head["date"]
    _update(phase="archive", message="下载资源包", sha=sha)

    part = project_root / STAGE_PART
    part.mkdir(parents=True, exist_ok=True)
    cache = project_root / CACHE
    cache.mkdir(parents=True, exist_ok=True)
    archive = cache / f"{sha[:12]}.zip"
    if not archive.is_file():
        _fetch(ARCHIVE.format(sha=sha), archive, retries=2)

    _update(phase="extract", message="解压资源包")
    _extract(archive, part)

    pin = _submodule_pin(sha)
    _update(phase="models", message="准备 OCR 模型")
    reused = _sync_models(project_root, part, pin)

    _update(phase="verify", message="校验资源完整性")
    problems = _verify(part)
    if problems:
        raise RuntimeError("；".join(problems))

    manifest = _build_manifest(part, sha, pin, commit_date)
    (part / "assets" / MANIFEST_NAME).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    staged = project_root / STAGE
    if staged.exists():
        shutil.rmtree(staged, ignore_errors=True)
    part.rename(staged)
    try:
        archive.unlink()
    except OSError:
        pass

    return {
        "message": (
            f"资源已就绪（{manifest['pipelineCount']} 个流水线，"
            f"模型复用 {reused} 个），下次启动生效"
        ),
        "pipelineCount": manifest["pipelineCount"],
        "modelsReused": reused,
    }


def _fetch(url: str, target: Path, retries: int = 1, timeout: float = 120.0) -> int:
    """Stream a URL to disk, reporting progress. Returns bytes written."""
    last: Exception | None = None
    for attempt in range(retries + 1):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=timeout) as response:
                total = int(response.headers.get("Content-Length", "0"))
                if total:
                    _add_total(total)
                written = 0
                with target.open("wb") as buffer:
                    while True:
                        chunk = response.read(1 << 20)
                        if not chunk:
                            break
                        buffer.write(chunk)
                        written += len(chunk)
                        _add_bytes(len(chunk))
            return written
        except Exception as error:  # noqa: BLE001
            last = error
            try:
                target.unlink()
            except OSError:
                pass
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"下载失败 {url.rsplit('/', 1)[-1]}：{last}")


def _extract(archive: Path, target: Path) -> None:
    """Unpack assets/ and agent/ only; the archive also carries docs and tools."""
    with zipfile.ZipFile(archive) as bundle:
        roots = {name.split("/", 1)[0] for name in bundle.namelist() if "/" in name}
        if len(roots) != 1:
            raise RuntimeError(f"压缩包结构异常，根目录 {len(roots)} 个")
        for info in bundle.infolist():
            if info.is_dir():
                continue
            head, _, relative = info.filename.partition("/")
            if not relative.startswith(("assets/", "agent/")):
                continue
            if ".." in relative.split("/"):
                continue
            destination = target / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            with bundle.open(info) as source, destination.open("wb") as handle:
                shutil.copyfileobj(source, handle)


def _sync_models(project_root: Path, part: Path, pin: str) -> int:
    """Fill model/ocr/** in the staged tree, copying locally when the pin matches.

    Secondary sets (operator names, English) are optional: an install that never
    had them still runs the daily chain, so a failed download of those is
    recorded and skipped rather than aborting the whole update.
    """
    staged = part / "assets" / "resource" / "base"
    live = project_root / "assets" / "resource" / "base"
    _, local = find_manifest(project_root)
    reuse = bool(pin and local and pin == str(local.get("modelsCommit", "")))

    reused = 0
    skipped: list[str] = []
    for model_dir, (relative, names) in MODEL_SETS.items():
        required = relative == "model/ocr"
        for name in names:
            target = staged / relative / name
            if target.is_file() and target.stat().st_size > 0:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            source = live / relative / name
            if reuse and source.is_file():
                shutil.copy2(source, target)
                reused += 1
                continue
            if not pin:
                if required:
                    raise RuntimeError("无法确定 OCR 模型版本，请联网后重试")
                skipped.append(f"{relative}/{name}")
                continue
            try:
                _fetch(
                    RAW.format(repo=SUB_REPO, ref=pin, path=f"OCR/{model_dir}/{name}"),
                    target,
                    retries=1,
                )
            except RuntimeError:
                target.unlink(missing_ok=True)
                if required:
                    raise
                skipped.append(f"{relative}/{name}")
    if skipped:
        _update(message=f"可选模型缺失 {len(skipped)} 个，已跳过")
    return reused


def _remote_head() -> dict[str, str]:
    """Latest commit on the tracked branch, with its commit date."""
    request = urllib.request.Request(
        COMMITS,
        headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"},
    )
    with urllib.request.urlopen(request, timeout=8) as response:
        payload = json.load(response)
    if not payload:
        raise RuntimeError("上游没有返回提交")
    first = payload[0]
    return {
        "sha": str(first["sha"]),
        "date": str(first.get("commit", {}).get("committer", {}).get("date", ""))[:10],
    }


def _remote_sha() -> str:
    return _remote_head()["sha"]


def _submodule_pin(sha: str) -> str:
    """Commit the parent repo pins for MaaCommonAssets, empty when unknown."""
    url = CONTENTS.format(path="assets/MaaCommonAssets", sha=sha)
    try:
        request = urllib.request.Request(
            url,
            headers={"User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"},
        )
        with urllib.request.urlopen(request, timeout=8) as response:
            payload = json.load(response)
        if isinstance(payload, dict):
            return str(payload.get("sha", ""))
    except Exception:  # noqa: BLE001 - offline falls back to the local pin
        pass
    return ""


def _verify(part: Path) -> list[str]:
    problems: list[str] = []
    resource = part / "assets" / "resource" / "base"
    if not (part / "assets" / "interface.json").is_file():
        problems.append("缺少 interface.json")
    pipeline = resource / "pipeline"
    count = len(list(pipeline.rglob("*.json"))) if pipeline.is_dir() else 0
    if count < 100:
        problems.append(f"pipeline 只有 {count} 个文件")
    for relative in REQUIRED_MODELS:
        path = resource / relative
        if not path.is_file() or path.stat().st_size == 0:
            problems.append(f"缺少模型 {relative}")
    if not (part / "agent" / "main.py").is_file():
        problems.append("缺少 agent/main.py")
    return problems


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _build_manifest(part: Path, sha: str, pin: str, commit_date: str = "") -> dict[str, Any]:
    """Manifest for a staged tree, which has no git metadata to read."""
    resource = part / "assets" / "resource" / "base"
    models: dict[str, str] = {}
    for relative in MODEL_FILES:
        path = resource / relative
        if path.is_file():
            models[relative] = _sha256(path)

    interface = part / "assets" / "interface.json"
    return {
        "commit": sha,
        "commitDate": commit_date or datetime.now().strftime("%Y-%m-%d"),
        "branch": BRANCH,
        "modelsCommit": pin,
        "models": models,
        "interfaceSha256": _sha256(interface) if interface.is_file() else "",
        "pipelineCount": len(list((resource / "pipeline").rglob("*.json")))
        if (resource / "pipeline").is_dir()
        else 0,
        "generatedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
