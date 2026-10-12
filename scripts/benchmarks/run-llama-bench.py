#!/usr/bin/env python3
from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path

KIT_SRC = Path(__file__).resolve().parents[2] / "opensource" / "horus-bench-kit" / "src"
if str(KIT_SRC) not in sys.path:
    sys.path.insert(0, str(KIT_SRC))

from horus_bench_kit.cli import llama_bench  # noqa: E402
from horus_bench_kit.shell import Shell  # noqa: E402
from horus_profile import LLAMA_BENCH, HorusShell  # noqa: E402


def main(argv: Sequence[str] | None = None, *, shell: Shell | None = None) -> int:
    return llama_bench.main(argv, profile=LLAMA_BENCH, shell=shell or HorusShell())


if __name__ == "__main__":
    raise SystemExit(main())
