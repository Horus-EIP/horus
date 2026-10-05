#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from bench_compare import BenchSelection, compare_markdown


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Print the dev plan's section 10 metrics table for one benchmark run, "
        "or the difference between two."
    )
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


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    args = build_parser().parse_args()
    try:
        before, after = chosen_files(args)
        selection = BenchSelection(model=args.model, threads=args.threads, cache_type=args.kv)
        markdown = compare_markdown(before, after, selection)
    except (OSError, ValueError) as exc:
        print(f"[error] {exc}")
        return 2
    print(markdown, end="")
    if args.out:
        Path(args.out).write_text(markdown, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
