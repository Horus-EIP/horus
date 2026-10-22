#!/usr/bin/env python3

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import system_packages  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
NOTICES = REPO / "THIRD_PARTY_NOTICES"
COMPONENTS = Path(__file__).resolve().parent / "components.yaml"
SECTION = "7. Source code of GPL and LGPL components"


def notice_packages(text: str, service: str) -> dict[str, tuple[str, str]]:
    lines = text.splitlines()
    try:
        start = lines.index(SECTION) + 1
    except ValueError as error:
        raise ValueError(f"{NOTICES} has no Section 7 source offer") from error

    entries: list[list[str]] = []
    current: list[str] = []
    for line in lines[start:]:
        if line.startswith("7.3 "):
            break
        if re.match(r"^- \S+", line):
            if current:
                entries.append(current)
            current = [line]
        elif current:
            current.append(line)
    if current:
        entries.append(current)

    service_name = service.replace("_", "-")
    found = {}
    for entry in entries:
        heading = re.match(r"^- (\S+)(?:\s+(\S+))?", entry[0])
        if not heading:
            continue
        details = " ".join(line.strip() for line in entry[1:])
        image_match = re.search(r"\bImages:\s*(.*?)\.", details)
        if not image_match:
            continue
        images = {name.strip() for name in image_match.group(1).split(",")}
        if service_name not in images:
            continue
        licence_match = re.search(r"\bLicence:\s*(.*?)\.\s*Images:", details)
        found[heading.group(1)] = (
            heading.group(2) or "",
            licence_match.group(1) if licence_match else "GPL/LGPL",
        )
    return found


def markdown_report(service: str, notices: str, packages: list[dict]) -> tuple[str, bool]:
    listed = notice_packages(notices, service)
    lines = [
        f"#### GPL / LGPL system packages · {service}",
        "",
        "| Package | Image version | Licence | Source offer |",
        "| :--- | :--- | :--- | :--- |",
    ]
    mismatches = []
    for package in packages:
        name = package["name"]
        entry = listed.get(name)
        if entry and entry[0] == package["version"]:
            _, licence = entry
            source_offer = f"Listed in Section 7 ({licence})"
        elif entry:
            source_offer = f"❌ Version mismatch; notice lists `{entry[0]}`"
            mismatches.append(name)
        else:
            source_offer = "❌ Missing from Section 7"
            mismatches.append(name)
        lines.append(
            f"| `{name}` | `{package['version']}` | {package['licence']} | {source_offer} |"
        )

    if not packages:
        lines.append("| No GPL/LGPL OS packages detected | — | — | Scan completed |")
    if mismatches:
        lines += ["", f"**Error:** {len(mismatches)} package(s) do not match Section 7. "
                  "Refresh the system package notices for the release images."]
    lines.append("")
    return "\n".join(lines), not mismatches


def scan_image(image: str) -> tuple[dict, list[str]]:
    try:
        import yaml
    except ImportError as error:
        raise RuntimeError("PyYAML is required to load the system licence overrides") from error

    components = yaml.safe_load(COMPONENTS.read_text(encoding="utf-8")) or {}
    overrides = components.get("system_overrides") or {}
    return system_packages.image_packages(image, overrides)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Report GPL/LGPL system packages in an image.")
    parser.add_argument("--service", required=True)
    parser.add_argument("--image", required=True)
    args = parser.parse_args(argv)

    try:
        info, problems = scan_image(args.image)
        if problems:
            raise RuntimeError("\n".join(problems))
        report, complete = markdown_report(
            args.service,
            NOTICES.read_text(encoding="utf-8"),
            info["packages"],
        )
    except (OSError, RuntimeError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as error:
        detail = error.stderr.decode("utf-8", "replace").strip() if error.stderr else str(error)
        print(f"ERROR: Docker could not scan {args.image}: {detail}", file=sys.stderr)
        return 1

    print(report)
    return 0 if complete else 1


if __name__ == "__main__":
    raise SystemExit(main())
