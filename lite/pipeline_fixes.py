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

from .task_overrides import merge_pipeline

# Text the game shows on the stamina refill dialog.  Upstream only matches
# "体力回复", but the 6-24 dialog says "用道具回复" / "用日金市回复" instead,
# so the check silently misses and the run keeps retrying other nodes.
STAMINA_DIALOG_TEXTS = ["体力回复", "用道具回复", "用日金市回复"]

FIXES: dict[str, dict[str, Any]] = {
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
    return merge_pipeline(override, fix)
