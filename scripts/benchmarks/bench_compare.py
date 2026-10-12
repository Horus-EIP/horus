from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

KIT_SRC = Path(__file__).resolve().parents[2] / "opensource" / "horus-bench-kit" / "src"
if str(KIT_SRC) not in sys.path:
    sys.path.insert(0, str(KIT_SRC))

from horus_bench_kit import compare as kit  # noqa: E402
from horus_bench_kit.compare import (  # noqa: E402, F401
    BENCH_KINDS,
    HEADLINE_TESTS,
    BenchSelection,
    Side,
    bench_detail,
    bench_metrics,
    choose_model,
    headline_key,
)
from horus_bench_kit.llama_bench import RAW_REPORT_KIND as RAW_LLAMA_BENCH_KIND  # noqa: E402, F401
from horus_bench_kit.markdown import (  # noqa: E402, F401
    EMPTY,
    Metric,
    MetricRow,
    format_change,
    format_metric,
    format_number,
    row_change,
)
from horus_profile import (  # noqa: E402, F401
    COMPARE,
    EVAL_KIND,
    RECORDED_KIND,
    SECTION_10_ROWS,
    eval_metrics,
    recorded_metrics,
)


def load_document(path: Path | str) -> dict[str, Any]:
    return kit.load_document(path, COMPARE)


def build_side(name: str, documents: list[dict[str, Any]], selection: BenchSelection) -> Side:
    return kit.build_side(name, documents, selection, COMPARE)


def compare_markdown(
    before: list[Path | str], after: list[Path | str] | None, selection: BenchSelection
) -> str:
    return kit.compare_markdown(before, after, selection, COMPARE)
