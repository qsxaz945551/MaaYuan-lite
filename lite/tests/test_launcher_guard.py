"""The package launcher carries one tricky invariant, so pin it down here.

cmd.exe parses a .bat by byte offset.  Once the file mixes ``chcp 65001`` with
multi-byte text, that offset drifts and cmd can swallow the leading ``echo`` of
a later line -- the line then runs as if it were a command name.  It is
content-length dependent, so it appears and disappears as unrelated lines are
edited.  Keeping the .NET guard block pure ASCII is what makes it reliable.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "devtools"))

import build_release  # noqa: E402


def guard_block() -> str:
    """From the ``:check_dotnet`` label to the end of the template."""
    lines = build_release.START_BAT.splitlines()
    if ":check_dotnet" not in lines:
        raise AssertionError("start-lite.bat 模板里没有 :check_dotnet 标签")
    return "\n".join(lines[lines.index(":check_dotnet") :])


class LauncherGuardTest(unittest.TestCase):
    def test_guard_runs_before_the_exe_check(self) -> None:
        """Missing runtime must be reported as such, not as a missing exe."""
        text = build_release.START_BAT
        self.assertLess(
            text.index("call :check_dotnet"),
            text.index('if not exist "MaaYuanLite.Desktop.exe"'),
        )

    def test_guard_block_is_pure_ascii(self) -> None:
        block = guard_block()
        offenders = [line for line in block.splitlines() if not line.isascii()]
        self.assertEqual(
            offenders,
            [],
            "守卫块必须保持纯 ASCII，否则 cmd 会按字节偏移错位读串行",
        )

    def test_guard_never_uses_program_files_x86(self) -> None:
        """%ProgramFiles(x86)% injects a ')' that closes the for-set early."""
        risky = [
            line
            for line in guard_block().splitlines()
            if not line.lstrip().lower().startswith("rem")
            and "ProgramFiles(x86)" in line
        ]
        self.assertEqual(risky, [])

    def test_guard_fails_closed(self) -> None:
        """No runtime found => non-zero exit, so nothing downstream runs."""
        block = guard_block()
        self.assertIn("if defined WPF10 exit /b 0", block)
        tail = block[block.index("if defined WPF10 exit /b 0") :]
        self.assertIn("exit /b 1", tail)
        self.assertLess(tail.index("exit /b 1"), len(tail))

    def test_guard_points_at_a_download(self) -> None:
        self.assertIn("dotnet.microsoft.com/download/dotnet/10.0", guard_block())


if __name__ == "__main__":
    unittest.main()
