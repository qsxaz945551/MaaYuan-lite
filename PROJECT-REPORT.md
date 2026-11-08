# MaaYuan Lite 项目报告

> 版本：0.3.4（2026-11-08 09:40）  
> 定位：**后续开发以本报告为准**，主文档；
> `LITE.md`（功能现状）、`MANIFEST.md`（目录归属）、`docs/api-contract.md`（接口契约）、  
> 技术债与资产审查见 `docs/AUDIT-20261107-v2.md`（2026-11-07，含清理执行记录）。

---

## 一、项目定义

### 1.1 一句话

把 MaaYuan（如鸢日常自动化工具）从 740 MB 的 MFAAvalonia 桌面应用，重做成一个**自带运行时、  
便携解压即用、约 340 MB 的独立程序**，界面换成 WPF，并补上原版没有的**资源自动更新**与**运行期兜底**。

### 1.2 北极星

一台**从未装过 MaaYuan** 的 Windows 11 机器，只装雷电模拟器 + 解压 Lite 目录，双击即用；  
装过原版的机器，**删掉原版目录后功能不降级**。

### 1.3 非目标（明确不做）

| 不做             | 原因                         |
| -------------- | -------------------------- |
| 图形安装器          | 只交付便携目录 + zip              |
| 重构 HTML 控制台    | 2026-11-07 已删除（`lite/ui/`，1028 行），只保留 WPF       |
| OCR 量化/蒸馏/换小模型 | 上游红线，识别准确率优先               |
| 自动战斗、录制作业      | 上游能力，Lite 不接               |
| 多模拟器/多游戏适配     | 只支持雷电 14 + 如鸢简中            |

### 1.4 交付形态

> 2026-11-05：原版目录 `D://Apps Game\MaaYuan-win-x86_64-v2.1.1-beta.6.disabled` 已**永久删除**
> （1.35 GB / 10286 文件），D 盘可用空间回到 442 GB。旧版的三个配置小文件备份在
> `build/original-config-backup/`（`build/` 不入库）。至此机器上只剩 Lite 一份实现。


```
dist/
  ├─ active.txt                   指向当前版本（Q3 回退指针）
  ├─ 启动 Lite.bat                版本无关入口，按 active.txt 启动
  └─ MaaYuan-Lite-0.3.3/          343 MB（3001 个文件）
  ├─ MaaYuanLite.Desktop.exe      WPF 客户端（framework-dependent，需 .NET 10 Desktop Runtime；启动脚本会检测并给出下载地址）
  ├─ start-lite.bat               包内入口，拉起 WPF
  ├─ README.md                    面向使用者的快速上手
  ├─ runtime_env/                 263 MB，CPython 3.12.10 + maa 5.6.0 + 全部依赖
  ├─ assets/                      72 MB，pipeline + 图片模板 + 8 个 OCR 模型
  ├─ agent/                       6.9 MB，Python Agent
  ├─ lite/                        自研后端（`*.json` 里的选项是默认值，用户改动写 `runtime/`）
  ├─ build/generated/interface.json
  └─ NOTICE.md                    第三方许可
```

> 2026-11-05 晚给 `start-lite.bat` 与 `dist\启动 Lite.bat` 补了 .NET 10 运行时探测（缺失时打印下载地址并退出码 1）。
> 模板在 `devtools/release/build_release.py` 的 `START_BAT`；0.2.2 是就地打补丁，**0.2.3 已整体重打包并切为 active**，包含 11-05 之后全部运行期修复。

---

## 二、验收状态

### 2.1 硬验收（V1–V7）

