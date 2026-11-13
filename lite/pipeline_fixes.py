"""Runtime corrections for known gaps in the upstream pipeline.

The generated ``interface.json`` and the copied resource files come from
MaaYuan.  Occasionally a branch handles one screen but not the variant the
game actually shows (for example the stamina refill dialog of 6-24).  Patching
the JSON on disk would be overwritten the next time the resource is updated,
so the corrections are merged into each task's ``pipeline_override`` right
before it is posted.  They are applied after the user's option overrides, so
the fix wins over the stock node, while an explicit option can still replace
the surrounding nodes.

Every entry must keep the same node structure MaaFramework expects; we only
replace recognition parameters and next/on_error lists.
"""

from __future__ import annotations

from typing import Any

from .deepmerge import deep_merge


# Text the game shows on the stamina refill dialog.  Upstream only matches
# "体力回复", but the 6-24 dialog says "用道具回复" / "用日金市回复" instead,
# so the check silently misses and the run keeps retrying other nodes.
STAMINA_DIALOG_TEXTS = ["体力回复", "用道具回复", "用日金市回复"]

# 密探特训卡片的标题「密探」二字。上游 `special_training.png` 取自更早的一期，
# 2026-11-13 实测只剩 0.56（阈值 0.72）—— 每期换卡面就会掉线，这是活动的固有节奏，
# 不是 UI 改版。这里换成 Lite 自制的同位置模板（当期二十八期，自匹配 1.000、
# 首屏/主界面/据点页 0.33–0.36），并在 RESOURCE_EXTRAS 里保护，资源更新不会冲掉。
# **每期换卡面后仍需更新这张图**：截图 → 裁「密探」二字（约 88x50）→ 覆盖即可。
SPECIAL_TRAINING_TEMPLATE = "lite_special_training.png"
SPECIAL_TRAINING_ROI = [2, 317, 717, 849]
SPECIAL_TRAINING_THRESHOLD = 0.72

# 主界面右侧「活动」入口图标。上游 `eventicon.png` 是旧版的金色卷轴，
# 2026-11-13 实测在 `找到入口-活动` 的 ROI 里只有 0.5611（阈值 0.6）—— 游戏改版后
# 入口换成了金色礼盒。这张取自当前截图（避开右上角红点，红点领完会消失），
# 主界面 1.000、活动页/据点页 0.43–0.48。
EVENT_ICON_TEMPLATE = "lite_event_icon.png"

# 活动页的「活动」标题是书法体，OCR 从来没读对过（2026-11-06 当日 13 次尝试
# 全灭）。标题本身是静止的背景画，用模板匹配稳定得多。
# 图取自 2026-11-07 10:05 的原生截图，2026-11-13 复测活动页仍是 1.0000 ——
# 这个标题不随活动换期，是判页最稳的锚点。
ACTIVITY_TITLE_TEMPLATE = "activity_title.png"
ACTIVITY_TITLE_ROI = [250, 230, 220, 140]
ACTIVITY_TITLE_THRESHOLD = 0.8

# 补丁自己新增的节点（上游树里没有，也不该有）。门禁据此区分
# 「覆盖上游节点」和「新增节点」——后者要求它存在就等于永远拒绝更新。
NEW_NODES: dict[str, set[str]] = {
    "start_日常鸢报启动": {"等待小道消息收集完成", "end_鸢报四连完成"},
}

