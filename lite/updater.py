"""Check whether upstream resources are newer than the local copy.

Network access is optional and always bounded: a 3 second timeout, a 6 hour
cache, and errors are returned as data rather than raised. Callers decide
whether to show a badge or start a download.
"""

from __future__ import annotations

import json
import time
import urllib.request
from pathlib import Path
from typing import Any

from .source_manifest import find_manifest

REPO = "syoius/MaaYuan"
BRANCH = "v5"
API = f"https://api.github.com/repos/{REPO}/commits?sha={BRANCH}&per_page=1"
PYPI = "https://pypi.org/pypi/maafw/json"
CACHE_HOURS = 6


def _fetch_remote_commit(timeout: float = 3.0) -> dict[str, str]:
    request = urllib.request.Request(
        API,
        headers={
            "User-Agent": "maayuan-lite",
            "Accept": "application/vnd.github+json",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.load(response)
    if not payload:
        raise ValueError("empty response")
    first = payload[0]
    return {
        "sha": str(first.get("sha", "")),
        "date": str(first.get("commit", {}).get("committer", {}).get("date", ""))[:10],
    }


def _fetch_pypi_version(timeout: float = 3.0) -> str:
    request = urllib.request.Request(PYPI, headers={"User-Agent": "maayuan-lite"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.load(response)
    return str(payload.get("info", {}).get("version", ""))


def _read_cache(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def check_updates(project_root: Path, force: bool = False, timeout: float = 3.0) -> dict[str, Any]:
    manifest_path, local = find_manifest(project_root)
    cache_path = project_root / "runtime" / "update-check.json"
    cached = _read_cache(cache_path)

    fresh = (
        cached is not None
        and not force
        and time.time() - float(cached.get("checkedAt", 0)) < CACHE_HOURS * 3600
    )

    remote: dict[str, str] | None = None
    error: str | None = None
    framework_latest = ""
    framework_error: str | None = None
    if fresh and cached:
        remote = cached.get("remote")
        error = cached.get("error")
        framework_latest = str(cached.get("frameworkLatest") or "")
        framework_error = cached.get("frameworkError")
    else:
        try:
            remote = _fetch_remote_commit(timeout)
        except Exception as exc:  # noqa: BLE001 - offline is normal
            error = f"{type(exc).__name__}: {exc}"
        try:
            framework_latest = _fetch_pypi_version(timeout)
        except Exception as exc:  # noqa: BLE001
            framework_error = f"{type(exc).__name__}: {exc}"
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(
            json.dumps(
                {
                    "checkedAt": time.time(),
                    "remote": remote,
                    "error": error,
                    "frameworkLatest": framework_latest,
                    "frameworkError": framework_error,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    local_sha = local.get("commit", "") if local else ""
    remote_sha = remote.get("sha", "") if remote else ""
    available = bool(local_sha and remote_sha and local_sha != remote_sha)

    try:
        from importlib.metadata import version

        framework_installed = version("maafw")
    except Exception:  # noqa: BLE001
        framework_installed = "?"

    return {
        "resource": {
            "local": local_sha[:12] or None,
            "localDate": local.get("commitDate") if local else None,
            "remote": remote_sha[:12] or None,
            "remoteDate": remote.get("date") if remote else None,
            "available": available,
            "manifest": str(manifest_path) if manifest_path else None,
            "checked": not fresh,
            "error": error,
        },
        "framework": {
            "installed": framework_installed,
            "latest": framework_latest or None,
            "pinned": "5.6.0",
            "available": bool(
                framework_latest and framework_latest != framework_installed
            ),
            "error": framework_error,
        },
    }