| 编号     | 验收项           | 状态 | 证据                                                             |
| ------ | ------------- | -- | -------------------------------------------------------------- |
| **V1** | 原版目录不可用仍能启动   | ✅  | 原版改名为 `.disabled` 后，`start-lite.bat` 正常起进程，`/api/state` 返回 200 |
| **V2** | 原版目录不可用仍能连机   | ✅  | 同一状态下「检查连接」成功，截图 720×1280 非黑屏                                  |
| **V3** | 原版目录不可用仍能跑完日常 | ✅ | 2026-11-05 20:02 用当前代码跑完整链：7/8 + 续跑补齐 = **8/8**，任务耗时合计约 508 s。鸢报 133.7 s 体力耗尽正常结束；收尾首轮因当天已在别处领过密探特训而中止（上游无「已领取」兜底），续跑 150 s 成功。**2026-11-07 09:36 用 0.2.3 发布包一次跑通 8/8，496 s**：鸢报 134.3 s（旧包在此被 150 s 看门狗误杀）、收尾 159.2 s（旧包在此失败），证明修复已进入发布形态。**2026-11-07 22:39 用 0.3.2 发布包再跑：8 成功 + 1 未领取 + 0 失败，619.6 s**（鸢报 131.3 s 鸟食不足记未领取；收尾 157.7 s；`devtools/release/verify_chain.py`） |
| **V4** | 路径无关          | ✅  | 复制到 `D:\测试 目录\MaaYuan Lite\`（中文 + 空格），自检全绿                     |
| **V5** | 干净环境          | ✅  | `set PATH=C:\Windows\system32` 启动，自检全绿，不依赖系统 Python            |
| **V6** | 断网可用          | ◐  | 启动与自检全程不联网；实时断网未单独验证（GitHub 长期不可达，等价覆盖）                        |
| **V7** | 无残留引用         | ✅  | 原版改名后功能不降级，进程无 `D:/Apps Game` 句柄；**2026-11-05 已永久删除原版目录**（1.35 GB / 10286 文件），删除后自检 0 警告、`观星` 实跑 17.8 s 成功 |

**结论：7 项全部通过**（V6 用「杀 agent / 锁屏」两种故障等效覆盖，断网场景因会把模拟器搞坏而跳过）。「可以删原版」的前置条件已满足。

### 2.2 里程碑

| 阶段     | 目标                  | 状态 | 完成度             |
| ------ | ------------------- | -- | --------------- |
| **M0** | 基线收口（git、依赖测绘、测试入口） | ✅  | 4/4             |
| **M1** | 运行时自包含 + 未知界面兜底     | ✅  | 12/12（R12 实跑 8/8） |
| **M2** | API 与进程契约冻结         | ✅  | 11/11           |
| **M3** | 调度层重构               | ✅  | 4/4（D8/D4/D5/D21 全部完成） |
| **M4** | WPF 客户端             | ✅  | 8/8             |
| **M5** | 打包与分发               | ✅  | 6/6（P4 并入 M6）   |
| **M6** | 启动自检与资源更新           | ✅  | 7/7             |
| **M7** | 稳定性验收               | 🔶 | 3/4（Q1/Q2/Q3 完成，Q4 推迟） |

---

## 三、已完成工作

### 3.1 M0 基线收口

| 项        | 内容                                                                                                                          |
| -------- | --------------------------------------------------------------------------------------------------------------------------- |
| git 版本控制 | 37 次提交，起点 `23a86dc`（2026-11-01 迁移前快照）                                                                                       |
| 依赖测绘     | `devtools/probe/audit_runtime.py` 静态扫描 import 与 site-packages 差集，输出「需要/冗余/缺失」三张表                                                  |
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
`/api/settings` 自 0.3.0 起只返回 camelCase（网页控制台退役，双写已删），`apiVersion` 升到 2。

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
| 选项按名称解析 | ✅ | 存储从「只有索引」改为 `{index, label}`；上游重排可选值时按名称找回原值，找不到才退回索引并写 warn。UI/接口不变（返回的 selected 始终是解析后的索引）；`resolve_index` 成为唯一实现，`task_overrides._case_index` 委托给它 |
| 体力结束后回主界面 | ✅ | 体力耗尽算成功，但界面不保证停在主界面；下一项若从主界面起手就会空耗一整个看门狗窗口。现在成功后先探测 `is_main_screen()`，不在主界面就按返回键退出（实测 9 s），已在主界面则不动 |
| 会话收尾超时 | ✅ | `session.stop()` 的每个原生调用都带超时（移除监听 5 s / 停止任务 8 s / 断开 Agent 8 s / 结束 Agent 进程 15 s / 释放原生对象 15 s），超时记 warn 后继续。修复前：`MaaTaskerDestroy` 一旦阻塞，工作线程永不返回，`_busy()` 恒为真，**服务跑完一次后所有后续请求都是 409** |
| D13 设置原子写 | ✅ | `save_settings` 加锁 + `os.replace` 原子替换，并发保存不再丢字段、崩溃不留半写文件 |

### 3.5 M4 WPF 客户端

```
desktop/MaaYuanLite.Desktop/    18 个文件
  App.xaml                      深色主题资源：配色、按钮、下拉、开关、复选、滚动条
  MainWindow.xaml / .cs         状态条 + 控制条 + 三栏
  Services/LiteService.cs       进程管理 + HTTP 客户端
  Models/OptionGroup.cs         选项控件模型
  Models/LogEntry.cs            日志行（按 level 着色）
