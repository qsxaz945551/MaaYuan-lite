# 第三方组件与许可

MaaYuan Lite 基于以下项目构建，发布包保留其许可与版权声明。

| 组件 | 版本 | 许可 | 用途 |
|---|---|---|---|
| MaaYuan（syoius/MaaYuan） | v5 @ c119472 | MIT | 任务流水线、资源、Python Agent |
| MaaFramework（MaaXYZ/MaaFramework） | 5.6.0 | LGPL-3.0 | 设备控制、识别、任务调度 |
| MaaAgentBinary | 1.0.1 | 随 MaaFramework | minicap / minitouch / maatouch |
| CPython | 3.12.10 | PSF-2.0 | 运行时 |
| opencv-python | 4.x | Apache-2.0 | Agent 图像处理 |
| numpy | 2.x | BSD-3-Clause | 数值计算 |
| Pillow | 13.x | HPND | 截图编码 |
| loguru | 0.7.3 | MIT | 日志 |
| zhconv | 1.x | MIT | 简繁转换 |
| jsonschema | 4.x | MIT | 配置校验 |
| openpyxl | 3.x | MIT | Excel 读取 |

## 说明

- `assets/resource/` 与 `agent/` 来自上游 MaaYuan 仓库，未做修改；Lite 仅在运行时通过
  `pipeline_override` 打补丁，不改磁盘上的上游文件。
- OCR 模型来自 `MaaXYZ/MaaCommonAssets`（`ppocr_v6/small`、`ppocr_v5/zh_cn`、`ppocr_v4/en_us`），
  未做量化或替换。
- MaaFramework 的原生库随 `maafw` wheel 分发。
- 本项目自身代码同样以 MIT 许可发布。

完整许可文本见上游仓库：

- https://github.com/syoius/MaaYuan/blob/v5/LICENSE
- https://github.com/MaaXYZ/MaaFramework/blob/main/LICENSE
