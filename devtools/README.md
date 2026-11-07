# devtools 索引

开发期脚本，**不进发布包**。按用途分三组，入口仍然是根目录的 `run_tests.py`。

## release/ —— 打包、切换、同步资源

| 脚本 | 用途 |
|---|---|
| `build_release.py` | 打包到 `dist/MaaYuan-Lite-<version>/`（`--zip` 额外产 zip） |
| `release_switch.py` | `list` / `switch <版本\|previous>` / `prune --keep N` |
| `verify_chain.py` | 用 active 发布包跑一整轮日常并记录结果（8–13 分钟，会点击游戏） |
| `sync_repo.py` | 克隆/更新上游到 `vendor/MaaYuan-src`（`--update` / `--check`） |
| `upgrade.py` | 用上游资源升级当前 `assets/`（`--apply` 才落盘） |

## smoke/ —— 连真机/真包的冒烟

| 脚本 | 用途 |
|---|---|
| `smoke_release.py` | 对已打包目录做 version/health（`--skip-game` 跳过连机） |
| `smoke_ui_note.py` | 验证 `/api/note` 写入运行日志 |
| `smoke_daily.py` | 触发一轮日常并观察 |
| `smoke_update.py` | 走一遍下载/校验/门禁 |
| `smoke_recover.py` | 未知界面恢复原语（只按键，不点游戏） |
| `soak_check.py` | 长时间轮询内存/句柄 |
| `stability_run.py` | 稳定性跑测，记录进程树指标 |
| `inject_fault.py` | 故障注入（**含 emulator/network，仅用户手动执行**） |
| `smoke_emulator_restart.py` | 重启模拟器场景（**仅用户手动执行**） |

## probe/ —— 只读取证

| 脚本 | 用途 |
|---|---|
| `capture_run.py` | 采样进程树指标到 CSV |
| `proc_tree.py` | 打印进程树（命令行单次） |
| `measure_tree.py` | 测量进程树内存/句柄 |
| `summarize_run.py` | 汇总 MaaYuan 日志里的任务耗时 |
| `check_upstream.py` | 校验资源完整性 / 任务名 / 补丁依赖节点 |
| `audit_scan.py` | 静态扫描（死代码、导入） |
| `audit_runtime.py` | 运行时依赖体积审计 |

## 约束

- `smoke/inject_fault.py` 与 `smoke/smoke_emulator_restart.py` 会改模拟器状态，AI 不得执行（见 `AGENTS.md` R1–R4）。
- 三个测试通过 `sys.path` 直接 import `release/` 下的脚本，移动文件时必须同步改：
  `test_launcher_guard.py`、`test_release_switch.py`、`test_upgrade_keep.py`。