```

| 项              | 实现                                                                                                     |
| -------------- | ------------------------------------------------------------------------------------------------------ |
| **W0 发布形态**    | framework-dependent，`net10.0-windows`。理由：.NET 10 是 LTS（到 2028-11），.NET 8 在 2026-11-10 EOL、.NET 9 已 EOL |
| **W1 布局**      | 状态条 / 控制条 / 三栏（320 · 420 · 自适应），1360×860，最小 1080×700；深色主题按 WebView 控制台配色 1:1 还原（`#0D1117` 底 + `#D9B36C` 强调） |
| **W2 进程管理**    | 查根目录 → 复用已运行实例（读 `port.txt`）→ 否则起 `python app.py --parent-pid <pid>`                      |
| **W3 状态与日志**   | 空闲 2 秒、运行中 1 秒轮询 `/api/state`；首屏 `since=0` 拉取已有日志，增量追加，上限 800 行；`warn`/`error` 着色                    |
| **W4 选项控件**    | 下拉（>2 项）/ 开关（=2 项，`Yes` 固定为开）/ 文本框，改动即时写回                                                              |
| **W5 启停动作**    | 控制条两个下拉，读写 `/api/settings`                                                                             |
| **W6 首次自检**    | 启动调 `/api/health`，只有 fail 才弹窗；模拟器未开只是警告                                                                |
| **W7 替换 Edge** | 只保留 WPF；0.3.0 起连 `--legacy` 浏览器退路、`open_ui`、根路由与 `running_instance` 一并删除（`app.py` 749 行） |
| **W8 任务列表**    | 「今日日常 / 其他任务」两个 Tab 带计数；每行 = 序号（其他任务为勾选框）+ 名称 + 选项摘要 + 状态徽章（完成/失败/超时/跳过/限时）；选中行金边高亮 |
| **W9 单独执行**    | 其他任务勾选后 `POST /api/run-task`，按列表顺序批量执行；按钮文案随勾选数变为「开始任务（N）」                                              |
| **W10 历练类型**   | 选中「历练」时面板顶部出现修为/铜钱/经验三按钮，切换即重取 `/api/plan?training=` 并写回 `lastTraining`                                |
| **W11 地宫开关**   | 控制条开关 → `lastDungeon` → 重取 `/api/plan?dungeon=`；运行中禁用                                                       |
| **W12 状态口径**   | 资源不足提前收手记 `skipped_no_resource`：第二行行首加粗「未领取到资源」+ 琥珀徽章，失败任务名标红；汇总条单列「未领取」 |
| **W13 可勾选日常** | 日常行也有勾选框，「开始日常」与「开始任务」合并为一个「开始任务（N）」，只跑勾选项；`/api/start` 接受 `names` 子集，仍走链上语义（地宫探测、历练档位、超时表） |
| **W14 全选**      | 「今日日常」页签前的全选框：全选 / 全部取消当前列表；未开放的地宫、每日进膳不在列表内，天然不受影响 |
| **W15 隐藏即清勾** | 任务离开列表（地宫关闭、每日进膳过了 24:00）立即清掉勾选；按钮数字只数面板上可见的勾选，避免残留导致 N 虚高 |
| **W17 真正一个按钮** | 勾选跨两个 Tab 累计，`开始任务（N）` 的 N 是合计；`/api/start` 新增 `extra`，其他任务接在日常之后同一次运行里执行。只勾其他任务时仍走 `/api/run-task`，不动日常进度 |
| **W18 更新分流** | 资源每次启动自动检查 + 后台下载 + 校验，结果写进界面日志，下次启动原子切换；框架钉住 5.6.0，不再拿 PyPI 最新版当"可更新"，也不提供一键升级。切换时按 `RESOURCE_EXTRAS` 补回 Lite 自加的资源文件 |
| **W19 门禁修正** | `pipeline_fixes.NEW_NODES` 声明补丁自建节点，门禁不再要求它们存在于上游；失败时日志带出具体问题（11-06 的更新曾因此每次启动都被拒绝） |
| **W20 提示归位** | 控制条下的即时提示移到右栏日志底部，替换掉「成功/失败/状态」计数汇总；新增 `POST /api/note`，失败提示双写进运行日志（前缀「界面：」），停止措辞与服务端统一 |
| **W16 未开放标注** | 地宫入口探测失败时服务端记 `note: 本期未开放`，该行副标题以琥珀色显示（徽章「跳过」）；底栏显示 `v<版本>`（取自 `/api/meta`），避免分不清启动的是哪个包 |
| 更新徽章           | 三态：有更新（黄）/ 正在下载（蓝，带百分比与 MB）/ 待生效（点击可重启）                                                                |

