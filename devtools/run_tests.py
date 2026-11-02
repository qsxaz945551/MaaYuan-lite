"""Run the Lite test suite with an explicit sys.path.

The bundled embeddable Python ignores PYTHONPATH and does not put the current
directory on sys.path, so ``python -m unittest discover`` fails with
``No module named 'lite'``. This entry point fixes the path once and works the
same on the bundled runtime and on a system Python.

Usage:
    python devtools/run_tests.py
    python devtools/run_tests.py -q
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    verbosity = 1 if "-q" in sys.argv else 2
    suite = unittest.TestLoader().discover(
        str(ROOT / "lite" / "tests"),
        top_level_dir=str(ROOT),
    )
    result = unittest.TextTestRunner(verbosity=verbosity).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