FIXES: dict[str, dict[str, Any]] = {
    # 日常收尾：领取密探特训奖励（2026-11-06 实跑失败后定位）
    "日常收尾启动": {
        # 卡片标题换成当期的模板（上游那张已经过期两期了）。
        "进入密探特训页面": {
            "recognition": {
                "param": {
                    "template": SPECIAL_TRAINING_TEMPLATE,
                    "threshold": SPECIAL_TRAINING_THRESHOLD,
                }
            }
        },
        # 主界面活动入口换成当前版本的图标。
        "找到入口-活动": {
            "recognition": {"param": {"template": EVENT_ICON_TEMPLATE}}
        },
        # 判页必须用**页面标题**而不是卡片标题。
        #
        # 2026-11-06 这里被改成了 `special_training.png`（卡片上的「密探」二字），
        # 理由是"卡片在屏上就说明已经在活动页"。但卡片会随活动换期改版，
        # 2026-11-12 掉到 0.55，判页全失败 → `进入界面-活动` 落到末位 DirectHit 的
        # `退出各类popups`，命中 `返回主界面` 把界面退出去，再进再失败 ——
        # 死循环跑了 121 次、790.9 s。
        #
        # 「活动」二字是活动列表页的固定标题，不随换期变化（2026-11-13 复测 1.0000），
        # 而且 `已在界面-活动-向下滑` 一直在用它。判页改回它，卡片在不在首屏都不影响。
        "已在界面-活动": {
            "recognition": {
                "type": "TemplateMatch",
                "param": {
                    "template": ACTIVITY_TITLE_TEMPLATE,
                    "roi": list(ACTIVITY_TITLE_ROI),
                    "threshold": ACTIVITY_TITLE_THRESHOLD,
                },
            }
        },
        # 同一页的「向下滑」分支：只换识别，滑动动作与 post_delay 保持上游原样。
        "已在界面-活动-向下滑": {
            "recognition": {
                "type": "TemplateMatch",
                "param": {
                    "template": ACTIVITY_TITLE_TEMPLATE,
                    "roi": list(ACTIVITY_TITLE_ROI),
                    "threshold": ACTIVITY_TITLE_THRESHOLD,
                },
            }
        },
        # 这里**不能**动 `进入界面-活动` 和 `领取密探特训奖励启动` 的 next。
        #
        # 2026-11-12 死循环时曾把 `进入界面-活动.next` 末位的 `[JumpBack]退出各类popups`
        # 删掉、并把导航项改成不带 JumpBack 的普通项 + `stop`。方向错了：
        # 那个兜底正是"从别的界面退回主界面再点活动入口"的唯一手段，
        # 删掉之后只要当前不在活动页（例如刚做完小道消息），`找到入口-活动` 就
        # 永远找不到——2026-11-13 08:01 实测连续失败 20 次，奖励一次也没领到。
        #
        # 死循环的真正根因是**判页锚点选错了**（用卡片标题判"是否在活动页"）；
        # 判页改回页面标题后，在活动页时必然命中，也就不会落到退出兜底上。
        # 兜底保留原样，导航链路才完整。
        #
        # 附带确认：`max_hit` 限流在 MaaFramework 5.6.0 无效——它只在
        # PipelineParser 里被解析，PipelineTask / Context 没有任何 hit 计数检查，
        # 上游那 50 处 `max_hit: 1` 在这个版本同样不起作用。别再走这条路。
    },
    # 鸢报四连：批量收集要等倒计时（2026-11-06 21:57 实跑失败后定位）
    #
    # 上游 `确定批量收集小道消息` 成功后，只靠 `检测点击_前往收集_小道消息成功`
    # （inverse「前往收集」消失）就结束分支；可此时屏幕上正是
    # 「外出收集中… 批量进度 0/3 倒计时 01:13」——收集才刚开始。
    # 分支结束后 `start_小道消息` 再走一次（max_hit=2），按钮仍是灰的 →
    # `识别不可用的一键收取` → 分支再次结束 → 入口四个分支全部耗尽 →
    # `start_日常鸢报启动` 没有候选节点 → 任务在 153 s 判失败。
    # 注意此时离倒计时结束还有 73 s，任务超时是 1800 s，不是"时间给得太短"，
    # 而是流水线根本没等。
    #
    # 上游其实有等待节点 `小道消息收集中`（OCR「外出收集中」+ post_delay 15 s），
    # 但它只挂在 `loop_小道消息` 上，而 `loop_小道消息` 是个没有任何节点指向的
    # 孤儿。这里把「确认批量收集」接到轮询上，等按钮恢复可点再收取。
    "start_日常鸢报启动": {
        # 确认后先让弹窗收场，避免第一轮判定时界面还在动画里。
        "确定批量收集小道消息": {"next": ["等待小道消息收集完成"]},
        "等待小道消息收集完成": {
            "recognition": {"type": "DirectHit", "param": {}},
            "action": {"type": "DoNothing", "param": {}},
            "pre_delay": 3000,
            "next": [
                # 优先收：按钮恢复可点就说明收集完了。
                "一键收取_小道消息",
                # 还在收集：命中 `小道消息收集中`，它自己 post_delay 15 s，
                # 然后 JumpBack 回到本节点继续轮询（不会消耗入口的 max_hit）。
                "[JumpBack]小道消息收集中",
                # 兜底：按钮灰且不在收集，说明今天的额度已经收完。
                "识别不可用的一键收取",
            ],
        },
        # 四个分支都是 [JumpBack]，全部结束后入口没有候选节点，任务会判失败。
        # 实测（最小流水线）确认：入口末尾补一个 DirectHit 终止节点即可正常
        # succeeded，也顺带解决 11-05 那条"四连跑完但报失败"的隐患。
        "start_日常鸢报启动": {
            "next": [
                "[JumpBack]start_突发情况启动",
                "[JumpBack]start_他的传闻启动",
                "[JumpBack]start_待办公务启动",
                "[JumpBack]start_小道消息",
                "end_鸢报四连完成",
            ]
        },
        # 上游写终止节点用 `stop`（base.json 里的 DirectHit + StopTask），
        # 并在终止节点上挂 `focus` 输出一句中文进度（见 `密探特训奖励提醒`）。
        # 这里保留自有节点而不是直接 `next: ["stop"]`，就是为了这句 focus ——
        # `stop` 没有 focus，日志里只会看到一个英文节点名。
        "end_鸢报四连完成": {
            "recognition": {"type": "DirectHit", "param": {}},
            "action": {"type": "DoNothing", "param": {}},
            "focus": "鸢报四连完成",
            "next": [],
        },
    },
    "start_6-24": {
        # Broaden the text match so the dialog is recognised wherever it is
        # checked.
        "检测体力回复框": {
            "recognition": {
                "type": "OCR",
                "param": {"expected": list(STAMINA_DIALOG_TEXTS)},
            }
        },
        # The dialog appears *after* 郊外 (开始行动) is clicked when stamina
        # just ran out, but upstream only checks right after 进入关卡.
        "开始行动": {"next": ["检测体力回复框", "6-24事件选择"]},
        # Same gap on the fast path (极速版).
        "极速版6-24": {"next": ["检测体力回复框", "6-24-1-前进"]},
        # If the dialog is already up when the event screen is evaluated,
        # stop before falling into the 小铜匣 retry loop.
        "6-24事件选择": {"on_error": ["检测体力回复框", "点击小铜匣"]},
    }
}


def apply_pipeline_fixes(entry: str, override: dict[str, Any]) -> dict[str, Any]:
    """Return ``override`` merged with the fixes registered for ``entry``."""
    fix = FIXES.get(entry)
    if not fix:
        return override
    return deep_merge(override, fix)
