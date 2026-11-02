# MaaYuan Lite HTTP 契约

> 版本：0.2.0 / API v1
> 更新：2026-11-02
> 适用对象：WPF 客户端、任何替代前端。HTML 控制台仍在用旧字段，见第八节迁移计划。

服务只监听 `127.0.0.1`，默认端口 8765；端口被占用时回退随机端口，实际端口写在 `runtime/port.txt`。
所有请求与响应均为 UTF-8 JSON（`/api/events` 除外）。

---

## 一、通用约定

| 项 | 约定 |
|---|---|
| 基础地址 | `http://127.0.0.1:<port>` |
| 端口发现 | 读 `runtime/port.txt`；文件不存在说明服务未启动 |
| 认证 | 无（仅本机回环） |
| 时间格式 | 本地时间字符串 `YYYY-MM-DD HH:MM:SS`，空字符串表示未发生 |
| 日志游标 | 单调递增整数 `logSeq`，跨请求有效，进程重启后归零 |
| 错误响应 | `{"error": "中文描述"}` + 4xx/5xx；错误码见第七节（待迁移） |

---

## 二、端点总览

| 方法 | 路径 | 用途 | 稳定性 |
|---|---|---|---|
| GET | `/` | HTML 控制台（WPF 上线后移除） | 临时 |
| GET | `/api/state?since=` | 状态 + 增量日志 | 稳定 |
| GET | `/api/events` | SSE：状态与日志推送 | 新增（v0.2） |
| GET | `/api/plan?training=&dungeon=` | 生成日常计划（不执行） | 稳定 |
| GET | `/api/settings` | 启停动作与上次选择 | 字段待改名 |
| GET | `/api/task-options?scope=` | 任务选项树 | 字段待改名 |
| GET | `/api/meta` | 版本与枚举 | 新增（v0.2） |
| GET | `/api/health` | 环境自检摘要 | 新增（v0.2） |
| GET | `/api/screenshot` | 最近一帧 PNG | 稳定 |
| POST | `/api/start` | 开始日常 | 稳定 |
| POST | `/api/stop` | 停止 | 稳定 |
| POST | `/api/check` | 连接检查 | 稳定 |
| POST | `/api/run-task` | 单独运行任务 | 稳定 |
| POST | `/api/settings` | 保存启停动作 | 字段待改名 |
| POST | `/api/task-options` | 修改选项 | 字段待改名 |
| POST | `/api/exit` | 退出服务 | 稳定 |

---

## 三、`GET /api/state`

查询参数 `since`：整数游标，或 `latest`（只取当前游标、不回填历史）。

| 字段 | 类型 | 可空 | 说明 |
|---|---|---|---|
| `status` | string | 否 | 运行状态，枚举见第六节 |
| `currentTask` | string | 是（空串） | 正在执行的任务名 |
| `tasks` | array | 否 | 本次计划的任务，见下 |
| `summary` | object | 否 | `{succeeded:int, failed:int}`，未运行时为 `{}` |
| `startedAt` / `finishedAt` | string | 是（空串） | 本次运行起止时间 |
| `logs` | array | 否 | 增量日志 `{seq,time,level,message}` |
| `logSeq` | int | 否 | 当前游标 |
| `runId` | int | 否 | 进程启动时生成，变化表示服务重启过 |
| `single` | object\|null | 是 | 单独/批量任务进度 |
| `busy` | bool | 否 | 是否有运行线程 |
| `canResume` | bool | 否 | 是否存在可补跑的任务 |
| `config` | object | 否 | `{adbSerial, resource}`，只读摘要 |

`tasks[]` 字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `name` | string | 显示名（含 emoji），**不要用作主键** |
| `kind` | string | `daily` / `single` / `optional` |
| `status` | string | 枚举见第六节 |
| `duration` | float | 秒 |
| `attempts` | int | 尝试次数 |
| `timeout` | int\|null | 秒；`null` 表示无上限（邺城） |

客户端合并规则：`runId` 变化 → 清空本地状态；`logSeq` 小于本地 → 重新全量拉取。

---

## 四、`GET /api/events`（SSE）

`Content-Type: text/event-stream`。连接建立后立即收到一条，之后每秒一条；15 秒无数据时发注释行 `: ping`。

```
event: state
data: {"status":"running","currentTask":"🏯 据点日常","summary":{},"logSeq":128,"logs":[...]}
```

| 字段 | 说明 |
|---|---|
| `status` / `currentTask` / `summary` | 同 `/api/state` |
| `logSeq` | 本批日志后的游标 |
| `logs` | 新增日志，可能为空数组 |

