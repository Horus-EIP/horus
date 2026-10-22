#!/usr/bin/env python3

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

CUDA_PREFIXES = ("nvidia-", "cuda-")
CUDA_PACKAGES = {"triton"}
TORCH_STACK = ("torch", "sentence-transformers")
DISTRIBUTION = re.compile(r"([A-Za-z0-9][A-Za-z0-9._-]*)\s*(?:==\s*(\S+)|@\s*\S+)?")


def normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def installed(listing: str) -> dict[str, tuple[str, str]]:
    packages = {}
    for raw in listing.splitlines():
        line = raw.strip()
        match = DISTRIBUTION.match(line) if line and not line.startswith("#") else None
        if match:
            packages[normalize(match.group(1))] = (match.group(1), match.group(2) or "")
    return packages


def pinned_torch(requirements: str) -> str | None:
    for raw in requirements.splitlines():
        match = DISTRIBUTION.match(raw.split(" #", 1)[0].strip())
        if match and normalize(match.group(1)) == "torch":
            return match.group(2)
    return None


def check(packages: dict[str, tuple[str, str]], pin: str | None, source: str) -> list[str]:
    if not packages:
        return ["no packages listed: the image could not be inspected"]

    problems = [
        f"CUDA package in the image: {name}=={version}"
        for key, (name, version) in sorted(packages.items())
        if key.startswith(CUDA_PREFIXES) or key in CUDA_PACKAGES
    ]
    if not pin:
        problems.extend(
            f"{packages[key][0]}=={packages[key][1]} is in a CPU image, but {source} "
            "pins no torch: nothing on the CPU path may need it"
            for key in TORCH_STACK
            if key in packages
        )
        return problems
    torch = packages.get("torch", ("", ""))[1]
    public, _, local = torch.partition("+")
    if torch and local != "cpu":
        problems.append(f"torch {torch} is not the CPU build")
    if public != pin:
        found = f"torch {torch} is installed" if torch else "torch is not installed"
        problems.append(f"{found}, but {source} pins torch=={pin}")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Fail when a CPU image ships CUDA packages, or any torch when its "
        "requirements pin none, or a torch other than the pinned CPU build "
        "when they pin one."
    )
    parser.add_argument(
        "packages",
        type=Path,
        help="Output of `python -m pip list --format=freeze` run inside the image.",
    )
    parser.add_argument(
        "--requirements",
        type=Path,
        help="The requirements file the image or environment was installed from. Without "
        "a torch==X pin in it (or without this option), torch must be absent; with "
        "one, that pin must be what is installed, as the CPU build.",
    )
    args = parser.parse_args(argv)

    packages = installed(args.packages.read_text(encoding="utf-8"))
    pin = None
    source = "the image"
    if args.requirements is not None:
        pin = pinned_torch(args.requirements.read_text(encoding="utf-8"))
        source = str(args.requirements)
    problems = check(packages, pin, source)
    for problem in problems:
        print(problem)
    if problems:
        print(f"\n{len(problems)} problem(s): this is not a CPU-only image.")
        return 1
    torch = packages.get("torch", ("", ""))[1]
    print(
        f"{len(packages)} packages, none from CUDA; "
        + (f"torch {torch}." if torch else "no torch.")
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