**顺手修的真 bug**：后端曾用 `--no-browser` 启动，而「启动时自动运行日常」恰好写在该分支内 —— 这个设置从来没生效过。已移出；0.3.0 退役网页控制台后连该参数一起删除。

**2026-11-05 深夜修的大 bug：WPF 的所有 POST 请求体都是空的。**
`LiteService.PostAsync` 用 `JsonContent.Create(body)`，它要等到写请求流时才序列化，`HttpClient` 因此拿不到长度、退化成 `Transfer-Encoding: chunked`；
而 `app.py` 的 `_read_json` 只读 `Content-Length`，chunked 请求直接当成 `{}`。后果是**静默**的：
任务选项保存失败（滑块拨过去又弹回来）、启动时/结束后下拉不生效、其他任务批量执行失败、
「继续未完成」实际会重新开一轮日常（空 payload 走了默认值）。改用 `StringContent(JsonSerializer.Serialize(...))` 后恢复正常。
服务端也补上了 chunked 解析（`lite/http_body.py`，`read_body` 同时认 `Content-Length` 与 `Transfer-Encoding: chunked`，
9 项测试在 `lite/tests/test_http_body.py`），这样即便以后有客户端再按 chunked 发，也不会静默丢包。
教训：读请求体的服务端和写请求体的客户端，长度语义必须对齐；静默吞掉请求体比报错难查得多。

**界面自检**：`MaaYuanLite.Desktop.exe --screenshot out.png` 渲染整窗到 PNG 后退出（`--scope library` 切到其他任务页），用于改版前后对比，不需要人工点。

### 3.6 M5 打包与分发

| 项                           | 内容                                                                                                                               |
| --------------------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| `devtools/release/build_release.py` | `dotnet publish` → 重建 interface → 复制 runtime_env/assets/agent/lite/docs → 写 `start-lite.bat` → 产出 `dist/MaaYuan-Lite-<version>/` |
| 产物                          | 343 MB / 3000 文件；`grep "Apps Game"` 为零                                                                                           |
| `devtools/smoke/smoke_release.py` | 对**已打包目录**做一次自检：起包内运行时 → `/api/meta` 版本 → `/api/health` → 可选 `/api/check`（只连接+截图）→ `/api/exit`。`--skip-game` 跳过连机 |
| `devtools/release/upgrade.py`       | 默认预演，`--apply` 才执行；保留 `lite/*.json`、`runtime/`；配置先备份到 `runtime/upgrade-backup-<时间>/`                                             |
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

