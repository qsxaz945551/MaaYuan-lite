"""Turn a pipeline node's ``focus`` config into one line of display text.

MaaYuan documents ``focus`` as the per-node progress channel (开发手册
「节点信息输出」), and several shapes are in use in the shipped resource:

* ``"focus": "开始领取密探特训奖励"``  — plain string, the common case
* ``"focus": {"content": "...", "display": ["log", "toast"]}``  — v2.3 object
* ``"focus": {"start": "...", "toast": "..."}``  — legacy keys, text repeated
  (``daily/special_training_reward.json``)
* ``"focus": {"Node.Action.Starting": "..."}``  — one template per message

The console only needs one readable sentence, so the rules are: prefer the
message that fires when the node starts, ignore the display channel, and
substitute ``{name}`` with the node name.
"""

from __future__ import annotations

import json
from typing import Any

# Ordered by "how well does this describe the node starting".  The framework
# templates use these keys; the rest are the legacy display-channel keys.
_PREFERRED_KEYS = (
    "Node.Action.Starting",
    "Node.Recognition.Succeeded",
    "Node.Action.Succeeded",
    "Node.PipelineNode.Starting",
    "Node.NextList.Starting",
    "start",
    "toast",
    "log",
    "content",
    "message",
)

_MESSAGE_PREFIXES = ("Node.", "Tasker.", "Resource.", "Controller.")

# Keys that hold metadata rather than display text.  Without this a
# ``{"display": "toast"}`` value would come back as the word "toast".
_NOT_TEXT_KEYS = {"display", "type", "channel"}


def focus_text(value: Any, node_name: str = "") -> str | None:
    """Best-effort single-line text for a node's ``focus`` value."""
    text = _text_of(value, 0)
    if text is None:
        return None
    if node_name:
        text = text.replace("{name}", node_name)
    # The console renders this on one row, so fold newlines and runs of space.
    text = " ".join(text.split())
    return text or None


def _text_of(value: Any, depth: int) -> str | None:
    if depth > 3:
        return None
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return None
        # Some callbacks deliver the config as an unparsed JSON string.
        if raw.startswith("{") and raw.endswith("}"):
            try:
                return _text_of(json.loads(raw), depth + 1)
            except (ValueError, TypeError):
                return raw
        return raw
    if isinstance(value, (list, tuple)):
        for item in value:
            text = _text_of(item, depth + 1)
            if text:
                return text
        return None
    if isinstance(value, dict):
        if not value:
            return None
        for key in _PREFERRED_KEYS:
            if key in value:
                text = _text_of(value[key], depth + 1)
                if text:
                    return text
        # Remaining message-keyed entries: take one, but never a failure
        # message — "执行失败，请检查环境" would read as the current step.
        for key, item in value.items():
            if not isinstance(key, str) or not key.startswith(_MESSAGE_PREFIXES):
                continue
            if key.endswith(".Failed"):
                continue
            text = _text_of(item, depth + 1)
            if text:
                return text
        for key, item in value.items():
            if key in _NOT_TEXT_KEYS:
                continue
            # Message keys were considered above; only a failure message is
            # left there, which must not become the step text.
            if isinstance(key, str) and key.startswith(_MESSAGE_PREFIXES):
                continue
            text = _text_of(item, depth + 1)
            if text:
                return text
        return None
    return None
