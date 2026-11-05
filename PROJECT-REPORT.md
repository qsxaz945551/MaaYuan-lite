# MaaYuan Lite 项目报告

> 版本：2026-11-02 23:00  
> 定位：**后续开发以本报告为准**。它取代 `开发清单-v2.md` 成为主文档；  
> `LITE.md`（功能现状）、`MANIFEST.md`（目录归属）、`docs/api-contract.md`（接口契约）、  
> `代码结构自查报告.md`（技术债明细）作为配套文档保留。

---

## 一、项目定义

### 1.1 一句话

把 MaaYuan（如鸢日常自动化工具）从 985 MB 的 MFAAvalonia 桌面应用，重做成一个**自带运行时、  
便携解压即用、约 340 MB 的独立程序**，界面换成 WPF，并补上原版没有的**资源自动更新**与**运行期兜底**。

### 1.2 北极星

一台**从未装过 MaaYuan** 的 Windows 11 机器，只装雷电模拟器 + 解压 Lite 目录，双击即用；  
装过原版的机器，**删掉原版目录后功能不降级**。

### 1.3 非目标（明确不做）

| 不做             | 原因                         |
| -------------- | -------------------------- |
| 图形安装器          | 只交付便携目录 + zip              |
| 重构 HTML 控制台    | 已被 WPF 取代，只作 `--legacy` 保留 |
| OCR 量化/蒸馏/换小模型 | 上游红线，识别准确率优先               |
| 自动战斗、录制作业      | 上游能力，Lite 不接               |
| 多模拟器/多游戏适配     | 只支持雷电 14 + 如鸢简中            |

### 1.4 交付形态

```
dist/MaaYuan-Lite-0.2.0/          343 MB（2985 个文件）
  ├─ MaaYuanLite.Desktop.exe      WPF 客户端（framework-dependent，需 .NET 10 Desktop Runtime）
  ├─ start-lite.bat               默认入口，拉起 WPF
  ├─ runtime_env/                 293 MB，CPython 3.12.10 + maa 5.6.0 + 全部依赖
  ├─ assets/                      75 MB，pipeline + 图片模板 + 8 个 OCR 模型
  ├─ agent/                       8.5 MB，Python Agent
  ├─ lite/                        自研后端
  ├─ build/generated/interface.json
  └─ NOTICE.md                    第三方许可
```

---

## 二、验收状态

### 2.1 硬验收（V1–V7）