设计取舍：`tasks` 不进 SSE（数组大、变化少），客户端收到 `status` 变化时再拉一次 `/api/state`。
断线重连由客户端负责，服务端不保存会话；重连时用最后一次 `logSeq` 作为 `since` 补齐。

---

## 五、其余 GET

### `GET /api/plan`

| 参数 | 类型 | 默认 | 说明 |
|---|---|---|---|
| `training` | string | `修为` | `修为` / `铜钱` / `经验` |
| `dungeon` | `0`/`1` | 配置值 | 是否插入地宫助手 |

返回：`{tasks:[{name,kind}], skipped:[{name,reason}], count:int}`。
`skipped.reason` 目前是内部标识（如 `seasonal_daily_disabled`），客户端应原样展示或按映射表翻译。

### `GET /api/settings`

`{startup_action, shutdown_action, last_training, last_dungeon}` —— **snake_case，待迁移**。
枚举值见 `/api/meta` 的 `startupActions` / `shutdownActions`。

### `GET /api/task-options?scope=daily|all`

`{scope, tasks[], hidden[], pinned[]}`。`tasks[]`：

| 字段 | 类型 | 说明 |
|---|---|---|
| `name` | string | 任务显示名 |
| `entry` | string | pipeline 入口，稳定主键 |
| `groups` | array | 选项组 |
| `groups[].group` | string | 组名 |
| `groups[].type` | string | `select` / `switch` / `input` |
| `groups[].depth` | int | 嵌套层级（0 为顶层） |
| `groups[].cases` | string[] | 可选项 |
| `groups[].selected` | int | 当前选中的索引 |
| `groups[].description` | string | 说明，可为空 |

写入用 `POST /api/task-options`，body：`{task, group, index}` 或 `{task, group, inputs:{...}}`。

### `GET /api/meta`

`{version, apiVersion, runStates[], taskStates[], startupActions[], shutdownActions[], trainingTypes[]}`。
客户端不应硬编码枚举，启动时读一次缓存。

### `GET /api/health`

`{ok:bool, failed:int, warned:int, checks:[{name,status,detail}]}`，`status` 为 `ok`/`warn`/`fail`。
结果缓存 30 秒；`?refresh=1` 强制重跑。首次调用约 1–3 秒（含 adb 探测）。

---

## 六、枚举

**运行状态** `status`：

| 值 | 含义 | 终态 |
|---|---|---|
| `idle` | 未运行 | 是 |
| `starting` | 已受理，准备中 | 否 |
| `running` | 执行中 | 否 |
| `checking` | 连接检查中 | 否 |
| `completed` | 全部成功 | 是 |
| `completed_with_errors` | 有失败但已跑完 | 是 |
| `cancelled` | 用户停止 | 是 |
| `error` | 不可继续的错误（Agent 重启失败等） | 是 |
| `interrupted` | 上次进程留下的未完成快照 | 是 |

**任务状态** `tasks[].status`：`pending` / `running` / `succeeded` / `failed` / `timed_out` / `skipped` / `cancelled`。

---

## 七、错误

当前所有失败统一返回 `{"error": "中文句子"}`，HTTP 400 或 409。客户端只能按状态码分支。

计划迁移（未实施）：`{"code": "TASK_UNKNOWN", "message": "..."}`，`code` 为稳定标识：

| code | HTTP | 触发 |
|---|---|---|
| `BAD_JSON` | 400 | 请求体不是 JSON |
| `TASK_UNKNOWN` | 400 | `run-task` 的任务名不存在 |
| `GROUP_UNKNOWN` | 400 | 选项组不属于该任务 |
| `INDEX_OUT_OF_RANGE` | 400 | 选项索引越界 |
| `BUSY` | 409 | 已有运行中的任务 |
| `NO_PLAN` | 400 | 续跑时没有可补跑项 |

---

## 八、命名迁移计划

现状：`/api/state`、`/api/meta`、`/api/health` 已是 camelCase；`/api/settings`、`/api/plan`、`/api/task-options` 仍混用 snake_case。

不一次性切换的原因：HTML 控制台有 900 多行 JS 直接读这些字段，一次性改会同时动后端、前端和测试，且没有自动化前端测试兜底。

迁移分三步：

1. **双写**（WPF 开工前）：后端响应同时带 `startup_action` 与 `startupAction`，旧字段标 `deprecated`。
2. **切换**：WPF 只用 camelCase；HTML 控制台改读新字段（或随 WPF 上线一起下线）。
3. **清理**：删除旧字段，`apiVersion` 升到 2。

在此之前，新增字段一律用 camelCase，不再增加 snake_case。
