"""Static scan of the Lite backend: sizes, long functions, unused imports."""

from __future__ import annotations

import ast
import io
import tokenize
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "lite"
TARGETS = sorted(ROOT.glob("*.py")) + [ROOT.parent / "app.py"]


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def unused_imports(path: Path) -> list[str]:
    source = read(path)
    tree = ast.parse(source)
    imported: dict[str, int] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.asname or alias.name.split(".")[0]
                imported[name] = node.lineno
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name == "*":
                    continue
                imported[alias.asname or alias.name] = node.lineno

    used: set[str] = set()
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type == tokenize.NAME:
            used.add(token.string)
    # attribute access like module.attr keeps the module name in NAME tokens
    return [
        f"{name} (line {line})"
        for name, line in imported.items()
        if name not in used
    ]


def long_functions(path: Path) -> list[tuple[str, int, int]]:
    tree = ast.parse(read(path))
    rows = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            span = (node.end_lineno or node.lineno) - node.lineno + 1
            rows.append((node.name, node.lineno, span))
    rows.sort(key=lambda item: -item[2])
    return rows[:5]


def counters(path: Path) -> dict[str, int]:
    text = read(path)
    return {
        "lines": text.count("\n") + 1,
        "bare_except": text.count("except Exception"),
        "todo": text.count("TODO") + text.count("FIXME"),
    }


def main() -> None:
    print(f"{'file':38} {'lines':>6} {'funcs':>6} {'except':>7}")
    total = 0
    for path in TARGETS:
        tree = ast.parse(read(path))
        funcs = sum(
            1
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        )
        stats = counters(path)
        total += stats["lines"]
        print(
            f"{path.name:38} {stats['lines']:6} {funcs:6} {stats['bare_except']:7}"
        )
    print(f"{'TOTAL':38} {total:6}")

    print("\n=== 最长函数（行数） ===")
    for path in TARGETS:
        rows = long_functions(path)
        if not rows:
            continue
        top = ", ".join(f"{name}:{span}" for name, _line, span in rows[:3])
        print(f"{path.name:30} {top}")

    print("\n=== 未使用的导入 ===")
    found = False
    for path in TARGETS:
        items = unused_imports(path)
        if items:
            found = True
            print(f"{path.name}: {', '.join(items)}")
    if not found:
        print("(none)")


if __name__ == "__main__":
    main()
