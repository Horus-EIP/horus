#!/usr/bin/env python3

from __future__ import annotations

import argparse
import os
import sys
import xml.etree.ElementTree as ET
from collections.abc import Sequence
from pathlib import Path

HEADER = "| Suite | Lines | Lines and branches | Tests |\n|---|---:|---:|---|"
NO_REPORT = "no report"
NOTHING_ARRIVED = "nothing arrived"


def coverage_figures(coverage_xml: Path) -> tuple[str, str]:
    try:
        totals = ET.parse(coverage_xml).getroot().attrib
    except (OSError, ET.ParseError):
        return NO_REPORT, NO_REPORT
    return line_rate(totals), gate_total(totals)


def line_rate(totals: dict[str, str]) -> str:
    try:
        return f"{float(totals['line-rate']) * 100:.1f} %"
    except (KeyError, ValueError):
        return NO_REPORT


def gate_total(totals: dict[str, str]) -> str:
    try:
        valid = int(totals["lines-valid"]) + int(totals["branches-valid"])
        covered = int(totals["lines-covered"]) + int(totals["branches-covered"])
    except (KeyError, ValueError):
        return NO_REPORT
    return f"{100.0 * covered / valid if valid else 100.0:.2f} %"


def test_counts(junit_xml: Path) -> str:
    try:
        root = ET.parse(junit_xml).getroot()
    except (OSError, ET.ParseError):
        return NO_REPORT
    counts = {"passed": 0, "failed": 0, "skipped": 0}
    for case in root.iter("testcase"):
        counts[outcome(case)] += 1
    return f"{counts['passed']} passed, {counts['failed']} failed, {counts['skipped']} skipped"


def outcome(case: ET.Element) -> str:
    if case.find("failure") is not None or case.find("error") is not None:
        return "failed"
    return "skipped" if case.find("skipped") is not None else "passed"


def suite_row(suite: str, coverage_xml: Path, junit_xml: Path) -> str:
    lines, lines_and_branches = coverage_figures(coverage_xml)
    return f"| {suite} | {lines} | {lines_and_branches} | {test_counts(junit_xml)} |"


def collected_table(rows: dict[str, str]) -> str:
    lines = ["## Coverage", "", HEADER]
    for suite, row in rows.items():
        lines.append(
            row.strip()
            or f"| {suite} | {NOTHING_ARRIVED} | {NOTHING_ARRIVED} | {NOTHING_ARRIVED} |"
        )
    if not any(row.strip() for row in rows.values()):
        lines += ["", "No test job sent its coverage line."]
    return "\n".join(lines)


def append(env_name: str, text: str) -> None:
    target = os.environ.get(env_name)
    if target:
        with open(target, "a", encoding="utf-8") as handle:
            handle.write(text + "\n")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Write a test job's coverage and test counts to its summary, or collect them."
    )
    commands = parser.add_subparsers(dest="command", required=True)
    line = commands.add_parser("line", help="one suite: its coverage XML and junit XML")
    line.add_argument("suite")
    line.add_argument("coverage_xml", type=Path)
    line.add_argument("junit_xml", type=Path)
    collect = commands.add_parser("collect", help="the rows the test jobs sent, as SUITE=ROW")
    collect.add_argument("rows", nargs="*")
    args = parser.parse_args(argv)

    if args.command == "line":
        row = suite_row(args.suite, args.coverage_xml, args.junit_xml)
        append("GITHUB_STEP_SUMMARY", f"{HEADER}\n{row}")
        append("GITHUB_OUTPUT", f"row={row}")
        print(row)
        return 0

    rows = dict(item.partition("=")[::2] for item in args.rows)
    table = collected_table(rows)
    append("GITHUB_STEP_SUMMARY", table)
    print(table)
    return 0


if __name__ == "__main__":
    sys.exit(main())
