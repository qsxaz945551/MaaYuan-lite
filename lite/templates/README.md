# Lite 自制模板

这里的 PNG 是 Lite 自己维护的模板图，上游 `assets/resource` 里没有或已过期。
运行时它们必须出现在 `assets/resource/base/image/`；`build_release.py` 会在打包时
把它们复制过去，`update_applier.RESOURCE_EXTRAS` 与 `upgrade.py` 的 KEEP 清单
负责在资源更新 / 应用升级后保留。仓库里放一份，是为了重装仓库后能恢复。

| 文件 | 用途 | 更新时机 |
|---|---|---|
| `activity_title.png` | 判页：活动列表页的「活动」标题（不随换期变化） | 页面标题改版时 |
| `lite_event_icon.png` | 主界面右侧「活动」入口图标 | 入口图标改版时 |
| `lite_special_training.png` | 活动卡片「密探」二字，定位密探特训 | **每期换卡面后可能要更新** |

更新方法：`adb exec-out screencap -p` 截图 → 裁对应区域 → 覆盖同名文件 →
`python lite/apply_scope.py` 不需要，直接重新打包即可。
