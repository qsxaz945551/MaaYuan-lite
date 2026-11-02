"""从 GitHub 仓库同步 MaaYuan 资源，让 Lite 不再依赖原版安装。

上游仓库 syoius/MaaYuan（默认分支 v5）里有 pipeline、图片、interface.json 和
agent；OCR 模型放在子模块 MaaXYZ/MaaCommonAssets 里（344 MB，不值得整克隆），
所以这里只按当前版本需要的 7 个文件按需下载。

用法：
    python devtools/sync_repo.py            # 首次克隆并同步模型
    python devtools/sync_repo.py --update   # 已有克隆，拉取最新提交
    python devtools/sync_repo.py --check    # 只报告当前版本，不下载

同步完成后把 lite/runtime-config.json 的三个路径指向 vendor/MaaYuan-src 即可。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "vendor" / "MaaYuan-src"
REPO_URL = "https://github.com/syoius/MaaYuan.git"
BRANCH = "v5"
SUB_REPO = "MaaXYZ/MaaCommonAssets"
RAW = "https://raw.githubusercontent.com/{repo}/{ref}/{path}"

# 与仓库 configure.py 保持一致：中文主模型用 ppocr_v6/small，
# 密探全名模型用 ppocr_v5/zh_cn，英文用 ppocr_v4/en_us。
MODEL_SETS = {
    "ppocr_v6/small": "model/ocr",
    "ppocr_v5/zh_cn": "model/ocr/operator_names",
    "ppocr_v4/en_us": "model/ocr/en",
}
MODEL_FILES = ("det.onnx", "rec.onnx", "keys.txt")


def run(cmd: list[str], cwd: Path | None = None, check: bool = True) -> str:
    result = subprocess.run(
        cmd, cwd=str(cwd) if cwd else None, capture_output=True, text=True,
        encoding="utf-8", errors="ignore",
    )
    if check and result.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd)} 失败：{result.stderr.strip()[:300]}")
    return result.stdout.strip()


def repo_state() -> tuple[str, str]:
    sha = run(["git", "-C", str(DEST), "rev-parse", "--short", "HEAD"])
    date = run(["git", "-C", str(DEST), "log", "-1", "--format=%cd", "--date=short"])
    return sha, date


def ensure_repo(update: bool) -> None:
    if (DEST / ".git").is_dir():
        if update:
            print(f"拉取 {BRANCH} 最新提交……")
            run(["git", "-C", str(DEST), "fetch", "--depth", "1", "origin", BRANCH])
            run(["git", "-C", str(DEST), "reset", "--hard", "FETCH_HEAD"])
        else:
            print("已存在克隆，跳过更新（加 --update 可拉取最新）")
        return

    DEST.parent.mkdir(parents=True, exist_ok=True)
    print(f"克隆 {REPO_URL}（分支 {BRANCH}，深度 1）……这一步约 70–90 MB")
    run([
        "git", "clone", "--depth", "1", "--branch", BRANCH,
        "--single-branch", REPO_URL, str(DEST),
    ])
    # 保持与上游字节一致，避免 CRLF 转换让文件大小对不上。
    run(["git", "-C", str(DEST), "config", "core.autocrlf", "false"])


def pinned_submodule() -> str:
    """父仓库为子模块钉住的 commit，模型必须取这个版本。"""
    out = run(["git", "-C", str(DEST), "ls-tree", "HEAD", "assets/MaaCommonAssets"])
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 3:
            return parts[2]
    raise RuntimeError("未能读取 MaaCommonAssets 子模块指向的提交")


def remote_size(url: str) -> int:
    request = urllib.request.Request(url, method="HEAD",
                                     headers={"User-Agent": "maayuan-lite"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return int(response.headers.get("Content-Length", "0"))


def download(url: str, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": "maayuan-lite"})
    with urllib.request.urlopen(request, timeout=120) as response, target.open("wb") as handle:
        while True:
            chunk = response.read(1 << 20)
            if not chunk:
                break
            handle.write(chunk)


def sync_models(pinned: str) -> int:
    """按需下载模型文件，大小一致则跳过，返回下载个数。"""
    base = DEST / "assets" / "resource" / "base"
    downloaded = 0
    for model_dir, dest_dir in MODEL_SETS.items():
        for name in MODEL_FILES:
            url = RAW.format(
                repo=SUB_REPO, ref=pinned, path=f"OCR/{model_dir}/{name}"
            )
            target = base / dest_dir / name
            try:
                size = remote_size(url)
            except Exception as error:
                print(f"  [跳过] {model_dir}/{name}：{error}")
                continue
            if target.is_file() and target.stat().st_size == size:
                continue
            print(f"  下载 {model_dir}/{name}（{size / 1048576:.1f} MB）")
            download(url, target)
            downloaded += 1
    return downloaded


def verify() -> list[str]:
    base = DEST / "assets"
    problems = []
    if not (base / "interface.json").is_file():
        problems.append("缺少 assets/interface.json")
    ocr = base / "resource" / "base" / "model" / "ocr"
    for name in MODEL_FILES:
        if not (ocr / name).is_file():
            problems.append(f"缺少 OCR 模型 {name}")
    pipeline = base / "resource" / "base" / "pipeline"
    count = len(list(pipeline.rglob("*.json"))) if pipeline.is_dir() else 0
    if count < 100:
        problems.append(f"pipeline 文件偏少（{count}）")
    if not (DEST / "agent" / "main.py").is_file():
        problems.append("缺少 agent/main.py")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--update", action="store_true", help="拉取最新提交")
    parser.add_argument("--check", action="store_true", help="只报告状态")
    args = parser.parse_args()

    ensure_repo(update=args.update)
    sha, date = repo_state()
    print(f"仓库版本：{sha}（{date}）")

    if not args.check:
        pinned = pinned_submodule()
        print(f"子模块 MaaCommonAssets 钉在 {pinned[:12]}")
        changed = sync_models(pinned)
        print(f"模型文件更新 {changed} 个" if changed else "模型文件均为最新")

    problems = verify()
    base = DEST / "assets"
    if not problems:
        pipeline = base / "resource" / "base" / "pipeline"
        print(f"校验通过：pipeline {len(list(pipeline.rglob('*.json')))} 个 JSON，模型齐全")

        sys.path.insert(0, str(ROOT))
        from lite.source_manifest import write_manifest

        manifest = write_manifest(DEST)
        print(f"来源清单：{manifest}")

        print("\n把 lite/runtime-config.json 指向这个目录即可：")
        print(json.dumps({
            "resource_root": str((base / "resource" / "base").resolve()).replace("\\", "/"),
            "agent_root": str((DEST / "agent").resolve()).replace("\\", "/"),
            "interface_source": str((base / "interface.json").resolve()).replace("\\", "/"),
        }, ensure_ascii=False, indent=2))
        return 0

    print("校验未通过：")
    for item in problems:
        print("  -", item)
    return 1


if __name__ == "__main__":
    sys.exit(main())
