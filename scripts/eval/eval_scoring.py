from __future__ import annotations

import sys
from pathlib import Path

KIT_SRC = Path(__file__).resolve().parents[2] / "opensource" / "horus-bench-kit" / "src"
if str(KIT_SRC) not in sys.path:
    sys.path.insert(0, str(KIT_SRC))

from horus_bench_kit.scoring import (  # noqa: E402, F401
    ROUTE_AGENT,
    ROUTE_DIRECT,
    ROUTE_NONE,
    SOURCE_BASIS_CITED,
    SOURCE_BASIS_RETRIEVAL,
    compile_pattern,
    expected_route,
    expected_sources,
    missing_patterns,
    normalize_answer,
    route_correct,
    source_check,
    source_key,
    source_ranks,
)
from horus_eval_profile import (  # noqa: E402, F401
    FALLBACK_MARKERS,
    STOPPED_BY_WATCHDOG,
    answer_correct,
    detect_fallback,
    final_status,
)
