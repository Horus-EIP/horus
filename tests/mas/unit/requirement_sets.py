from __future__ import annotations

from pathlib import Path

from packaging.requirements import Requirement

MAS_ROOT = Path(__file__).resolve().parents[3] / "src" / "services" / "mas"
REQUIREMENT_FILES = ("requirements.txt", "requirements-cpu.txt", "requirements-gpu.txt")
UPPER_BOUND_OPERATORS = ("<", "<=", "==", "~=")


def listed_requirements(file_name: str) -> list[Requirement]:
    found: list[Requirement] = []
    for raw in (MAS_ROOT / file_name).read_text(encoding="utf-8").splitlines():
        line = raw.split(" #", 1)[0].strip()
        if line.startswith("-r "):
            found.extend(listed_requirements(line.split(None, 1)[1]))
        elif line and not line.startswith(("#", "-")):
            found.append(Requirement(line))
    return found


def requirement(file_name: str, project: str) -> Requirement:
    for parsed in listed_requirements(file_name):
        if parsed.name.lower() == project.lower():
            return parsed
    raise AssertionError(f"{file_name} does not list {project}")


def has_upper_bound(requirement_: Requirement) -> bool:
    return any(spec.operator in UPPER_BOUND_OPERATORS for spec in requirement_.specifier)
