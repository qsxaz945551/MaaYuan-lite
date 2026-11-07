"""Deep merge shared by scoping and option overrides.

The two callers used to have their own copy; one shared nested objects with the
input, the other deep-copied them. These cases pin the semantics both rely on.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from lite.deepmerge import deep_merge


class MergeSemanticsTest(unittest.TestCase):
    def test_nested_dict_merges(self) -> None:
        base = {"a": {"x": 1, "y": 2}}
        patch = {"a": {"y": 3, "z": 4}}
        self.assertEqual(deep_merge(base, patch), {"a": {"x": 1, "y": 3, "z": 4}})

    def test_list_is_replaced_not_concatenated(self) -> None:
        # Pipeline steps must be replaced wholesale; appending would run twice.
        base = {"next": ["a", "b"]}
        patch = {"next": ["c"]}
        self.assertEqual(deep_merge(base, patch), {"next": ["c"]})

    def test_missing_keys_survive(self) -> None:
        self.assertEqual(deep_merge({"a": 1, "b": 2}, {"b": 3}), {"a": 1, "b": 3})

    def test_none_overrides(self) -> None:
        self.assertEqual(deep_merge({"a": 1}, {"a": None}), {"a": None})

    def test_deep_copy_mode_does_not_share(self) -> None:
        base = {"a": {"x": 1}}
        merged = deep_merge(base, {"b": 2}, copy_values=True)
        merged["a"]["x"] = 99
        self.assertEqual(base["a"]["x"], 1, "base must not be mutated")

    def test_shallow_mode_shares_nested(self) -> None:
        # apply_scope relies on this: the result is written out immediately.
        base = {"a": {"x": 1}}
        merged = deep_merge(base, {"b": 2}, copy_values=False)
        self.assertIs(merged["a"], base["a"])

    def test_patch_nested_dict_is_copied_in_copy_mode(self) -> None:
        patch = {"a": {"x": 1}}
        merged = deep_merge({}, patch, copy_values=True)
        merged["a"]["x"] = 99
        self.assertEqual(patch["a"]["x"], 1)

    def test_empty_patch_returns_equivalent(self) -> None:
        self.assertEqual(deep_merge({"a": 1}, {}), {"a": 1})

    def test_dict_replaces_scalar(self) -> None:
        self.assertEqual(deep_merge({"a": 1}, {"a": {"b": 2}}), {"a": {"b": 2}})

    def test_scalar_replaces_dict(self) -> None:
        self.assertEqual(deep_merge({"a": {"b": 2}}, {"a": 1}), {"a": 1})


class CopyModeTest(unittest.TestCase):
    """The two call-site modes are now explicit at the call site."""

    def test_shallow_mode_shares_nested_objects(self) -> None:
        # apply_scope 立刻把结果写出去，不需要为省一次拷贝而 deepcopy。
        base = {"a": {"x": 1}}
        self.assertIs(deep_merge(base, {}, copy_values=False)["a"], base["a"])

    def test_default_mode_copies_nested_objects(self) -> None:
        base = {"a": {"x": 1}}
        merged = deep_merge(base, {})
        merged["a"]["x"] = 99
        self.assertEqual(base["a"]["x"], 1)

    def test_apply_scope_runs_as_script(self) -> None:
        """app.py 用 subprocess 调它，相对导入会直接让启动时重建 interface 失败。"""
        import subprocess
        import sys

        root = Path(__file__).resolve().parents[2]
        result = subprocess.run(
            [sys.executable, str(root / "lite" / "apply_scope.py"), "--help"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("scope", result.stdout.lower())


if __name__ == "__main__":
    unittest.main()
