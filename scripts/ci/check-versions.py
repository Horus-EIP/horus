#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from collections.abc import Callable
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
RELEASE = re.compile(r"\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?")

Reader = Callable[[str], str]


def json_field(*keys: str) -> Reader:
    def read(text: str) -> str:
        node = json.loads(text)
        for key in keys:
            node = node[key]
        return node

    return read


def cargo_package(text: str) -> str:
    return tomllib.loads(text)["package"]["version"]


def cargo_lock_entry(name: str) -> Reader:
    def read(text: str) -> str:
        for entry in tomllib.loads(text).get("package", []):
            if entry.get("name") == name:
                return entry["version"]
        raise KeyError(name)

    return read


def env_assignment(key: str) -> Reader:
    def read(text: str) -> str:
        for line in text.splitlines():
            name, sep, value = line.strip().partition("=")
            if sep and name == key:
                return value.strip()
        raise KeyError(key)

    return read


def first_match(pattern: str) -> Reader:
    compiled = re.compile(pattern, re.MULTILINE)

    def read(text: str) -> str:
        match = compiled.search(text)
        if match is None:
            raise KeyError(pattern)
        return match.group(1)

    return read


CHECKS: tuple[tuple[str, str, Reader], ...] = (
    ("src/services/web-client/package.json", "version", json_field("version")),
    ("src/services/web-client/package-lock.json", "version", json_field("version")),
    (
        "src/services/web-client/package-lock.json",
        'packages[""].version',
        json_field("packages", "", "version"),
    ),
    ("desktop/package.json", "version", json_field("version")),
    ("desktop/package-lock.json", "version", json_field("version")),
    ("desktop/package-lock.json", 'packages[""].version', json_field("packages", "", "version")),
    ("desktop/src-tauri/tauri.conf.json", "version", json_field("version")),
    ("desktop/src-tauri/Cargo.toml", "package.version", cargo_package),
    ("desktop/src-tauri/Cargo.lock", "horus-desktop", cargo_lock_entry("horus-desktop")),
    ("desktop/ui/index.html", "bundle folder placeholder", first_match(r"Horus-Beta-([^\s\"<]+)")),
    ("src/infra/.env.example", "HORUS_VERSION", env_assignment("HORUS_VERSION")),
    ("CHANGELOG.md", "newest release heading", first_match(r"^## \[?(\d+\.\d+\.\d+[^\s\]]*)")),
)


def check(root: Path, tag: str | None = None) -> list[str]:
    version_file = root / "VERSION"
    try:
        expected = version_file.read_text(encoding="utf-8").strip()
    except OSError as exc:
        return [f"VERSION: cannot read {version_file} ({exc})"]
    if not RELEASE.fullmatch(expected):
        return [f"VERSION: {expected!r} is not MAJOR.MINOR.PATCH"]

    problems = []
    if tag is not None:
            core_tag_version = tag.removeprefix("v").split("-")[0]
            if core_tag_version != expected:
                problems.append(f"git tag {tag!r} does not name VERSION {expected!r}")
    for rel, field, read in CHECKS:
        try:
            found = read((root / rel).read_text(encoding="utf-8"))
        except (OSError, KeyError, ValueError, TypeError) as exc:
            problems.append(f"{rel}: cannot read {field} ({type(exc).__name__}: {exc})")
            continue
        if found != expected:
            problems.append(f"{rel}: {field} is {found!r}, VERSION says {expected!r}")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Fail when a version number in the repository differs from VERSION."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=REPO,
        help=f"Repository root to check (default: {REPO}).",
    )
    parser.add_argument(
        "--tag",
        help="Release tag being built (e.g. v0.1.2); it must name the same version.",
    )
    args = parser.parse_args(argv)

    problems = check(args.root, args.tag)
    for problem in problems:
        print(problem)
    if problems:
        print(f"\n{len(problems)} version number(s) disagree with VERSION.")
        return 1
    print(f"All {len(CHECKS)} version numbers match VERSION.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