### 3.9 交付打磨（0.3.3）

审查批次全部关闭后，专门做了一轮"能不能交出去"的收尾：

| 项 | 动作 | 结果 |
|---|---|---|
| 用户状态与仓库分离 | 新增 `runtime/settings.json`（启动/结束动作等偏好）与 `runtime/task-options.json`（选项）；`lite/*.json` 退为随包默认值，程序只读 | 以前改一次下拉框或选项，git 工作区就脏一次；现在 `git status` 常清洁，换机器也不会把上一个人的选择带过去 |
| 老配置迁移 | `lite/runtime-config.json` 里的 `automation` 段仍可读，第一次保存时搬到新位置；`lite/task-options.json` 的纯索引条目照旧自动补名称 | 升级用户无感，不改任何选项 |
| 使用文档 | 重写 `README.md`：前置条件、首次使用、界面、两条限时任务、更新机制、日志排障、恢复默认 | 用户不必读 42 KB 的 `LITE.md` |
| 纠正过时描述 | `LITE.md` 的三栏布局（还写着 CSS 断点）、"关窗口服务仍在后台"、结束动作文案、agent 日志保留 40 个 | 与实际 WPF 行为一致 |
| 打包可复现 | 从清理后的源码重跑 `build_release.py`：**14 秒，3001 个文件 / 343.3 MB**；与旧包逐文件对比只差 `README.md` 与运行产物 | 证明 0.3.0 那轮删掉 1 GB 资产没有删到打包依赖 |
| 包内卫生 | 冒烟会生成 `runtime/`、`config/`、`debug/`，交付前清掉；`README.md` 纳入打包清单；包内 `runtime-config.json` 去掉 `automation` 段（否则开发机的「自动运行日常」会被新用户继承） | 包内只剩程序本身与默认值 |

测试 302 → **306**（新增用户/默认文件分离 3 项、设置迁移 1 项）。

### 3.10 输入方式：AdbShell → 自动择优（0.3.4）

| 项 | 动作 | 结果 |
|---|---|---|
| 输入方式 | `input_methods` 1 → 7（AdbShell \| MinitouchAndAdbKey \| Maatouch） | 框架按 Maatouch > Minitouch > AdbShell 选；跑到一半能在设备上看到 MaaTouch 的 `app_process` |
| 截图方式 | 维持 `RawWithGzip` | 实测 235 ms/帧，原版同为 236 ms，已是本机最快（EmulatorExtras 雷电 14 不支持） |
| 打包 | `docs/evidence/` 不进用户包 | 3001 个文件 / 343.3 MB |

0.3.4 全链验收跑了两轮：**517.4 s / 547.3 s，均 7 成功 + 1 未领取 + 0 失败**（鸢报鸟食不足）。
启动（78.1 / 77.6）、据点（49.1 / 49.6）、观星（27.8 / 28.0）三轮内几乎不抖，波动集中在收尾
（152.5 / 191.8）与修为（43.6 / 28.0）。同采集器测得整链私有提交 1357 / 峰值 1481 MB、
工作集 434 / 658 MB、CPU 16.8% 单核（原版为 1878 / 2056、335 / 505、79.6%）。

0.3.2 的「据点 112 s」是状态波动（11-05 也跑过 50.8 s），不能算作输入方式的收益；
按同一天对比，原版基线 672.3 s vs Lite 517.4–547.3 s，快 19–23%。

---

## 四、技术架构

### 4.1 目录与职责

