import os
from collections.abc import Mapping
from pathlib import Path

UNKNOWN_VERSION = "0.0.0"


def resolve_version(
    environ: Mapping[str, str] | None = None, start: Path | None = None
) -> str:
    environ = os.environ if environ is None else environ
    declared = environ.get("HORUS_VERSION", "").strip()
    if declared:
        return declared
    here = start or Path(__file__).resolve()
    for folder in here.parents:
        version_file = folder / "VERSION"
        if version_file.is_file():
            return version_file.read_text(encoding="utf-8").strip() or UNKNOWN_VERSION
    return UNKNOWN_VERSION


HORUS_VERSION = resolve_version()
