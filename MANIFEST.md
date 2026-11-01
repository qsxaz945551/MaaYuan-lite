# 目录归属清单（MANIFEST）

MaaYuan Lite 的代码分成两类：**自研**（本仓库维护）和**上游**（从 MaaYuan 复制，不修改）。
本文件定义这条边界，打包时按此决定带什么。

## 自研（需要维护、需要入库）

| 路径 | 说明 | 行数 |
|---|---|---|
| `app.py` | HTTP 服务、进程与窗口管理 | 430 |
| `lite/*.py` | 调度、会话、选项、配置解析（10 个模块） | 2234 |
| `lite/ui/index.html` | 前端单文件（将被 WPF 替换） | 926 |
| `lite/tests/` | 10 个测试文件，49 项用例 | 908 |
| `lite/*.json` | 日常链定义、选项快照、scope、运行配置 | — |
| `start-lite.bat` | 启动脚本 | 20 |
| `devtools/` | 开发期工具（静态扫描、进程测量） | — |
| `LITE.md` / `代码结构自查报告.md` | 项目文档 | — |

## 上游（运行时依赖，不修改，随上游版本更新）

| 路径 | 体积 | 运行时用途 | 入库 |
|---|---|---|---|
| `assets/interface.json` | 431 KB | **任务与选项定义源头**，`apply_scope.py` 读它生成 Lite 版 interface | ✅ 入库（文本，可 diff） |
| `assets/resource/` | 67 MB | 图片模板、OCR 模型、流水线 JSON | ❌ 不入库 |
| `assets/config/` | 1 KB | 上游配置模板 | ❌ 不入库 |
| `agent/` | 8.5 MB | Python Agent：自定义识别/动作、`*.npz` 索引 | ⚠️ 入库（不支持 LFS，暂按二进制提交） |
| `deps/` | 303 KB | 上游依赖脚本 | ❌ 已被 `.gitignore` 排除 |

## 上游（非运行时，已移出主目录）

原在本项目根目录，运行时零引用（已用 grep 验证），2026-11-01 移入 `vendor/upstream/`：

`docs/` `guide/` `homepage/` `tools/` `android/` `config/` `MFAUpdater`
`check_resource.py` `configure.py` `install.py` `install4release.py` `migrate_pipeline_v5.py`
`StockReport.txt` `CONTACT` `logo.png` `v5-release-note.md` `自定义派遣脚本修改说明.md`

合计 **36 MB**。`vendor/` 整体被 `.gitignore` 排除，需要时从上游压缩包重新解出即可。

## 上游来源

- 仓库：`https://github.com/syoius/MaaYuan`，分支 `v5`（默认分支）
- 当前同步版本：提交 `c119472`（2026-10-26），由 `devtools/sync_repo.py` 记录
- 资源与 agent 由 `vendor/MaaYuan-src/` 提供；项目内的 `assets/`、`agent/` 是早期从
  `MaaYuan-win-x86_64-v2.1.1-beta.6` 安装目录复制的副本，现在只作兜底
- 运行时（Python / maa 包 / MaaAgentBinary）仍指向安装目录，见下一节

## 资源更新（游戏更新时最重要的一节）

**现在是直接从 GitHub 仓库同步，不再依赖原版安装。**

上游仓库 `github.com/syoius/MaaYuan`（分支 `v5`）里有 pipeline、图片、
`interface.json` 和 `agent/`；OCR 模型放在子模块 `MaaXYZ/MaaCommonAssets`
（344 MB，整克隆不划算），所以只按需下载当前版本需要的 7 个文件
（`ppocr_v6/small` 主模型 + `ppocr_v5/zh_cn` 密探名模型 + `ppocr_v4/en_us` 英文）。

```bash
python devtools/sync_repo.py            # 首次：克隆 + 下载模型（约 100 MB）
python devtools/sync_repo.py --update   # 之后：拉取最新提交，模型按大小增量更新
python devtools/sync_repo.py --check    # 只看当前版本，不下载
```

克隆落在 `vendor/MaaYuan-src/`（已被 `.gitignore` 排除，约 181 MB）。

`lite/runtime-config.json` 的三个字段指向它（**相对路径按项目根解析**）：

```json
"resource_root": "vendor/MaaYuan-src/assets/resource/base",
"agent_root": "vendor/MaaYuan-src/agent",
"interface_source": "vendor/MaaYuan-src/assets/interface.json"
```

三个字段留空 = 回退到项目内的 `assets/`、`agent/` 副本（这份副本仍在，作为兜底）。

`start-lite.bat` 每次启动都会重跑 `apply_scope.py`，裁剪结果随仓库版本刷新。

### 更新后的自检

```bash
python devtools/check_upstream.py
```

校验三件事：资源路径是否完整（含 OCR 模型）、`daily-profile` 里的任务名是否还存在、
`pipeline_fixes` 与 `round_progress` 依赖的节点名是否还存在。有问题退出码为 1。

**游戏大版本更新后的顺序**：`sync_repo.py --update` → `check_upstream.py` →
任务名/节点名失效就先改 `daily-profile.json` / `pipeline_fixes.py` / `round_progress.py`
→ 再跑日常。

## 仍然依赖原版安装的部分

资源已经不依赖了，但**运行时还依赖**，卸载前需要补齐：

| 依赖 | 现状 | 卸载后怎么办 |
|---|---|---|
| Python 解释器 | 用 `D:/Apps Game/MaaYuan-.../python/python.exe` | 自带 embeddable Python，或装系统 Python |
| `maa` 包（含原生库 66 MB） | 用原版 site-packages | `pip install maa`（自带 `bin/*.dll`） |
| `MaaAgentBinary`（13 MB） | 用原版 `libs/MaaAgentBinary` | `pip install MaaAgentBinary`（独立包） |
| MaaFramework 原生库 | `runtime_root/runtimes/win-x64/native` | 已含在 `maa` 包的 `bin/` 里 |

也就是说「卸载原版」还差一步：把这四样搬进 Lite 自己的目录。做完之后
`runtime_root` 就可以不再指向 `D:/Apps Game/...`。

## 恢复步骤（换机器 / 重装）

1. `git clone` 本仓库（`assets/resource` 与 `vendor/` 不入库，需重新获取）
2. `python devtools/sync_repo.py` 拉取上游资源与模型
3. 修改 `lite/runtime-config.json` 的 `runtime_root` / `adb_path`（指向 Python 与 adb）
4. 运行 `python lite/apply_scope.py` 生成 `build/generated/interface.json`
5. 运行 `python -m unittest discover -s lite/tests` 确认环境正常
5. 运行 `python lite/apply_scope.py` 生成 `build/generated/interface.json`
6. 运行 `python -m unittest discover -s lite/tests` 确认环境正常
