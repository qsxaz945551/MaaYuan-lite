# MaaYuan Lite

如鸢（代号鸢）日常自动化的精简客户端：**WPF 界面 + 自带 Python 运行时**，解压即用，不依赖原版安装。

> 本仓库是 [syoius/MaaYuan](https://github.com/syoius/MaaYuan) 的个人精简分支（fork）。
> 以日常链为主，同时保留限时活动与部分刷本任务；重写了桌面外壳与运行时。
> 上游的资源与 Agent 原样使用，所有流程修正都通过运行时覆盖层完成，不改磁盘上的上游文件。

## 这是什么

一个"打开就能跑日常"的 Windows 客户端。默认 8 项：

`🚀 启动游戏 → 💰 领月卡福利 → 🏯 据点日常 → 🔮 观星 → 📜 鸢报四连 → 💎 修为历练 → 🗡 白鹄扫荡 → 🔶 日常收尾`

全部跑完约 **13–14 分钟**，过程中不需要人工干预；体力不足、次数用尽、活动未开放都会自动跳过，
不会把整轮判失败。

除了日常，任务列表里还保留了 **21 项**可选任务，同样可以单独运行、参与勾选：

- **限时活动**：🍚 每日进膳、🗡 地宫助手、💝 初见日、🔍 楼主查岗
- **刷本与专项**：🔄 6-24/7-15 刷到体力耗尽、🔄 鸢报四合一、🔄 三千世界刷成就、
  🔄 自动刷神秘洞窟、🔥 家具历险首通、🌺 自动爬兰台、🧯 红点消除助手、👆 百宝箱、💲 铜钱历练、⚔️ 经验历练
- **往期活动**：🎲 爱乐之村、🌾 望祈丰年、🏮 花灯绘、🐱 咪教模拟器、🍡 魂生又一串、
  🗃️ 披荆斩棘的实习考核、💼 夜以继日的绩效评估

活动任务的识别模板同样来自上游；活动换期后模板失效时，需要等上游更新或自行替换模板
（见 `lite/templates/README.md`）。

## 快速上手

| 项 | 要求 |
|---|---|
| 系统 | Windows 10/11 x64 |
| 运行时 | .NET 10 Desktop Runtime（唯一外部依赖） |
| 模拟器 | 雷电 14，物理分辨率 1280×720（游戏启动后自己转竖屏） |
| 游戏 | 如鸢简中，已登录 |

1. 解压到任意目录，双击 `start-lite.bat`。
2. 先开好模拟器、把游戏停在主界面，点右上「检查连接」确认链路（只连接、截图，不点游戏）。
3. 左栏勾选今天要做的项，点「开始任务（N）」。
4. 中途停止后可以点「继续未完成」接着跑。

「启动时」可选：只打开界面 / 打开并最小化 / 自动运行日常 / 自动运行并最小化。「结束后」可选：
不处理 / 关闭 Lite / 关闭模拟器和 Lite。

## 精简了什么

- **任务**：39 → 29 项。移除 biubiu 加速器、据点商人购物、心纸营建、6-24 指定循环次数、派遣四合一、
  据点情报二合一、自动抄作业 V3、邺城之战 V3、关闭游戏、朝歌之战 V2。
- **界面**：只保留 主页任务列表 / 任务设置 / 连接设置 / 运行日志 / 启动与停止；去掉自动战斗与作业录制。
- **平台**：只保留 Windows x64，不再维护 macOS / Linux / Android 的构建与依赖脚本。
- **安装**：不需要先装原版、不需要单独装 Python、不需要配置环境变量。

## 新增了什么

- **今日日常勾选 + 继续未完成**：只补失败、中断或未执行的项，跑过的不重跑。
- **单任务运行**：`POST /api/run-task {"names": ["🔮 观星"]}`，调试单项不用整轮。
- **本地 HTTP API**：任务列表、选项、状态、日志都可读，方便接自己的自动化或看板。
- **资源热更新**：启动后从上游 GitHub 增量下载，暂存、校验、下次启动原子切换，失败自动回滚。
- **一键自检**：解释器、依赖、原生库、MaaAgentBinary、资源、OCR 模型、agent、adb、interface、端口，
  一条命令回答"为什么起不来"。
- **失败取证**：失败帧（`runtime/debug/on_error/`）与整屏截图（`runtime/failures/`）自动留存。
- **任务级覆盖层**：不用改上游 assets 就能修 pipeline，上游更新后不会被冲掉。

## 修复了什么

以下问题在上游 5.6.0 资源上实测存在，均通过覆盖层修正（详见文件内注释）：

| 问题 | 现象 | 处理 |
|---|---|---|
| 活动页判页锚点用了卡片标题 | 活动换期卡面改版后判页恒失败，`进入界面-活动` 死循环 121 次 / 790.9 s | 改用页面标题 `activity_title.png` + ROI 阈值 0.8 |
| 密探特训卡面模板过期 | 匹配分 0.5649（阈值 0.72），永远进不去特训页 | 自制 `lite_special_training.png`，实测 1.0000 |
| 活动入口图标改版 | 旧金色卷轴 0.5611（阈值 0.6），主界面找不到入口 | 自制 `lite_event_icon.png`（避开红点），实测 1.0000 |
| 月卡商店 20 体点击落在红点 | 无 target 的 Click 在识别框内随机取点，落在角标上 → 页签没切换 → OCR 读到商城价格 | target 收到标签本体 `[500,250,30,24]` |
| 月卡 60 体点击落在页签边框 | target 内同样随机取点，2026-11-17 落在 y=139（上边框）→ 页面没切 → 60 体漏领 | target 收到「福利」二字中心 `[344,158,24,16]`，并加 `pre_delay 600` |
| 家具互动点床 | 心纸君躺床上时点到角色、点不到家具，图标不浮出 | 改点矮柜 `[344,388,32,32]`，实测图标 0.9892 |
| 鸢报批量收集不等倒计时 | 确认收集后流程直接结束，任务在 153 s 判失败 | 把孤儿等待节点 `小道消息收集中` 接回轮询链 |
| 6-24 体力回复弹窗文案变体 | 上游只匹配「体力回复」，实际显示「用道具回复」→ 守卫永远不命中 | 扩展 OCR 期望值 |
| 据点日常 `无行囊check` 用 en 模型 | `en/` 只有 rec 没有 det，`ocrer_` 为空，守卫永不命中 | 该节点补 `only_rec` |

## 技术重构

| 维度 | 上游 MaaYuan | 本分支 |
|---|---|---|
| 界面 | MFAAvalonia | 自研 WPF（.NET 10）+ Python 服务进程 |
| 运行时 | 需要用户自备 Python 环境 | 自带 CPython 3.12.10 与全部依赖（293 MB） |
| 平台 | Windows / macOS / Linux / Android | 仅 Windows 10/11 x64 |
| 任务数 | 39 项 | 29 项 |
| 资源 | 随仓库发布 | 启动后从上游 GitHub 增量更新，暂存校验后原子切换 |
| 流程修正 | 直接改 pipeline | 运行时覆盖层，assets 保持上游原样 |

1. **界面与执行分离**：WPF 外壳负责展示与交互，Python 服务进程负责 MaaFramework 会话与任务调度，
   两者通过本地 HTTP JSON API 通信（`/api/state`、`/api/plan`、`/api/start`、`/api/run-task`、
   `/api/task-options` 等，契约见 `docs/api-contract.md`）。外壳崩溃时 `process_guard` 会带走服务进程，
   不会留下占端口的孤儿。
2. **运行时自包含**：`runtime_env/` 内置 CPython 3.12.10、`maafw==5.6.0`、OpenCV / numpy / Pillow /
   loguru 等依赖，唯一外部依赖是 .NET 10 Desktop Runtime。
3. **资源热更新**：启动后台检查上游 GitHub，下载到 `assets.next/` 暂存，校验 pipeline 数量、
   OCR 模型与 agent 脚本后**下次启动**原子切换；校验不过自动回滚，下载失败只记日志、不影响本次运行。
4. **覆盖层而非改文件**：`lite/pipeline-overrides.json`（4 条）与 `lite/pipeline_fixes.py` 在运行时
   合并进各任务的 `pipeline_override`。上游资源更新后修正依然生效，也不会弄脏 `assets/`。
5. **稳定性护栏**：`NodeRepeatGuard`（同一节点重复 120 次判卡死）、横屏/停滞检测、`agent_guard`、
   `process_guard`、日志轮转（agent 日志留 40 份、失败帧留 40 张）。
6. **工程化**：321 项单元测试（`python devtools/run_tests.py`）、一键自检（`python app.py --selftest`）、
   发布脚本与发布包自检。

## 性能实测

同一台机器（RTX 3060 Laptop / 雷电 14 / 720×1280 竖屏），整轮 8 项：

| 版本 | 墙钟 | private 均值/峰值 | 工作集均值/峰值 | CPU（单核） |
|---|---|---|---|---|
| 上游原版 2.3.1-beta.3 | 672.3 s¹ | 1878 / 2056 MB | 335 / 505 MB | 79.6% |
| Lite 0.3.16 | 796.9 – 838.9 s | 1473 – 2473 MB | 709 – 963 MB | 16.4 – 18.1% |

¹ 上游那轮「启动游戏」是关掉游戏后单独跑的（82.9 s），与 Lite 的整轮口径不同，时长仅供参考。
内存主因是识别推理的临时分配，不是泄漏；DirectML 后端偶发一次较大的分配，会把整轮均值抬高约 1 GB
（详见 `docs/evidence/`），按 2.8 GB 上限规划即可。

## 已知限制

- 只在**如鸢国服 + 雷电 14 + 1280×720** 下验证；其他模拟器、分辨率、繁中/国际服未做适配。
- 不包含自动战斗、作业站、密探信息采集；刷本类只保留 6-24 刷体力、三千世界、洞窟、兰台、家具历险首通。
- 活动任务的模板随版本/换期可能失效：`lite_special_training.png` 需要按 `lite/templates/README.md` 重新裁图。
- MaaFramework 5.6.0 的 `max_hit` 在运行时无效（框架只解析不检查），限流只能靠节点结构与守卫。
- 内存偶发升高（1.47 → 2.47 GB）已定位在主 Python 进程的 DirectML 分配，不影响任务执行。

## 开发

```bash
python devtools/run_tests.py                      # 321 项单元测试
python app.py --selftest                          # 环境自检
python devtools/release/sync_repo.py --update     # 同步上游 pipeline
python devtools/release/build_release.py          # 打包到 dist/MaaYuan-Lite-<版本>
dotnet build desktop/MaaYuanLite.Desktop          # 编译 WPF 客户端
```

## 致谢

- **[MaaYuan](https://github.com/syoius/MaaYuan)**（syoius 及贡献者）—— 本项目的全部任务流水线、
  资源与 Python Agent 都来自这里，没有它就没有这个分支。原项目功能远比本分支完整，
  需要刷本、作业站、密探采集等能力请直接使用上游。
- **[MaaFramework](https://github.com/MaaXYZ/MaaFramework)**（MaaXYZ）—— 图像识别、设备控制与任务调度，
  本项目使用 5.6.0。
- **[MFAAvalonia](https://github.com/MaaXYZ/MFAAvalonia)** —— 上游的桌面图形界面；本分支把它换成了
  自研 WPF 外壳，但界面组织方式仍受其影响。
- **[MaaCommonAssets](https://github.com/MaaXYZ/MaaCommonAssets)** —— OCR 模型（`ppocr_v6/small`、
  `ppocr_v5/zh_cn`、`ppocr_v4/en_us`），未量化、未替换。

## 许可

本项目自身代码以 MIT 发布。任务流水线、资源与 Agent 来自上游 MaaYuan（MIT），
MaaFramework 为 LGPL-3.0，OCR 模型来自 MaaCommonAssets。完整第三方清单见 `NOTICE.md`。

上游：[syoius/MaaYuan](https://github.com/syoius/MaaYuan)（分支 `v5`）。
