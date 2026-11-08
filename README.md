# MaaYuan Lite

如鸢日常自动化的精简本地客户端：WPF 界面 + 自带 Python 运行时，解压即用，不依赖原版安装。

## 前置条件

| 项 | 要求 |
|---|---|
| 系统 | Windows 10/11 x64 |
| 运行时 | **.NET 10 Desktop Runtime**（唯一外部依赖，约 55 MB） |
| 模拟器 | 雷电 14，物理分辨率 1280×720；游戏启动后会自己转成竖屏 |
| 游戏 | 如鸢简中，已登录 |

## 第一次使用

1. 解压到任意目录。
2. 双击 `start-lite.bat`。若目录里还有 `启动 Lite.bat`，双击它——它按 `dist/active.txt` 挑当前版本，再转交给包内的 `start-lite.bat`。
3. 雷电模拟器先开好、游戏进到主界面，再点界面右上方的「检查连接」。它只连接、截图，不点游戏、不跑任务；日志出现截图信息就说明链路通了。
4. 左栏「今日日常」勾选今天要做的项，「开始任务（N）」执行勾选的全部任务。
5. 中途要停：点「停止」，正在跑的那项按未完成记录；之后点「继续未完成」只补失败、中断或未执行的项，跑过的不重跑。

## 界面

顶部从左到右：启动时、结束后、地宫开放期、开始任务（N）、继续未完成、停止。

- **左栏「执行顺序」**：`今日日常` / `其他任务` 两个页签，各自显示勾选数；「全选」常驻在页签左边，只作用于今日日常，切到其他任务时变灰不可点。未开放的任务（地宫、每日进膳）不参与勾选，也不会被全选带上。
- **中栏「任务选项」**：选中任务的全部选项，改完立即保存，下次运行生效。
- **右栏「运行日志」**：实时日志与成功/失败统计，不清空历史，只插入「—— 新的一次运行 ——」分隔。标题右侧有「检查连接」「最近截图」。

「启动时」：只打开界面 / 打开并最小化 / 自动运行日常 / 自动运行并最小化

「结束后」：不处理 / 关闭 Lite / 关闭模拟器和 Lite

关闭窗口就是退出：后端进程树会被一并回收，下次启动是全新实例。

## 两条限时任务

- **每日进膳**：16:00 开放、24:00 结束，由本机时间自动决定是否入链（位置在领月卡之后），其它时间不出现，不需要手动开关。
- **地宫助手**：限时活动，用顶部「地宫开放期」手动开关。活动没开时线上探测 5 秒内返回不可用，该项标记「跳过」，不算失败，后续任务照常执行。

## 资源更新

启动后会在后台检查上游 GitHub，有新版就下载到 `assets.next/`，**下次启动**才原子切换。切换前校验 pipeline 数量、OCR 模型与 agent 脚本，校验不过自动回滚到上一版。下载失败只写一条日志，不影响本次运行。

## 日志与排障

| 位置 | 内容 |
|---|---|
| 界面右栏 | 最近 2000 行运行日志与统计 |
| `runtime/logs/agent-*.log` | Agent 输出，保留最近 40 个 |
| `runtime/debug/maa.log` | MaaFramework 日志 |
| `runtime/debug/on_error/` | 识别失败帧，保留最近 40 张 |
| `runtime/failures/` | 任务失败时的整屏截图 |
| `runtime/crash.log` | Python 原生崩溃栈 |

常见情况：

- **提示缺少 .NET 10 Desktop Runtime**：按提示装「.NET Desktop Runtime 10.x — Windows x64」，装完重新双击。
- **检查连接失败**：确认雷电已启动，且 `adb devices` 能看到 `emulator-5554`；模拟器路径不对时改 `lite/runtime-config.json` 的 `adb_path`。
- **端口 8765 被占用**：程序会自动改用随机端口并把实际端口写进 `runtime/port.txt`，界面无需干预。
- **任务卡在某个识别**：先看界面日志的当前步骤，再看 `runtime/debug/on_error/` 最近一张图是不是画面停在别处（弹窗、体力不足、活动未开）。

## 恢复默认

关掉程序后删除 `runtime/settings.json`（启动/结束动作等偏好）、`runtime/task-options.json` 与 `runtime/task-inputs.json`（选项），下次启动会回到随包默认值。`lite/` 下的同名文件是默认值本体，程序只读不写。

## 开发

```bash
python devtools/run_tests.py                      # 306 项单元测试
python devtools/release/sync_repo.py --update      # 同步上游 pipeline 到 vendor/MaaYuan-src
python devtools/release/build_release.py           # 打包到 dist/MaaYuan-Lite-<版本>
python devtools/release/release_switch.py switch <版本>   # 切换 active
python devtools/smoke/smoke_release.py             # 对打包产物做 version/health 自检
python devtools/release/verify_chain.py            # 用发布包跑一整轮日常（8–13 分钟）
dotnet build desktop/MaaYuanLite.Desktop           # 编译 WPF 客户端
```

## 文档

| 文件 | 内容 |
|---|---|
| `LITE.md` | 完整使用说明、界面、任务口径、更新策略 |
| `MANIFEST.md` | 目录归属边界（自研 / 上游 / 生成） |
| `docs/api-contract.md` | HTTP 契约与错误码 |
| `PROJECT-REPORT.md` | 实现记录、验收数据、决策表 |
| `docs/DEEPSEEK-HANDOFF.md` | 环境事实与模拟器硬规则 |
| `docs/AUDIT-20261107-v2.md` | 技术债与资产审查（含清理记录） |

上游：[syoius/MaaYuan](https://github.com/syoius/MaaYuan)（分支 `v5`）。本项目只保留日常链所需的任务与选项，资源随上游更新。
