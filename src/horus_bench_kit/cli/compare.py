# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from horus_bench_kit import __version__
from horus_bench_kit.cli.eval import utf8_output
from horus_bench_kit.compare import (
    DEFAULT_PROFILE,
    BenchSelection,
    CompareProfile,
    compare_markdown,
)

DESCRIPTION = (
    "Print a Markdown table of benchmark metrics for one run (a llama-bench file, an evaluation report, "
    "or both), or the difference between two runs."
)


def build_parser(
    prog: str | None = "hbk-compare", description: str = DESCRIPTION, version_option: bool = True
) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=prog, description=description)
    if version_option:
        parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("files", nargs="*", metavar="FILE", help="BEFORE [AFTER]")
    parser.add_argument("--before", nargs="+", metavar="FILE")
    parser.add_argument("--after", nargs="+", metavar="FILE")
    parser.add_argument("--model", help="llama-bench model shown in the metrics table")
    parser.add_argument("--threads", type=int, help="llama-bench thread count shown")
    parser.add_argument("--kv", default="f16", help="llama-bench KV cache type shown")
    parser.add_argument("--out", help="Also write the Markdown to this file")
    return parser


def chosen_files(args: argparse.Namespace) -> tuple[list[str], list[str]]:
    if args.files and (args.before or args.after):
        raise ValueError("give the files either as BEFORE [AFTER] or with --before/--after")
    if args.files:
        if len(args.files) > 2:
            raise ValueError("give one file, or two to compare, or use --before/--after")
        return [args.files[0]], args.files[1:]
    if not args.before:
        raise ValueError("give at least one benchmark file")
    return args.before, args.after or []


def main(
    argv: Sequence[str] | None = None,
    *,
    profile: CompareProfile = DEFAULT_PROFILE,
    prog: str | None = "hbk-compare",
    description: str = DESCRIPTION,
    version_option: bool = True,
) -> int:
    utf8_output()
    args = build_parser(prog, description, version_option).parse_args(argv)
    try:
        before, after = chosen_files(args)
        selection = BenchSelection(model=args.model, threads=args.threads, cache_type=args.kv)
        markdown = compare_markdown(before, after, selection, profile)
    except (OSError, ValueError) as exc:
        print(f"[error] {exc}")
        return 2
    print(markdown, end="")
    if args.out:
        Path(args.out).write_text(markdown, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
