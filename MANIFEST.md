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

- 版本：`MaaYuan-win-x86_64-v2.1.1-beta.6`
- 运行时根目录（本机）：`D:/Apps Game/MaaYuan-win-x86_64-v2.1.1-beta.6`（见 `lite/runtime-config.json`）
- 本仓库的 `assets/`、`agent/` 即从该版本复制而来

## 恢复步骤（换机器 / 重装）

1. 取上游 `MaaYuan-win-x86_64-v2.1.1-beta.6` 完整包
2. 复制其中的 `assets/`、`agent/` 到本目录（覆盖）
3. 复制 `assets/interface.json`（通常在 `assets/` 根下）
4. 修改 `lite/runtime-config.json` 的 `runtime_root` / `adb_path`
5. 运行 `python lite/apply_scope.py` 生成 `build/generated/interface.json`
6. 运行 `python -m unittest discover -s lite/tests` 确认环境正常
