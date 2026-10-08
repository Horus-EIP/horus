from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

KIT_SRC = Path(__file__).resolve().parents[2] / "opensource" / "horus-bench-kit" / "src"
if str(KIT_SRC) not in sys.path:
    sys.path.insert(0, str(KIT_SRC))

from horus_bench_kit import testset as kit  # noqa: E402
from horus_bench_kit.scoring import compile_pattern, expected_sources  # noqa: E402, F401
from horus_bench_kit.testset import (  # noqa: E402, F401
    CATEGORIES,
    DIFFICULTIES,
    IN_CORPUS_CATEGORIES,
    REQUIRED_FIELDS,
    absent_term_errors,
    corpus_errors,
    corpus_root,
    duplicate_errors,
    file_sha256,
    grounding_errors,
    lf_normalized,
    read_documents,
    schema_errors,
    select_items,
)
from horus_eval_profile import (  # noqa: E402, F401
    CANNED_NON_ANSWERS,
    DEFAULT_TESTSET_PATH,
    FALLBACK_MARKERS,
    REPO_ROOT,
    answer_correct,
)


def load_testset(path: Path | str = DEFAULT_TESTSET_PATH) -> dict[str, Any]:
    return kit.load_testset(path, yaml_only=True)


def self_consistency_errors(testset: dict[str, Any]) -> list[str]:
    return kit.self_consistency_errors(testset, CANNED_NON_ANSWERS, FALLBACK_MARKERS)


def validate_testset(testset: dict[str, Any], root: Path) -> list[str]:
    return kit.validate_testset(testset, root, CANNED_NON_ANSWERS, FALLBACK_MARKERS)


def corpus_problems(expected_names: list[str], stored_titles: list[str]) -> list[str]:
    counts: dict[str, int] = {}
    for title in stored_titles:
        counts[title] = counts.get(title, 0) + 1
    problems = [f"{name} is not in the knowledge store" for name in expected_names if name not in counts]
    problems += [
        f"{name} is stored {counts[name]} times; delete the duplicates so retrieval is not skewed"
        for name in expected_names
        if counts.get(name, 0) > 1
    ]
    return problems
