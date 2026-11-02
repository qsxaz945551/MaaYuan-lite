"""Record which upstream version the local resources came from.

Without this file nothing can answer "is my resource older than upstream?"
``sync_repo.py`` writes it after a sync; the release builder copies it; the
updater compares it with GitHub.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

MANIFEST_NAME = ".source.json"
# Mirrors the three sets pinned by upstream configure.py. ``ppocr_v4/en_us``
# ships without det.onnx, so English reuses the main detector — listing it here
# would make every update fail a 404.
MODEL_FILES = (
    "model/ocr/det.onnx",
    "model/ocr/rec.onnx",
    "model/ocr/keys.txt",
    "model/ocr/operator_names/det.onnx",
    "model/ocr/operator_names/rec.onnx",
    "model/ocr/operator_names/keys.txt",
    "model/ocr/en/rec.onnx",
    "model/ocr/en/keys.txt",
)
# Without these three nothing can recognise Chinese text at all.
REQUIRED_MODELS = MODEL_FILES[:3]


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="ignore",
    )
    return result.stdout.strip()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_manifest(repo_dir: Path) -> dict[str, Any]:
    assets = repo_dir / "assets"
    resource = assets / "resource" / "base"

    models: dict[str, str] = {}
    for relative in MODEL_FILES:
        path = resource / relative
        if path.is_file():
            models[relative] = _sha256(path)

    interface = assets / "interface.json"
    pinned = ""
    try:
        tree = _git(repo_dir, "ls-tree", "HEAD", "assets/MaaCommonAssets")
        parts = tree.split()
        if len(parts) >= 3:
            pinned = parts[2]
    except OSError:
        pass

    return {
        "commit": _git(repo_dir, "rev-parse", "HEAD"),
        "commitDate": _git(repo_dir, "log", "-1", "--format=%cd", "--date=short"),
        "branch": _git(repo_dir, "rev-parse", "--abbrev-ref", "HEAD"),
        "modelsCommit": pinned,
        "models": models,
        "interfaceSha256": _sha256(interface) if interface.is_file() else "",
        "pipelineCount": len(list((resource / "pipeline").rglob("*.json")))
        if (resource / "pipeline").is_dir()
        else 0,
        "generatedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def write_manifest(repo_dir: Path) -> Path:
    manifest = build_manifest(repo_dir)
    target = repo_dir / "assets" / MANIFEST_NAME
    target.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return target


def find_manifest(project_root: Path) -> tuple[Path | None, dict[str, Any] | None]:
    """Look for a manifest next to the resources actually in use."""
    candidates = [
        project_root / "assets" / MANIFEST_NAME,
        project_root / "vendor" / "MaaYuan-src" / "assets" / MANIFEST_NAME,
    ]
    for path in candidates:
        if not path.is_file():
            continue
        try:
            return path, json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
    return None, None
