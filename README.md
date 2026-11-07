# MaaYuan Lite

MaaYuan（如鸢）日常自动化的精简本地客户端：WPF 界面 + 自包含 Python 运行时，解压即用。

## 使用

双击 `start-lite.bat`（发布包内同名文件）。窗口关闭时后端服务一并退出。

- **唯一外部依赖**：.NET 10 Desktop Runtime。启动脚本会检测，缺失时打印下载地址。
- 首次使用先点「检查连接」：只连接、截图，不点击游戏、不执行任务。
- 左栏勾选今天要做的任务（「今日日常」有两个 Tab），右上角「开始任务（N）」执行勾选项。

## 开发

```bash
python devtools/run_tests.py              # 295 项单元测试
python devtools/sync_repo.py --update     # 同步上游 pipeline 到 vendor/MaaYuan-src
python devtools/build_release.py          # 打包到 dist/MaaYuan-Lite-<版本>
python devtools/release_switch.py switch <版本>   # 切换 active
python devtools/smoke_release.py          # 对打包产物做 version/health 自检
python devtools/verify_chain.py           # 用发布包跑一整轮日常（8–13 分钟）
dotnet build desktop/MaaYuanLite.Desktop  # 编译 WPF 客户端
```

## 文档

| 文件 | 内容 |
|---|---|
| `LITE.md` | 使用说明、界面、任务口径、更新策略 |
| `PROJECT-REPORT.md` | 实现记录、验收数据、决策表 |
| `MANIFEST.md` | 目录归属边界（自研 / 上游 / 生成） |
| `docs/api-contract.md` | HTTP 契约与错误码 |
| `docs/DEEPSEEK-HANDOFF.md` | 环境事实与模拟器硬规则 |
| `docs/AUDIT-20261107-v2.md` | 技术债与资产审查（含本次清理记录） |

上游：[syoius/MaaYuan](https://github.com/syoius/MaaYuan)（分支 `v5`）。本项目只保留日常链所需的任务与选项，资源随上游更新。