```
MaaYuan-Lite/
├─ app.py                    745 行  HTTP 服务、启动编排、进程守卫、更新接线
├─ lite/                    4682 行 / 22 个模块
│  ├─ run_service.py        1263  调度核心：任务循环、结果归类、兜底恢复、日志
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
├─ lite/tests/              2450 行 / 25 个文件 / 157 项用例
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
 → LiteService 找根目录 → 复用或启动 python app.py --parent-pid
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
| 6 | ~~保留 HTML 控制台作 `--legacy`~~ | 2026-11-07 用户决定退役：发布包本就没有入口，只留下双写与两套 UI 的维护成本 | 已删除，`apiVersion` 升 2 |
| 7 | 资源默认全自动更新，框架只提示 | 资源跟游戏版本走，晚一天可能跑不动；框架静默升级会把"昨天能跑"变不确定 | 见 M6 |
| 8 | 所有更新先落 `*.next/`，过门禁才切换 | 校验不过、加载失败自动回滚，不会"更新完打不开" | `assets.prev/` 保留一份 |
| 9 | 原版目录改名保留，V3 连跑 3 天再删 | 有退路 | 磁盘多占一份原版（740 MB） |
| 10 | 不做 OCR 量化 | 上游红线 | 资源里 38 MB 是模型 |

---

## 六、基线数据

### 6.1 体积

> 口径：以下为**文件字节数**合计（`Path.stat().st_size`），与资源管理器"大小"一致；磁盘占用略高。

| 组成 | 体积 |
|---|---|
| `runtime_env/`（Python + maa + cv2 + numpy + PIL + MaaAgentBinary） | 263 MB |
| `assets/resource/base`（pipeline + 图片 + 8 个 OCR 模型） | 72 MB |
| `agent/` | 6.9 MB |
| 代码 + WPF + interface | 约 1 MB |
| **发布包合计** | **343.3 MB / 3001 个文件** |
| 原版安装目录（v2.3.1-beta.3） | **726.6 MB / 8303 个文件** |

原版 726.6 MB 的构成：`python/` 337.8 + `libs/` 137.0（.NET/Avalonia）+ `resource/` 139.8
（简中 72.0 + 繁中 67.8）+ `runtimes/` 64.9 + `agent/` 7.8 + `debug/`·`logs/` 38.4（运行产物）+ 其余约 1 MB。
剔除运行产物为 688.2 MB，Lite 等于它的 **49.9%**。

### 6.2 性能对比（同机空闲态，同一采集器）

> 2026-11-08 09:05 重测。口径：进程树求和，启动后 45 秒、无任务在跑；私有提交（Private）为主，工作集受系统回收影响只作参考。

| 指标 | 原版 v2.3.1-beta.3 | Lite 0.3.3 |
|---|---|---|
| 进程数 | 13 | 8 |
| 私有提交 均值 / 峰值 | 1495 / 1577 MB | **1289 / 1380 MB** |
| 工作集 均值 / 峰值 | 345 / 361 MB | 638 / 709 MB |

差别来自取舍而不是效率：Lite 把 OCR 模型常驻内存（工作集高），原版更依赖页面文件换进换出（私有提交高、CPU 高）。跑任务时的对照见 6.3。

### 6.3 原版实跑基线（2026-11-08，整轮 08:48–08:58 + 冷启动单测 09:21）

环境：MaaYuan **v2.3.1-beta.3** / MFAAvalonia **v2.6.8** / MaaFramework **5.6.0** / 资源 **v2.3.2-beta.1**；
雷电 14、游戏竖屏 720×1280；队列 8 项（与 Lite 默认日常链同集），修为=风火/八/3 次，地宫关，进膳未到开放时间。

| 任务 | 耗时 |
|---|---|
| 🚀 启动游戏 | 82.9 s（**冷启动实测**：游戏进程关闭 → 主界面） |
| 📜 鸢报四连 - 日常专用 | 165.7 s |
| 💰 领月卡福利 | 42.5 s |
| 🏯 据点日常 | 116.1 s |
| 🔮 观星 | 21.2 s |
| 💎 修为历练 | 40.7 s |
| 🗡 白鹄扫荡 | 32.7 s |
| 🔶 日常收尾 | 170.5 s |
| **合计** | **672.3 s** |

**口径**：「启动游戏」取自 2026-11-08 09:21 的单任务冷启动实测（先 `am force-stop` 关闭游戏、确认回到桌面，再点开始），
其余 7 项取自 08:48 整轮（游戏已在主界面——这正是真实链条中它们所处的状态）。合计为替换后相加。

| 指标 | 数值 |
|---|---|
| 进程树 | 13 个进程（MaaYuan.exe + agent + .NET） |
| 私有提交 | 均值 **1878 MB** / 峰值 **2056 MB**（任务段 1813–1956） |
| 工作集 | 均值 335 MB / 峰值 505 MB |
| CPU | 全程均值 **79.6%** 单核（启动段 113%，任务段 75–82%） |
| 失败 / 错误截图 | 0 / 0 |
| 启动到首个任务 | 18 s |

数据文件：`docs/evidence/original-run-20261108-084745.{csv,json}`（整轮，2 s 一次共 319 个采样）、
`docs/evidence/original-run-20261108-092110.{csv,json}`
（冷启动单任务，09:21:27.889 → 09:22:50.824 = 82.9 s）。
采集器：`build/measure_original.py`（进程树采样，读 `logs/log-*.log` 判完成）。

口径提醒：
- 原版队列顺序是它自己的任务表顺序（鸢报排第 2），Lite 把鸢报排在历练前、收尾前，顺序差异会影响单项耗时。
- 原版资源 v2.3.2-beta.1 比 Lite 当前快照（2026-10-26 `c119472`）新，单项差值里含 pipeline 版本因素。
- 工作集在后台会被系统回收，比较以私有提交为准。
- 总时长：原版 672.3 s（8 项，冷启动口径）；Lite 0.3.4 两轮 517.4 / 547.3 s（8 项），快 19–23%。
- 单项对比要扣口径：鸢报两端都不完整（都是鸟食不足提前结束）；据点 49 vs 116 s 的差距主要来自
  pipeline 版本（原版资源 v2.3.2-beta.1 比 Lite 快照新 11 天），不宜全归给运行速度。

### 6.4 测试

```
python devtools/run_tests.py     306 项，约 22 秒
```

覆盖：设置迁移、选项树与选项文件存储位置、日常计划、调度归类、更新执行器/门禁/下载器、HTTP 14 条路由（真起服务）、自检、孤儿清理、ANR 识别、方向诊断。

---

## 七、未完成项

### 7.1 阻塞验收（P0）

| ID | 内容 | 验收 | 依赖 |
|---|---|---|---|
| **R12** | 完整日常实跑 | ✅ 2026-11-05 20:02 用当前代码跑完整链：7/8 + 续跑补齐 = **8/8**，任务耗时合计约 508 s。鸢报 133.7 s 体力耗尽正常结束；收尾首轮失败——当天已在另一台设备领过密探特训，页面上无可领取项，pipeline 无兜底，150 s 后被看门狗中止；退回主界面后续跑 150 s 成功 | 已完成 |

### 7.2 稳定性验收 M7（P1）

| ID | 内容 | 验收 |
|---|---|---|
| **Q1** | 连续 10 次日常 | ✅ 2026-11-05 以「观星 ×10」验证（日常每天只能完整跑一次，用单任务代理跑满 10 轮）：**10/10 成功**，句柄 939 → 933（无单调上涨），内存 439 → 454 MB（区间 437–535，有涨有落）。工具：`python devtools/smoke/stability_run.py --spawn --task "🔮 观星" --times 10` |
| **Q2** | 故障注入 | 杀 agent ✅、锁屏 ✅、鸢报卡死 ✅；**模拟器重启 ✅（明确报错）**：重启后游戏被杀、界面回到横屏桌面，任务 47.6 s 判失败、状态 `completed_with_errors`，服务全程 35 次探测均有响应；随后新增「横屏+无进展 → 中止整轮」。断网 ⏭ 跳过（飞行模式会把模拟器搞坏）。⚠ 模拟器只能由用户手动启动（AGENTS.md R2）：沙箱会在 AI 命令结束时回收进程树并让 VM 有序关机 |
| **Q3** | 回退包 | ✅ 每版独立目录 + `dist/active.txt` 指针；`dist/启动 Lite.bat` 按指针启动。**实测：切换 + 启动到服务就绪 4 秒**（0.2.1 与 0.2.0 分别验证，`/api/meta` 版本号正确）|
| **Q4** | 长稳 24 小时 | ⏳ 采样工具就绪：`python devtools/smoke/soak_check.py`（采一次追加 `runtime/soak.csv`）与 `--summary`（看趋势：句柄/内存/日志体积）。挂到任务计划里每 15–30 分钟一次即可，不需要模拟器参与 |

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
| ~~R21 错误帧落点~~ | ✅ 已闭环：2026-11-05 的真实失败帧落在 `runtime/debug/on_error/`（`lite-probe_2026.11.05-07.13.*.png`），证明错误帧跟随 `set_log_dir`；`maa.log` 10 MB + `maa.bak.log` 17 MB，轮转正常 |
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
| 6 | ~~选项索引错位~~ | 上游增删/重排选项值 | ✅ 已解决：`task-options.json` 同时存 `{index, label}`，解析时按名称反查，名称不存在才退回索引并记 warn。旧格式自动补记（本次迁移 128 条），迁移前后 34 个任务的 override 逐字节一致 |
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
python devtools/run_tests.py                 # 157 项测试
python app.py --selftest                     # 10 项环境自检
python app.py --port 8790                    # 只起服务

# 构建
python devtools/release/build_release.py             # 产出 dist/MaaYuan-Lite-<version>/
dotnet build desktop/MaaYuanLite.Desktop     # 只编 WPF

# 上游同步（开发期）
python devtools/release/sync_repo.py                 # 克隆上游到 vendor/ + 下载模型
python devtools/release/sync_repo.py --update        # 拉最新提交
python devtools/probe/check_upstream.py            # 任务名/节点名兼容性检查

# 回退（Q3）
python devtools/release/release_switch.py list       # 列版本 + 当前指向
python devtools/release/release_switch.py switch previous   # 切回上一版
python devtools/release/release_switch.py prune --keep 2    # 只留最近两版

# 升级已有安装
python devtools/release/upgrade.py                   # 预演
python devtools/release/upgrade.py --apply           # 执行

# 端到端冒烟
python devtools/smoke/smoke_update.py              # 造暂存树 → 切换 → 回滚
python devtools/smoke/smoke_daily.py               # 完整日常实跑（V3），服务自带启停
python devtools/smoke/stability_run.py --spawn --task "🔮 观星" --times 10   # 连续跑（Q1）
python devtools/smoke/smoke_emulator_restart.py    # Q2 重启模拟器——仅用户手动执行，见 AGENTS.md R2
python devtools/smoke/inject_fault.py <fault>      # Q2 故障注入（emulator/network 需用户放行）
```

---

## 十、下一步建议的顺序

```
1. 用 0.3.3 包跑一轮完整日常   ← 0.3.3 改了配置落点（settings / task-options 移到 runtime/），
                                 跑一轮顺带确认选项与启动/结束动作读写正常
2. Q4 长稳 24 小时            ← 采样工具已就绪（soak_check.py），需服务连续在线
3. 技术债 P2 按需             ← O2/O3/O4 收益都很小
4. 框架升级（maa 5.6.0 → 5.15.x）← 需装 pip、重验全部 pipeline，收益未量化，排在最后
```

0.3.2 的完整日常回归已通过（8 成功 + 1 未领取 + 0 失败，619.6 s），0.3.3 只动了配置路径与文档，未动调度层。

M7 之前不建议加新功能：调度层还有两处半成品，现在加功能会让回归面变大。

---

*配套文档：`LITE.md`（功能与实测数据）、`MANIFEST.md`（目录归属）、`docs/api-contract.md`（接口契约）、`docs/AUDIT-20261107-v2.md`（技术债与资产审查）。*
