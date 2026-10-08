#!/usr/bin/env python3
from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path

KIT_SRC = Path(__file__).resolve().parents[2] / "opensource" / "horus-bench-kit" / "src"
if str(KIT_SRC) not in sys.path:
    sys.path.insert(0, str(KIT_SRC))

from horus_bench_kit.cli import compare  # noqa: E402
from horus_profile import COMPARE, COMPARE_DESCRIPTION  # noqa: E402


def main(argv: Sequence[str] | None = None) -> int:
    return compare.main(argv, profile=COMPARE, prog=None, description=COMPARE_DESCRIPTION, version_option=False)


if __name__ == "__main__":
    raise SystemExit(main())
