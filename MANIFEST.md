# 目录归属清单（MANIFEST）

MaaYuan Lite 的代码分成三类：**自研**（本仓库维护）、**上游**（从 MaaYuan 复制，
会被资源更新替换）、**生成**（运行时产生，不入库）。

本文件定义这条边界，打包（`devtools/build_release.py`）按此决定带什么。

## 自研（需要维护、需要入库）

| 路径 | 说明 | 规模 |
|---|---|---|
| `app.py` | HTTP 服务、进程守卫、启动编排 | 727 行 |
| `lite/*.py` | 调度、会话、选项、更新、自检（21 个模块） | 4230 行 |
| `lite/ui/index.html` | 旧浏览器控制台（`--legacy` 才用，WPF 上线后退役） | 926 行 |
| `lite/tests/` | 16 个测试文件 | 1433 行，83 项用例 |
| `lite/*.json` | 日常链、选项快照、scope、运行配置、来源清单 | — |
| `desktop/MaaYuanLite.Desktop/` | WPF 客户端（.cs + .xaml） | 17 个文件，约 1200 行 |
| `start-lite.bat` | 启动器（**GBK + CRLF**，默认拉起 WPF） | 40 行 |
| `devtools/` | 开发期工具（同步、自检、打包、测量） | 13 个脚本 |
| `docs/api-contract.md` | 字段级 API 契约与错误码表 | — |
| `NOTICE.md` | 第三方声明 | — |
| `LITE.md` / `MANIFEST.md` / `开发清单-v2.md` | 项目文档 | — |

## 上游（运行时可被更新替换）

| 路径 | 体积 | 运行时用途 | 入库 |
|---|---|---|---|
| `assets/interface.json` | 424 KB | **任务与选项定义源头**，`apply_scope.py` 读它生成裁剪版 | ✅ 文本，可 diff |
| `assets/.source.json` | 1 KB | 记录来源 commit、子模块 pin、8 个模型 sha256 | ✅ 小文本 |
| `assets/resource/base/` | 75 MB | 图片模板、OCR 模型、流水线 JSON | ❌ |
| `agent/` | 7.5 MB | Python Agent：自定义识别/动作、`*.npz` 索引 | ⚠️ 入库（无 LFS） |

**`agent/` 不再是"只读"**：资源自动更新会连同 agent 脚本一起替换，且在
`apply_staged` 里与 `resource/base` 原子切换。改 agent 的补丁应写在
`lite/pipeline_fixes.py`，不要直接改 `agent/` 下的文件 —— 下次更新会被覆盖。

## 运行时（自带，不依赖原版安装）

`runtime_env/` 共 **293 MB**，已被 `.gitignore` 排除，发布包由 `build_release.py` 打包：

```
runtime_env/
  python/                    CPython 3.12.10 embeddable（含 maa 5.6.0、cv2、numpy、PIL）
  python/Lib/site-packages/
    maa/bin/                 MaaFramework 原生库（60 MB，已替代原版 runtimes/win-x64/native）
    MaaAgentBinary/          Agent 二进制（13 MB）
```

已删除：`pandas`（75 MB，全仓库无引用）、`pip`（13 MB）、重复的 `runtimes/`（65 MB）。

2026-11-02 起原版安装目录 `D:\Apps Game\MaaYuan-win-x86_64-v2.1.1-beta.6` 已改名
`.disabled`，Lite 仍能启动、连接、截图、跑任务（V1/V2 验收通过）。

## 生成（运行时产生，不入库）

| 路径 | 说明 |
|---|---|
| `build/generated/interface.json` | `apply_scope.py` 的裁剪产物，启动时按 mtime 自动重建 |
| `runtime/port.txt` | 实际监听端口（WPF 读它，不解析 stdout） |
| `runtime/last-run.json` | 上次运行进度，「继续未完成」依赖它 |
| `runtime/agent.json` | agent 进程 PID，崩溃后用于清理孤儿 |
| `runtime/debug/maa.log` | MaaFramework 日志（`Tasker.set_log_dir` 指定） |
| `runtime/debug/on_error/` | 识别失败帧，保留最近 40 张 |
| `runtime/logs/agent-*.log` | agent stdout/stderr，保留最近 40 个 |
| `runtime/cache/*.zip` | 已下载的资源包，保留最近 3 个 |
| `runtime/selftest.json` | 最近一次自检结果 |
| `runtime/update-check.json` | 更新检查缓存（6 小时） |
| `assets.next/` `assets.prev/` | 资源切换的暂存与备份，切换瞬间存在 |
| `on_error/` | **历史遗留**，旧版本写在项目根；新版本已改到 `runtime/debug/on_error/` |

## 资源更新（两条路径）

### 用户侧：自动更新（发布包）

`lite/downloader.py` 在启动后后台检查 GitHub，有新版就下载到 `assets.next/`：

1. 下载 `syoius/MaaYuan` 对应 commit 的 zip（约 58 MB），只解压 `assets/` + `agent/`
2. OCR 模型按子模块 pin 取：pin 未变则从现有资源**复制**（省 38 MB），变了才下载
3. 校验（pipeline 数量 ≥ 100、主模型齐全、agent/main.py）
4. 写 `.source.json` → `assets.next.part` 改名为 `assets.next`
5. **下次启动**时原子切换；生成 interface 失败会自动回滚

模型清单是 **8 个文件**（`ppocr_v4/en_us` 上游没有 `det.onnx`，英文复用主检测器）。

### 开发侧：`sync_repo.py`

```bash
python devtools/sync_repo.py            # 克隆上游到 vendor/MaaYuan-src 并下载模型
python devtools/sync_repo.py --update   # 拉最新提交
python devtools/sync_repo.py --check    # 只看版本
```

克隆落在 `vendor/MaaYuan-src/`（约 181 MB，已 gitignore）。开发配置若指向
`vendor/`，自动更新会**拒绝切换**并提示「自动更新只对发布包生效」—— 这是刻意的，
避免更新一个运行时根本不读的目录。

### 更新后的兼容性检查

```bash
python devtools/check_upstream.py
```

校验资源完整性、`daily-profile` 任务名、`pipeline_fixes` / `round_progress` 依赖的
节点名。有问题退出码为 1。`lite/update_gate.py` 在切换前会做同样的检查。

## 上游来源

- 仓库：`https://github.com/syoius/MaaYuan`，分支 `v5`
- 当前同步版本：`c119472`（2026-10-26），子模块 `MaaCommonAssets` pin `dabcd46`
- `assets/.source.json` 是机器可读的记录；`vendor/MaaYuan-src` 是开发期的完整克隆

## 恢复步骤（换机器 / 重装）

**用发布包**（推荐）：解压 `dist/MaaYuan-Lite-<版本>` → 双击 `start-lite.bat`。
包内自带 `runtime_env/`、`assets/`、`agent/`，无需任何前置安装（除 .NET 10 Desktop Runtime）。

**从源码**：

1. `git clone` 本仓库（`assets/resource`、`runtime_env`、`vendor` 不入库）
2. 准备运行时：复制一份 embeddable Python 到 `runtime_env/python/`，`pip install maa MaaAgentBinary opencv-python numpy pillow loguru zhconv jsonschema openpyxl`
3. 准备资源：`python devtools/sync_repo.py`（或让下载器跑一次）
4. `python lite/apply_scope.py` 生成 interface
5. `python devtools/run_tests.py` 跑测试，`python app.py --selftest` 查环境
6. `dotnet build desktop/MaaYuanLite.Desktop` 编译 WPF，双击 `start-lite.bat`
