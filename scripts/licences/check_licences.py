#!/usr/bin/env python3

from __future__ import annotations

import argparse
import fnmatch
import re
import sys
from pathlib import Path

import third_party_notices as notices

ALLOWLIST = Path(__file__).resolve().parent / "allowlist.yaml"
STRONG = "strong"
WEAK = "weak"
FREE = "free"
RANK = {FREE: 0, WEAK: 1, STRONG: 2}
WEAK_TERMS = re.compile(r"LGPL|Lesser General Public|Library General Public", re.IGNORECASE)
STRONG_TERMS = re.compile(r"\bA?GPL|General Public License|SSPL|Server Side Public", re.IGNORECASE)
ALTERNATIVES = re.compile(r"\s+OR\s+|\s*/\s*", re.IGNORECASE)
TERMS = re.compile(r"\s+AND\s+", re.IGNORECASE)


def term_kind(term: str) -> str:
    if WEAK_TERMS.search(term):
        return WEAK
    if STRONG_TERMS.search(term):
        return STRONG
    return FREE


def licence_kind(licence: str) -> str:
    flat = licence.replace("(", " ").replace(")", " ").strip()
    choices = []
    for alternative in ALTERNATIVES.split(flat):
        kinds = [term_kind(term) for term in TERMS.split(alternative) if term.strip()]
        choices.append(max(kinds, key=RANK.get) if kinds else FREE)
    return min(choices, key=RANK.get) if choices else FREE


def own_process_entries(report: notices.Report) -> list[tuple[str, notices.Entry]]:
    found = []
    for entries in notices.python_entries(report).values():
        found += [("python", entry) for entry in entries]
    found += [("web", entry) for entry in notices.web_entries()]
    found += [("rust", entry) for entry in notices.rust_entries(report)]
    return found


def read_allowlist(path: Path) -> dict[tuple[str, str], str]:
    data = notices.read_yaml(path) if path.is_file() else {}
    allowed = {}
    for item in data.get("allow") or []:
        if not str(item.get("reason", "")).strip():
            raise SystemExit(
                f"{path.name}: {item.get('ecosystem')} {item.get('name')} has no reason"
            )
        allowed[(item["ecosystem"], notices.normalise(item["name"]))] = item["reason"]
    return allowed


def allowed_by(
    allowed: dict[tuple[str, str], str], ecosystem: str, name: str
) -> tuple[str, str] | None:
    for key in allowed:
        if key[0] == ecosystem and fnmatch.fnmatchcase(notices.normalise(name), key[1]):
            return key
    return None


def check(allowlist: Path) -> int:
    report = notices.Report()
    allowed = read_allowlist(allowlist)
    used = set()
    failures, warnings = [], []
    for ecosystem, entry in own_process_entries(report):
        kind = licence_kind(entry.licence)
        if kind == FREE:
            continue
        key = allowed_by(allowed, ecosystem, entry.name)
        label = f"{ecosystem}: {entry.name} {entry.version} ({entry.licence})"
        if key is not None:
            used.add(key)
            print(f"allowed  {label}: {allowed[key]}")
        elif kind == STRONG:
            failures.append(label)
        else:
            warnings.append(label)
    for label in sorted(set(warnings)):
        print(
            f"warning  {label}: weak copyleft, keep it unmodified and listed in THIRD_PARTY_NOTICES"
        )
    for label in sorted(set(failures)):
        print(f"error    {label}: GPL, AGPL or SSPL inside a Horus process")
    for ecosystem, name in sorted(set(allowed) - used):
        print(
            f"error    {allowlist.name}: {ecosystem} {name} is allowed but no longer used; remove it"
        )
    for problem in report.stale:
        print(f"error    {problem}")
    stale = len(set(allowed) - used) + len(report.stale)
    print(f"{len(set(failures))} copyleft, {len(set(warnings))} weak copyleft, {len(used)} allowed")
    return 1 if failures or stale else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Fail on GPL, AGPL or SSPL among the Python packages, the web client's production "
        "dependencies and the desktop app's Rust crates. LGPL is a warning. Images and "
        "models run as separate processes and are not checked."
    )
    parser.add_argument("--allowlist", type=Path, default=ALLOWLIST)
    args = parser.parse_args(argv)
    return check(args.allowlist)


if __name__ == "__main__":
    sys.exit(main())
