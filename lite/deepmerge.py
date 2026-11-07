"""One deep-merge used by both the scoping step and the option overrides.

The two call sites used to be separate copies that had drifted: one shared
nested objects with its input, the other deep-copied them. Sharing meant an
override could mutate the loaded interface by accident; copying is the safer
default but wasteful when the caller immediately serialises the result.
``copy_values`` keeps both behaviours on one implementation.
"""

from __future__ import annotations

import copy
from typing import Any


def deep_merge(
    base: dict[str, Any], patch: dict[str, Any], *, copy_values: bool = True
) -> dict[str, Any]:
    """Merge ``patch`` into ``base`` recursively.

    - dict + dict → recurse
    - anything else in ``patch`` replaces the value in ``base`` (lists included;
      pipeline steps are replaced, never concatenated)
    - keys missing from ``patch`` are kept

    ``copy_values`` controls whether the inputs' nested objects are copied.
    Leave it on unless the result is written out immediately and never mutated.
    """
    result = copy.deepcopy(base) if copy_values else dict(base)
    for key, value in patch.items():
        existing = result.get(key)
        if isinstance(value, dict) and isinstance(existing, dict):
            result[key] = deep_merge(existing, value, copy_values=copy_values)
        elif copy_values:
            result[key] = copy.deepcopy(value)
        else:
            result[key] = value
    return result
