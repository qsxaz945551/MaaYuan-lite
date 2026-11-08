# MaaYuan Lite HTTP 契约

> 版本：0.3.0 / API v2
> 更新：2026-11-07
> 适用对象：WPF 客户端与任何替代前端。网页控制台已退役，线上格式只有 camelCase。

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
| 错误响应 | `{"ok": false, "error": "中文描述", "code": "MACHINE_CODE"}` + 4xx/5xx；`code` 见第七节 |

---

## 二、端点总览

| 方法 | 路径 | 用途 | 稳定性 |
|---|---|---|---|
| GET | `/api/state?since=` | 状态 + 增量日志 | 稳定 |
| GET | `/api/events` | SSE：状态与日志推送 | 新增（v0.2） |
| GET | `/api/plan?training=&dungeon=` | 生成日常计划（不执行） | 稳定 |
| GET | `/api/settings` | 启停动作与上次选择 | 稳定（camelCase） |
| GET | `/api/task-options?scope=` | 任务选项树 | 稳定 |
| GET | `/api/meta` | 版本与 pid | 新增（v0.2） |
| GET | `/api/health` | 环境自检摘要 | 新增（v0.2） |
| GET | `/api/screenshot` | 最近一帧 PNG | 稳定 |
| POST | `/api/start` | 开始日常 | 稳定 |
| POST | `/api/stop` | 停止 | 稳定 |
| POST | `/api/check` | 连接检查 | 稳定 |
| POST | `/api/run-task` | 单独运行任务 | 稳定 |
| POST | `/api/settings` | 保存启停动作 | 稳定（camelCase） |
| POST | `/api/task-options` | 修改选项 | 稳定 |
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
| `timeout` | int\|null | 秒；`null` 表示不设上限（长时间循环任务） |

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

`{startupAction, shutdownAction, lastTraining, lastDungeon, autoUpdateResources}` —— camelCase。
枚举值由客户端维护（`StartupOptions` / `ShutdownOptions`），服务端只按白名单校验。

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

`{version, apiVersion, pid}`。枚举不再下发：客户端本来也不消费，删掉以免和真实状态漂移。

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

所有失败响应统一为：

```json
{"ok": false, "error": "中文描述，可直接展示", "code": "TASK_UNKNOWN"}
```

`error` 是给人看的文本，`code` 是稳定标识，客户端按它分支。

| code | HTTP | 触发 |
|---|---|---|
| `BAD_JSON` | 400 | 请求体不是合法 JSON |
| `BAD_REQUEST` | 400 | 参数缺失或类型不对 |
| `TASK_UNKNOWN` | 400 | `run-task` 的任务名不存在 |
| `PLAN_FAILED` | 400 | 日常计划生成失败（配置损坏） |
| `OPTIONS_FAILED` | 400 | 选项树读取或写回失败 |
| `ROLLBACK_FAILED` | 400 | 没有可回滚的资源备份 |
| `APPLY_FAILED` | 400 | 资源切换在文件系统层失败（已自动回滚） |
| `APPLY_REJECTED` | 400 | 新资源通过门禁但生成不了 interface（已自动回滚） |
| `BUSY` | 409 | 已有运行中的任务，或正在检查连接 |
| `DEV_MANAGED` | 409 | 资源来自 `vendor/`，自动更新只对发布包生效 |
| `NO_SCREENSHOT` | 404 | 还没有截图可供查看 |
| `NOT_FOUND` | 404 | 接口不存在 |

规则：

- 新增错误一律先加 `code`，不新增字符串匹配分支。
- 4xx 表示「客户端可以改请求解决」，5xx 表示「本机环境问题」，目前没有 5xx 出口，环境问题通过 `/api/health` 表达。
- 资源更新失败不抛 5xx：`APPLY_*` 都是 400，且响应里带 `rolledBack` 说明是否已恢复。

---

## 八、命名约定

**线上格式一律 camelCase**，Python 内部仍用 snake_case，转换只在序列化层发生。

现状（2026-11-07，API v2）：

| 端点 | 状态 |
|---|---|
| `/api/state`、`/api/meta`、`/api/health`、`/api/updates` | camelCase |
| `/api/settings` | camelCase（0.3.0 起不再返回 snake_case 副本） |
| `/api/plan`、`/api/task-options` | 字段名本身无下划线，无需转换 |

写入侧仍接受两种拼写（`from_wire`），未知键原样透传，方便脚本调用。