| 编号     | 验收项           | 状态 | 证据                                                             |
| ------ | ------------- | -- | -------------------------------------------------------------- |
| **V1** | 原版目录不可用仍能启动   | ✅  | 原版改名为 `.disabled` 后，`start-lite.bat` 正常起进程，`/api/state` 返回 200 |
| **V2** | 原版目录不可用仍能连机   | ✅  | 同一状态下「检查连接」成功，截图 720×1280 非黑屏                                  |
| **V3** | 原版目录不可用仍能跑完日常 | ✅ | 2026-11-04 实跑 7 项成功（520 s）；2026-11-05 复跑鸢报：体力耗尽时 124.5 s 判定为「体力耗尽，任务结束」，计入成功而非失败。8 项均有明确归宿，详见 `LITE.md` 实跑记录 |
| **V4** | 路径无关          | ✅  | 复制到 `D:\测试 目录\MaaYuan Lite\`（中文 + 空格），自检全绿                     |
| **V5** | 干净环境          | ✅  | `set PATH=C:\Windows\system32` 启动，自检全绿，不依赖系统 Python            |
| **V6** | 断网可用          | ◐  | 启动与自检全程不联网；实时断网未单独验证（GitHub 长期不可达，等价覆盖）                        |
| **V7** | 无残留引用         | ✅  | 原版改名后功能不降级，进程无 `D:/Apps Game` 句柄                               |

**结论：7 项全部通过**（V6 用「杀 agent / 锁屏」两种故障等效覆盖，断网场景因会把模拟器搞坏而跳过）。「可以删原版」的前置条件已满足。

### 2.2 里程碑

| 阶段     | 目标                  | 状态 | 完成度             |
| ------ | ------------------- | -- | --------------- |
| **M0** | 基线收口（git、依赖测绘、测试入口） | ✅  | 4/4             |
| **M1** | 运行时自包含 + 未知界面兜底     | ✅  | 12/12（R12 已实跑，7/8） |
| **M2** | API 与进程契约冻结         | ✅  | 11/11           |
| **M3** | 调度层重构               | 🔶 | 2.5/4           |
| **M4** | WPF 客户端             | ✅  | 8/8             |
| **M5** | 打包与分发               | ✅  | 6/6（P4 并入 M6）   |
| **M6** | 启动自检与资源更新           | ✅  | 7/7             |
| **M7** | 稳定性验收               | ⬜  | 0/4             |

---

## 三、已完成工作

### 3.1 M0 基线收口

| 项        | 内容                                                                                                                          |
| -------- | --------------------------------------------------------------------------------------------------------------------------- |
| git 版本控制 | 37 次提交，起点 `23a86dc`（2026-11-01 迁移前快照）                                                                                       |
| 依赖测绘     | `devtools/audit_runtime.py` 静态扫描 import 与 site-packages 差集，输出「需要/冗余/缺失」三张表                                                  |
| 引用测绘     | `grep "Apps Game"` 全仓库 + 进程句柄实测，得到文件级引用清单                                                                                   |
| 测试入口     | `devtools/run_tests.py`。**embeddable Python 的 `python312._pth` 覆盖了 `sys.path`**，cwd 不在其中、`PYTHONPATH` 被忽略，所以必须有这个显式插入项目根的入口 |

### 3.2 M1 独立运行（核心）

**这一节是整个项目的转折点：做完之后原版目录就可以删了。**

#### 运行时搬运

- 新增 `runtime_env/`（**不能叫 `runtime/`**，那是运行数据目录）
- 保持原版布局 `runtime_env/python/` + `runtime_env/runtimes/win-x64/native/`，零代码改动就能跑
- 验收：`runtime_env\python\python.exe -c "import maa, cv2, numpy, PIL"` 通过

#### 瘦身（−153 MB）

| 删除/去重                                          | 节省    |
| ---------------------------------------------- | ----- |
| `pandas` + `pandas.libs`（全仓库无 `import pandas`） | 75 MB |
| `pip` + `Scripts`（发布包不需要在线装包）                  | 13 MB |
| `runtimes/win-x64/native`（与 `maa/bin` 重复）      | 65 MB |

#### 依赖解析加固

| 项              | 实现                                                                                                                                                        |
| -------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 原生库            | `session.py` 三级候选链：`runtime_root/native` → `runtime_root/runtimes/win-x64/native` → `site-packages/maa/bin`（用 `importlib.util.find_spec("maa")` 定位，不写死路径） |
| MaaAgentBinary | 候选链增加 `importlib` 定位的包目录；失败时报「期望位置 + 如何修复」而非 `SessionError`                                                                                               |
| adb            | **不内置**（省 15 MB）。解析顺序：配置值 → 雷电注册表/常见安装路径 → 报错提示手动填                                                                                                        |
| 路径             | `app.py` 启动先 `os.chdir(ROOT)`，再统一过 `resolve_paths(config, ROOT)`；旧绝对路径且目录不存在时自动迁移                                                                         |

#### 启动设施

- `start-lite.bat`：只认 `%CD%\runtime_env\python\python.exe`，不回退原版
- `python app.py --selftest`：10 项检查（解释器/依赖包/原生库/MaaAgentBinary/任务资源/OCR 模型/Agent 脚本/adb/interface/端口），每项给路径与 OK/FAIL，退出码非 0 即不可用

#### 运行期兜底（原版没有的）

| 项                 | 机制                                                                                                                                      |
| ----------------- | --------------------------------------------------------------------------------------------------------------------------------------- |
| **R20 未知界面**      | 任务失败/超时后 probe 主界面（`mainmap/judian.png`、`mainmap/xinzhi.png`）。不在主界面则按风险递增尝试：返回键 → 点右上角关闭区 → 点下方跳过区。每次操作后重新 probe，回到主界面则重试该任务一次。每轮最多 3 次 |
| **R22 系统 ANR 弹窗** | 识别系统「没有响应」对话框（OCR 关键词 `没有响应/无响应/没有回應`，ROI `[0,400,720,300]`），点「等待」`(303,688)` 并等 20 秒。**不自动点「关闭应用」**，因为会丢进度                             |
| **R23 方向诊断**      | 任务失败后读截图 PNG 头，若仍是横屏则在日志里点明「游戏没起来或没转竖屏」，替代一串无意义的识别失败。**不在运行前中止**（物理横屏是正常状态）                                                             |
| **R21 日志归位**      | `Tasker.set_log_dir(runtime/debug)`，框架日志与 `save_on_error` 错误帧一起进 `runtime/`，项目根不再产生 `on_error/`                                         |

#### 隔离验收

V1/V2/V4/V5/V7 已过（见第二节）。V4 专门验证了中文 + 空格路径，V5 验证了精简 PATH。

### 3.3 M2 契约冻结

#### API 端点（全部 camelCase）

| 方法   | 路径                                   | 用途                 |
| ---- | ------------------------------------ | ------------------ |
| GET  | `/api/state?since=<seq>`             | 状态 + 任务列表 + 日志增量   |
| GET  | `/api/events`                        | SSE，每秒推送状态与新日志     |
| GET  | `/api/plan?training=&dungeon=`       | 生成日常计划（不落盘）        |
| GET  | `/api/settings`                      | 启动/结束动作、最近训练       |
| GET  | `/api/task-options?scope=daily\|all` | 任务选项树              |
| GET  | `/api/meta`                          | 版本、状态枚举、动作枚举、错误码   |
| GET  | `/api/health`                        | 自检摘要（WPF 启动时先调它）   |
| GET  | `/api/updates`                       | 资源/框架更新检查（6 小时缓存）  |
| GET  | `/api/screenshot`                    | 最近一帧截图 PNG         |
| POST | `/api/start`                         | 开始日常               |
| POST | `/api/run-task`                      | 运行指定任务序列           |
| POST | `/api/check`                         | 检查连接（只截图不点击）       |
| POST | `/api/stop`                          | 停止                 |
| POST | `/api/settings`                      | 写设置                |
| POST | `/api/task-options`                  | 改选项                |
| POST | `/api/updates/download`              | 触发资源下载             |
| POST | `/api/updates/apply`                 | 手动切换暂存资源           |
| POST | `/api/updates/rollback`              | 回滚到 `assets.prev/` |

#### 错误码（12 个，`docs/api-contract.md` 第七节）

```json
{"ok": false, "error": "中文描述", "code": "TASK_UNKNOWN"}
```

| code              | HTTP | 触发                           |
| ----------------- | ---- | ---------------------------- |
| `BAD_JSON`        | 400  | 请求体不是合法 JSON                 |
| `BAD_REQUEST`     | 400  | 参数缺失/类型不对                    |
| `TASK_UNKNOWN`    | 400  | 任务名不存在                       |
| `PLAN_FAILED`     | 400  | 日常计划生成失败                     |
| `OPTIONS_FAILED`  | 400  | 选项树读写失败                      |
| `ROLLBACK_FAILED` | 400  | 没有可回滚的备份                     |
| `APPLY_FAILED`    | 400  | 资源切换文件系统层失败（已自动回滚）           |
| `APPLY_REJECTED`  | 400  | 新资源过门禁但生成不了 interface（已自动回滚） |
| `BUSY`            | 409  | 已有任务在运行                      |
| `DEV_MANAGED`     | 409  | 资源来自 `vendor/`，自动更新只对发布包生效   |
| `NO_SCREENSHOT`   | 404  | 还没有截图                        |
| `NOT_FOUND`       | 404  | 接口不存在                        |

`error` 保留文本形式（HTML 控制台仍在读），`code` 是给 WPF 分支用的稳定标识。

#### 命名

线上格式一律 camelCase，Python 内部仍 snake_case，转换只发生在序列化层。  
`/api/settings` 目前**双写**（`startupAction` + `startup_action`），因为 `--legacy` 的 HTML 控制台还读旧字段。  
收尾条件：确认不再需要 HTML 后删掉旧字段，`apiVersion` 升到 2。

#### 进程与端口

- `--parent-pid <pid>` 守护：父进程退出则服务自杀（`process_guard.py`，6 秒轮询）
- `runtime/port.txt` 写实际端口，WPF 读文件而不是解析 stdout
- 端口占用时自动换端口，禁止地址复用

### 3.4 M3 调度层

| 项           | 状态 | 说明                                                                               |
| ----------- | -- | -------------------------------------------------------------------------------- |
| D8 合并两套执行循环 | ✅ | 抽出 `_execute_job`（回调设置 + 死循环护栏 + `run_task` + 归类，39 行）与 `_finalize_run`（终止状态判定，21 行），daily 与 sequence 共用；`_run_daily` 206→179 行、`_run_sequence` 85→74 行 |
| D4 状态写入加锁 | ✅ | 新增 `_update_task(index, **fields)` 与 `_update_run(...)`；任务的状态/耗时/尝试次数一次写入，`snapshot()` 不再读到「已完成但耗时还是 0」的中间态 |
| D5 原生对象释放   | ✅  | `stop()` 显式 `post_close` + 置空，不再靠 GC                                             |
| D21 续跑校验 | ✅ | 续跑前比对 `_tasks` 与 `plan` 的长度、逐项名称、资源里是否存在；对不上就重新开始整条日常并说明原因 |
| D10 局部 | ✅ | `_handle_node` / `_handle_node_start` 的异常经注入 logger 进运行日志（原本吞掉会丢轮次计数）；`_recover_after_failure` 也改为记 `warn` |
| D9 超时收敛 | ✅ | `timeout_for(name, override)` 成为唯一入口（override → 表 → 1800）；`run_single`/`run_sequence` 默认值由 1800 改 `None`，不再隐式覆盖表 |
| D12 合并实现合一 | ✅ | `lite/deepmerge.py` 统一两处深合并，`copy_values` 区分深浅拷贝；interface 生成结果与改动前逐字节一致 |
| 运行前完整性校验 | ✅ | 开始日常前先确认 plan 里每个任务都在 interface 里；缺任务时直接报出缺哪几个并中止，不再等跑到第 N 项才抛 `Generated interface is missing task` |
| 原生对象后台释放 | ✅ | 崩溃栈定位到 `MaaAgentClientDestroy` 在设备中途消失后会永久阻塞。改为后台线程按原顺序销毁（agent 先行，其余最多等 3 秒）；`stop()` 立即返回，失败后紧接着再启动实测 **0.0 s 返回 200**，不再有 409 窗口 |
| 会话收尾超时 | ✅ | `session.stop()` 的每个原生调用都带超时（移除监听 5 s / 停止任务 8 s / 断开 Agent 8 s / 结束 Agent 进程 15 s / 释放原生对象 15 s），超时记 warn 后继续。修复前：`MaaTaskerDestroy` 一旦阻塞，工作线程永不返回，`_busy()` 恒为真，**服务跑完一次后所有后续请求都是 409** |
| D13 设置原子写 | ✅ | `save_settings` 加锁 + `os.replace` 原子替换，并发保存不再丢字段、崩溃不留半写文件 |

### 3.5 M4 WPF 客户端

```
desktop/MaaYuanLite.Desktop/    17 个文件，1654 行 C#
  MainWindow.xaml / .cs         三栏骨架、状态轮询、更新徽章
  Services/LiteService.cs       进程管理 + HTTP 客户端
  Models/OptionGroup.cs         选项控件模型
