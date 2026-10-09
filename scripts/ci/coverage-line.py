#!/usr/bin/env python3

from __future__ import annotations

import argparse
import os
import sys
import xml.etree.ElementTree as ET
from collections.abc import Sequence
from pathlib import Path

HEADER = "| Suite | Lines covered | Tests |\n|---|---:|---|"
NO_REPORT = "no report"


def line_rate(coverage_xml: Path) -> str:
    try:
        root = ET.parse(coverage_xml).getroot()
        return f"{float(root.attrib['line-rate']) * 100:.1f} %"
    except (OSError, ET.ParseError, KeyError, ValueError):
        return NO_REPORT


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
    return f"| {suite} | {line_rate(coverage_xml)} | {test_counts(junit_xml)} |"


def collected_table(rows: dict[str, str]) -> str:
    lines = ["## Coverage", "", HEADER]
    for suite, row in rows.items():
        lines.append(row.strip() or f"| {suite} | nothing arrived | nothing arrived |")
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
