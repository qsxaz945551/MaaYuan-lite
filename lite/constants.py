"""Values that were previously copy-pasted across modules.

Keeping them here makes drift visible: the training names appear in the
scheduler, the settings defaults, the CLI parser and the HTTP defaults, and a
typo in one of them used to mean "the UI shows 修为 but the run starts 铜钱".
"""

from __future__ import annotations

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765

# Short names used on the wire and in settings. The daily profile maps them to
# the prefixed task names (💎 修为历练 / 💲 铜钱历练 / ⚔️ 经验历练).
TRAINING_TYPES = ("修为", "铜钱", "经验")
DEFAULT_TRAINING = TRAINING_TYPES[0]
