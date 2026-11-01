"""Runtime guards for the Lite runner (stage 1 stability work)."""

from __future__ import annotations

import threading

# A task is assumed to be stuck when the same pipeline node starts this many
# times.  Normal tasks stay far below it (the busiest daily node is a few
# dozen repeats); an on_error/next loop reaches it within a couple of minutes.
NODE_REPEAT_BUDGET = 120


class NodeRepeatGuard:
    """Counts node executions inside one task and trips once a node loops."""

    def __init__(self, budget: int = NODE_REPEAT_BUDGET) -> None:
        self.budget = budget
        self._counts: dict[str, int] = {}
        self._tripped = ""
        self._lock = threading.Lock()

    def hit(self, name: str) -> bool:
        """Record one start; returns True only on the first over-budget hit."""
        with self._lock:
            if self._tripped:
                return False
            count = self._counts.get(name, 0) + 1
            self._counts[name] = count
            if count > self.budget:
                self._tripped = name
                return True
            return False

    @property
    def tripped_node(self) -> str:
        return self._tripped