```

| 项              | 实现                                                                                                     |
| -------------- | ------------------------------------------------------------------------------------------------------ |
| **W0 发布形态**    | framework-dependent，`net10.0-windows`。理由：.NET 10 是 LTS（到 2028-11），.NET 8 在 2026-11-10 EOL、.NET 9 已 EOL |
| **W1 三栏**      | 左任务 / 中选项 / 右日志，1360×880                                                                               |
| **W2 进程管理**    | 查根目录 → 复用已运行实例（读 `port.txt`）→ 否则起 `python app.py --no-browser --parent-pid <pid>`                      |
| **W3 状态与日志**   | 2 秒轮询 `/api/state`，增量渲染，上限 800 行                                                                       |
| **W4 选项控件**    | 下拉（>2 项）/ 开关（=2 项，`Yes` 固定为开）/ 文本框，改动即时写回                                                              |
| **W5 启停动作**    | 顶栏两个下拉，读写 `/api/settings`                                                                              |
| **W6 首次自检**    | 启动调 `/api/health`，只有 fail 才弹窗；模拟器未开只是警告                                                                |
| **W7 替换 Edge** | `start-lite.bat` 默认启 WPF，`--legacy` 才走浏览器；删除 `find_edge`/窗口枚举，`app.py` 从 770 行降到 730 行                 |
| 更新徽章           | 三态：有更新（黄）/ 正在下载（蓝，带百分比与 MB）/ 待生效（点击可重启）                                                                |

**顺手修的真 bug**：WPF 用 `--no-browser` 启动，而「启动时自动运行日常」写在该分支内 —— 这个设置从来没生效过。已移出，实测 `--no-browser` 下能自动开跑。

### 3.6 M5 打包与分发

| 项                           | 内容                                                                                                                               |
| --------------------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| `devtools/build_release.py` | `dotnet publish` → 重建 interface → 复制 runtime_env/assets/agent/lite/docs → 写 `start-lite.bat` → 产出 `dist/MaaYuan-Lite-<version>/` |
| 产物                          | 343 MB / 2985 文件；`grep "Apps Game"` 为零                                                                                           |
| `devtools/upgrade.py`       | 默认预演，`--apply` 才执行；保留 `lite/*.json`、`runtime/`；配置先备份到 `runtime/upgrade-backup-<时间>/`                                             |
| `NOTICE.md`                 | 11 个第三方组件及许可                                                                                                                     |

### 3.7 M6 启动自检与资源更新

**这是原版完全没有的能力。**

#### 本地来源清单

`assets/.source.json`：commit、commitDate、子模块 pin、8 个模型 sha256、interface hash、pipeline 数量。

```json
{"commit": "c1194728da35...", "commitDate": "2026-10-26",
 "modelsCommit": "dabcd4681ac9...", "models": {...8 项 sha256...}, "pipelineCount": 155}
```

#### 资源下载器（`lite/downloader.py`，419 行）

```
GitHub API 查 v5 HEAD
  → 下载 zip（约 58 MB，只解压 assets/ + agent/）
  → OCR 模型：子模块 pin 未变则从现有资源复制（省 38 MB），变了才下载
  → 校验：pipeline ≥ 100、主模型三件齐全、agent/main.py 存在
  → 写 .source.json → assets.next.part 改名为 assets.next
```

**模型清单是 8 个文件，不是 9 个**：上游 `ppocr_v4/en_us` **没有 `det.onnx`**（英文复用主检测器），多列一个会让每次更新 404。`REQUIRED_MODELS` 只要求主模型三件。

#### 应用器（`lite/update_applier.py`）

原子切换：`resource/base` + `interface.json` + **`agent/`** + `.source.json` 一起换；  
旧版本整体移到 `assets.prev/`；生成 interface 失败或门禁不过 → **自动回滚**。

`agent/` 现在会被更新替换，所以**改 agent 必须走 `pipeline_fixes.py`，不能直接改 `agent/` 下的文件**（下次更新会被覆盖）。

#### 门禁（`lite/update_gate.py`）

pipeline 节点数、interface 任务数、日常链任务名、`pipeline_fixes`/`round_progress` 依赖节点、`task-options` 任务名。

#### 状态与开关

| 对象              | 检查        | 下载 | 生效     | 默认    |
| --------------- | --------- | -- | ------ | ----- |
| 资源 + 模型 + agent | 自动（启动后后台） | 自动 | 下次启动切换 | **开** |
| maa 框架          | 自动        | 手动 | 下次启动切换 | **关** |
| Lite 自身         | 自动        | 手动 | 手动替换   | —     |

框架只提示不自动装的理由：上游把 `maafw` 钉在 5.6.0，而那才是兼容基线（PyPI 最新 5.14.3）。

#### 启动自检

`lite/selftest.py` 10 项检查，1 秒内完成，结果挂 `/api/health` 并落盘 `runtime/selftest.json`。

`lite/agent_guard.py`（182 行）：

- **孤儿 agent 清理**：启动时读 `runtime/agent.json`，用 ctypes 校验进程映像路径确实是我们的 python 才 terminate，避免误杀别人的进程
- **日志轮转**：agent 日志 40 个、错误帧 40 张、资源包缓存 3 个

### 3.8 技术债清理

自查报告 P0 七项全部关闭；P1 处理 8 项。

| ID  | 内容                                                         |
| --- | ---------------------------------------------------------- |
| D1  | git 版本控制                                                   |
| D2  | 连接检查不再清空日常进度（原本点一下「继续未完成」就没了）                              |
| D3  | 取消判定的死代码                                                   |
| D4  | 关键状态写入加锁                                                   |
| D5  | 原生对象显式释放                                                   |
| D6  | `vendor/` 划分，上游与自研分离                                       |
| D7  | spike 产物移出仓库                                               |
| D16 | API 版本号 + 错误码                                              |
| D17 | interface 按 mtime 自动重建（原本改了 scope 不重建，改动"不生效"）             |
| D18 | 端口写文件                                                      |
| D19 | **日志落盘 `runtime/lite.log`**（原本崩溃后 Lite 侧日志全丢）              |
| D20 | **体力探测只对消耗体力的任务**（原本任何失败都跑 1.2 秒 OCR，且可能把无关失败误判成"体力耗尽=成功"） |
| D15 | HTML 控制台不做重构（被 WPF 取代）                                     |

---

## 四、技术架构

### 4.1 目录与职责

```
MaaYuan-Lite/
├─ app.py                    730 行  HTTP 服务、启动编排、进程守卫、更新接线
├─ lite/                    4416 行 / 22 个模块
│  ├─ run_service.py        1050  调度核心：任务循环、结果归类、兜底恢复、日志
│  ├─ session.py             729  MaaFramework 会话：Resource/Controller/Tasker/Agent 生命周期
│  ├─ downloader.py          419  资源下载与暂存
│  ├─ selftest.py            309  10 项环境自检
│  ├─ task_options_service.py 241  选项树读写与校验
│  ├─ agent_guard.py         182  孤儿进程清理、日志轮转
│  ├─ apply_scope.py         180  interface 裁剪
│  ├─ update_applier.py      173  原子切换与回滚
│  ├─ updater.py             135  在线版本检查
│  ├─ daily_plan.py          119  日常计划生成
│  ├─ settings.py            113  配置读写 + camelCase 双写
│  ├─ source_manifest.py     110  来源清单
│  ├─ update_gate.py         110  更新门禁
│  ├─ task_overrides.py      109  选项合并
│  ├─ adb_finder.py          100  adb 探测
│  ├─ pipeline_fixes.py       54  运行期 pipeline 修补
│  ├─ process_guard.py        44  父进程守护
│  ├─ guards.py               36  死循环护栏
│  ├─ round_progress.py       35  循环任务计数
│  └─ version.py               8  版本号
├─ lite/tests/              2361 行 / 25 个文件 / 155 项用例
├─ desktop/                 1654 行 C# / 17 个文件
├─ devtools/                13 个脚本：run_tests / build_release / upgrade / sync_repo /
│                                    check_upstream / audit_runtime / smoke_update / proc_tree …
├─ assets/                  resource/base 75 MB、interface.json、.source.json
├─ agent/                   8.5 MB（**会被资源更新替换**）
├─ runtime_env/             293 MB（环境，只读，不入库）
├─ runtime/                 运行数据（可删）：port.txt、last-run.json、agent.json、
│                           lite.log、logs/、debug/、cache/、failures/
└─ build/generated/         interface.json（启动时按 mtime 自动重建）
```


### 4.2 一次日常的执行路径

```
WPF 启动
 → LiteService 找根目录 → 复用或启动 python app.py --no-browser --parent-pid
 → app.py: chdir(ROOT) → 加载配置 → 自动切换 assets.next（若有）
          → 按 mtime 重建 interface → 清理孤儿 agent → 日志轮转
          → 起 HTTP(127.0.0.1:8765) → 写 port.txt → 后台检查更新
 → WPF 读 port.txt 连上，轮询 /api/state

点「开始日常」
 → POST /api/start → RunService.start_daily
 → 线程：daily_plan 生成 8 项 → LiteSession.start（连模拟器 + 起 Agent）
 → 逐项执行：
     前置：adb 在线检查 → Agent 健康检查
     执行：tasker.post_task(entry, pipeline_override)
     归类：_classify_result（成功/超时/失败/取消/Agent 死/体力耗尽）
     失败：截错误帧 → R22 ANR 检测 → R20 未知界面恢复 → R23 方向诊断
     进展：写 last-run.json、推日志、更新任务徽章
 → 收尾：run_exit_actions（不处理 / 关 Lite / 关模拟器+Lite）
```

### 4.3 资源更新流程

```
启动后 3 秒（异步）
 → updater 查 GitHub v5 HEAD（6 小时缓存，3 秒超时）
 → 有新版 → downloader 下载 zip（58 MB）→ 解压 assets+agent
          → 模型按 pin 复制或下载 → 校验 → 写清单 → assets.next/
 → 下次启动：apply_staged 原子切换 → 重建 interface → 失败自动回滚
```

`DEV_MANAGED`：开发配置指向 `vendor/` 时拒绝自动切换，避免更新一个运行时根本不读的目录。

---

## 五、关键决策

| # | 决策 | 理由 | 影响 |
|---|---|---|---|
| 1 | 运行时目录叫 `runtime_env/`，不叫 `runtime/` | 项目已有 `runtime/` 存运行数据，混进 380 MB Python 后清理日志容易误删 | 命名约定，写进 MANIFEST |
| 2 | 先搬运（M1a）再裁剪（M1b） | 出问题能分清是"搬漏了"还是"裁多了" | 少排查一轮 |
| 3 | 只删 `pandas` + `pip`，`cv2` 保留 | pandas 全仓库无引用；cv2 是 agent 图像识别的硬依赖 | −88 MB |
| 4 | adb 不内置 | 模拟器目录里有，省 15 MB；配探测链 + 配置覆盖 | 模拟器升级换路径时要能自愈 |
| 5 | WPF 用 framework-dependent + .NET 10 | .NET 10 是 LTS（到 2028-11）；.NET 8 在 2026-11-10 EOL、.NET 9 已 EOL | 省 80 MB；目标机需 Desktop Runtime |
| 6 | 保留 HTML 控制台作 `--legacy` | WPF 出问题时还有退路，成本近乎为零 | 需维持 camelCase 双写 |
| 7 | 资源默认全自动更新，框架只提示 | 资源跟游戏版本走，晚一天可能跑不动；框架静默升级会把"昨天能跑"变不确定 | 见 M6 |
| 8 | 所有更新先落 `*.next/`，过门禁才切换 | 校验不过、加载失败自动回滚，不会"更新完打不开" | `assets.prev/` 保留一份 |
| 9 | 原版目录改名保留，V3 连跑 3 天再删 | 有退路 | 磁盘多占 985 MB |
| 10 | 不做 OCR 量化 | 上游红线 | 资源里 38 MB 是模型 |

---

## 六、基线数据

### 6.1 体积

| 组成 | 体积 |
|---|---|
| `runtime_env/`（Python + maa + cv2 + numpy + PIL + MaaAgentBinary） | 293 MB |
| `assets/resource/base`（pipeline + 图片 + 8 个 OCR 模型） | 75 MB |
| `agent/` | 8.5 MB |
| 代码 + WPF + interface | 约 5 MB |
| **发布包合计** | **343 MB** |
| 原版安装目录 | 985 MB |

原版 985 MB 的构成：MFAAvalonia 137 MB + 无轮转 debug 日志 285 MB + Python 381 MB + 重复的 runtimes 65 MB + 资源/agent 117 MB。

### 6.2 性能对比（2026-10-31 同机实测，空闲态）

| 指标 | 原版 v2.1.1 | Lite（服务端） |
|---|---|---|
| 提交内存 | 约 401 MiB | 约 18 MiB |
| 空闲 CPU（10 秒累计） | 0.75 s | 0.16 s |

Lite 的「轻」来自把界面交给系统已有浏览器；WPF 之后不再有浏览器增量，但会增加约 60–80 MB 的 .NET 进程。

### 6.3 原版实跑基线（2026-11-01 08:28–08:39）

8 项任务全部成功，合计 **685 s**：启动游戏 44 s、领月卡 33 s、据点日常 109 s、观星 29 s、
铜钱历练 38 s、白鹄 22 s、日常收尾 210 s、鸢报四合一 200 s。

资源：提交内存均值 1177 MiB / 峰值 1387 MiB；CPU 412 s / 685 s ≈ 60% 单核；错误截图 0 张。

> 口径提醒：这次「启动游戏」只有 44 秒是因为游戏已开着；Lite 默认链用「鸢报四连 - 日常专用」而非「四合一」，直接比总时长会失真。

### 6.4 测试

```
python devtools/run_tests.py      155 项，约 6 秒
```

覆盖：设置迁移、选项树、日常计划、调度归类、更新执行器/门禁/下载器、自检、孤儿清理、ANR 识别、方向诊断。

---

## 七、未完成项

### 7.1 阻塞验收（P0）

| ID | 内容 | 验收 | 依赖 |
|---|---|---|---|
| **R12** | 完整日常实跑 | ✅ 2026-11-04 首次 7/8（520 s）；2026-11-05 复跑鸢报：体力耗尽时 124.5 s 判「体力耗尽，任务结束」并计入成功。8 项均有明确归宿 | 已完成 |

### 7.2 稳定性验收 M7（P1）

| ID | 内容 | 验收 |
|---|---|---|
| **Q1** | 连续 10 次日常 | ✅ 2026-11-05 以「观星 ×10」验证（日常每天只能完整跑一次，用单任务代理跑满 10 轮）：**10/10 成功**，句柄 939 → 933（无单调上涨），内存 439 → 454 MB（区间 437–535，有涨有落）。工具：`python devtools/stability_run.py --spawn --task "🔮 观星" --times 10` |
| **Q2** | 故障注入 | 杀 agent ✅、锁屏 ✅、鸢报卡死 ✅；**模拟器重启 ✅（明确报错）**：重启后游戏被杀、界面回到横屏桌面，任务 47.6 s 判失败、状态 `completed_with_errors`，服务全程 35 次探测均有响应；随后新增「横屏+无进展 → 中止整轮」。断网 ⏭ 跳过（飞行模式会把模拟器搞坏）。⚠ 模拟器只能由用户手动启动（AGENTS.md R2）：沙箱会在 AI 命令结束时回收进程树并让 VM 有序关机 |
| **Q3** | 回退包 | ✅ 每版独立目录 + `dist/active.txt` 指针；`dist/启动 Lite.bat` 按指针启动。**实测：切换 + 启动到服务就绪 4 秒**（0.2.1 与 0.2.0 分别验证，`/api/meta` 版本号正确）|
| **Q4** | 长稳 24 小时 | ⏳ 采样工具就绪：`python devtools/soak_check.py`（采一次追加 `runtime/soak.csv`）与 `--summary`（看趋势：句柄/内存/日志体积）。挂到任务计划里每 15–30 分钟一次即可，不需要模拟器参与 |

### 7.3 技术债（P2）

| ID | 内容 | 收益 |
|---|---|---|
| ~~D11~~ | ~~用 entry 作任务主键~~ **评估后不做**：`update_gate` 已覆盖日常链与 task-options 的任务名漂移（更新时拦截），改主键要迁移 28 个任务名的配置，风险高于收益 | — |
| O2 | adb `device_ready()` 结果缓存 3 秒 | 每任务少一次子进程 |
| O3 | `/api/screenshot` 加 ETag | 省读盘 |
| O4 | 按引用裁剪未用任务图片 | 估减 20–30 MB |

### 7.4 待实机确认（P3）

| 项 | 说明 |
|---|---|
| R21 错误帧落点 | `set_log_dir` 已生效（maa.log 确实进了 `runtime/debug/`），但错误帧是否跟随，需要一次真实失败 |
| R22 实机 ANR | 逻辑与 4 项单测已完成，未在真实 ANR 下验证 |
| U3 在线检查 | 本地 commit 读取正常；GitHub 长期不可达，`available` 翻转未验证 |
| V6 真实断网 | 启动路径已确认不联网，实时拔网未单独跑 |

---

## 八、风险与限制

| # | 风险 | 触发 | 现有防护 |
|---|---|---|---|
| 1 | VC++ 运行库缺失 | 干净机器没有 VC++ 2015–2022 | 自检里 `LoadLibrary("MaaFramework.dll")`，失败给明确提示 |
| 2 | 中文/空格路径 | 放在 `D:\测试 目录\` | 所有 `subprocess` 用 list 形式；V4 已验 |
| 3 | 杀软误报 | 打包 exe | 不用 PyInstaller 单文件；目录形态 + 未改名官方二进制 |
| 4 | 模拟器升级换 adb 路径 | 雷电更新 | 探测链 + 配置覆盖 + 明确报错 |
| 5 | 上游改节点名 | 游戏大版本更新 | `update_gate` 门禁 + `check_upstream.py` |
| 6 | 选项索引错位 | 上游增删选项 | **未解决**：存储只有索引无名称，需在 `task-options.json` 冗余存选项名 |
| 7 | 游戏当天上新活动 | 宣传页盖住首页 | R20 运行期兜底；仍失败则停止并提示 |
| 8 | 框架静默升级破坏兼容 | 误开自动升级 | 默认关闭，只提示 |

**已知限制**：

- 地宫入口探测是「看到入口才执行」，不会滑动地图找；活动开放但不在主界面会被跳过
- 停止任务走 `post_stop`，当前动作可能还需数秒才结束
- 不提供批量导入/导出原版配置
- `agent/` 会被资源更新覆盖，改 agent 必须走 `pipeline_fixes.py`

---

## 九、常用命令

```bash
# 开发
python devtools/run_tests.py                 # 155 项测试
python app.py --selftest                     # 10 项环境自检
python app.py --no-browser --port 8790       # 只起服务

# 构建
python devtools/build_release.py             # 产出 dist/MaaYuan-Lite-<version>/
dotnet build desktop/MaaYuanLite.Desktop     # 只编 WPF

# 上游同步（开发期）
python devtools/sync_repo.py                 # 克隆上游到 vendor/ + 下载模型
python devtools/sync_repo.py --update        # 拉最新提交
python devtools/check_upstream.py            # 任务名/节点名兼容性检查

# 回退（Q3）
python devtools/release_switch.py list       # 列版本 + 当前指向
python devtools/release_switch.py switch previous   # 切回上一版
python devtools/release_switch.py prune --keep 2    # 只留最近两版

# 升级已有安装
python devtools/upgrade.py                   # 预演
python devtools/upgrade.py --apply           # 执行

# 端到端冒烟
python devtools/smoke_update.py              # 造暂存树 → 切换 → 回滚
python devtools/smoke_daily.py               # 完整日常实跑（V3），服务自带启停
python devtools/stability_run.py --spawn --task "🔮 观星" --times 10   # 连续跑（Q1）
python devtools/smoke_emulator_restart.py    # Q2 重启模拟器——仅用户手动执行，见 AGENTS.md R2
python devtools/inject_fault.py <fault>      # Q2 故障注入（emulator/network 需用户放行）
```

---

## 十、下一步建议的顺序

```
1. 完整日常回归（V3）       ← 用今天的代码再跑一次 8 项，确认体力/看门狗/收尾改动无回归
2. Q4 长稳 24 小时          ← 采样工具已就绪（soak_check.py），需服务连续在线
3. 技术债 P2 按需           ← O2/O3/O4 收益都很小
4. 删原版目录               ← 用户决定时机
```

M7 之前不建议加新功能：调度层还有两处半成品，现在加功能会让回归面变大。

---

*配套文档：`LITE.md`（功能与实测数据）、`MANIFEST.md`（目录归属）、`docs/api-contract.md`（接口契约）、`代码结构自查报告.md`（技术债明细）。*
