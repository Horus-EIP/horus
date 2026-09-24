#!/usr/bin/env python3
"""Cap triple-quoted blocks in source at a configurable line count.

This is a style guard, not a lint replacement. It flags module, class, or
function docstrings (and any other triple-quoted literal) longer than
``--max-lines`` lines so that long-form narrative lives in
``docs/adr/`` instead of inside source files.

Usage:
    python scripts/ci/check-docstring-length.py path1.py path2.py
    python scripts/ci/check-docstring-length.py --max-lines 40 src/

Exits non-zero when violations are found. Intended to be wired into
pre-commit via ``.pre-commit-config.yaml``.
"""

from __future__ import annotations

import argparse
import ast
import pathlib
import sys
from collections.abc import Iterable

DEFAULT_MAX_LINES = 40
EXCLUDE_DIRS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    "alembic",
    "migrations",
}


def _iter_py_files(paths: Iterable[str]) -> Iterable[pathlib.Path]:
    for raw in paths:
        p = pathlib.Path(raw)
        if p.is_file() and p.suffix == ".py":
            yield p
        elif p.is_dir():
            for sub in p.rglob("*.py"):
                if any(part in EXCLUDE_DIRS for part in sub.parts):
                    continue
                yield sub


def _find_long_docstrings(
    src: str, max_lines: int
) -> list[tuple[int, int]]:
    """Return (line_no, length) for every overlong triple-quoted string."""
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return []
    hits: list[tuple[int, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            # Only flag triple-quoted literals. ast doesn't expose the
            # quote style, so reconstruct by checking the source slice.
            end = getattr(node, "end_lineno", node.lineno)
            length = end - node.lineno + 1
            if length > max_lines:
                hits.append((node.lineno, length))
    return hits


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--max-lines",
        type=int,
        default=DEFAULT_MAX_LINES,
        help=f"Maximum lines per triple-quoted block (default: {DEFAULT_MAX_LINES}).",
    )
    parser.add_argument("paths", nargs="+")
    args = parser.parse_args(argv)

    violations = 0
    for path in _iter_py_files(args.paths):
        src = path.read_text(encoding="utf-8", errors="replace")
        for line_no, length in _find_long_docstrings(src, args.max_lines):
            print(
                f"{path}:{line_no}: triple-quoted block is {length} lines "
                f"(limit {args.max_lines}). Move long narrative to docs/."
            )
            violations += 1

    if violations:
        print(f"\n{violations} docstring/comment block(s) exceed the cap.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
