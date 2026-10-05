from __future__ import annotations

import re
import unicodedata
from functools import lru_cache
from pathlib import PurePosixPath
from typing import Any

ROUTE_DIRECT = "DIRECT_ANSWER"
ROUTE_AGENT = "AGENT"
ROUTE_NONE = "NONE"

FALLBACK_MARKERS = {
    "spiral": "couldn't extract a consistent answer from the retrieved",
    "timeout": "took too long to respond",
    "task_timeout": "exceeded the maximum processing time",
}
STOPPED_BY_WATCHDOG = "stopped by the MAS TASK_TIMEOUT watchdog"
SOURCE_BASIS_CITED = "cited"
SOURCE_BASIS_RETRIEVAL = "retrieval"

_CHARACTER_FIXES = str.maketrans(
    {
        "‘": "'",
        "’": "'",
        "“": '"',
        "”": '"',
        "。": ".",
        " ": " ",
    }
)
_MARKDOWN_EMPHASIS = re.compile(r"\*\*|__|`")


@lru_cache(maxsize=1024)
def compile_pattern(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern, re.IGNORECASE)


def normalize_answer(text: str | None) -> str:
    if not text:
        return ""
    folded = unicodedata.normalize("NFKC", text).translate(_CHARACTER_FIXES)
    return _MARKDOWN_EMPHASIS.sub("", folded)


def detect_fallback(answer: str | None) -> str | None:
    normalized = normalize_answer(answer).lower()
    for kind, marker in FALLBACK_MARKERS.items():
        if marker in normalized:
            return kind
    return None


def missing_patterns(patterns: list[str], answer: str | None) -> list[str]:
    normalized = normalize_answer(answer)
    return [pattern for pattern in patterns if not compile_pattern(pattern).search(normalized)]


def answer_correct(item: dict[str, Any], answer: str | None) -> bool:
    if not normalize_answer(answer).strip() or detect_fallback(answer):
        return False
    return not missing_patterns(item["answer_patterns"], answer)


def expected_sources(item: dict[str, Any]) -> list[str]:
    source = item.get("expected_source")
    if source is None:
        return []
    if isinstance(source, str):
        return [source]
    return list(source)


def expected_route(item: dict[str, Any]) -> str:
    return ROUTE_DIRECT if item["category"] == "direct" else ROUTE_AGENT


def route_correct(item: dict[str, Any], observed_route: str | None) -> bool | None:
    if observed_route is None:
        return None
    return observed_route == expected_route(item)


def final_status(status: str, error: str | None, answer: str | None) -> tuple[str, str | None]:
    if status == "ok" and detect_fallback(answer) == "task_timeout":
        return "timeout", error or STOPPED_BY_WATCHDOG
    return status, error


def source_key(title: str) -> str:
    return PurePosixPath(str(title).replace("\\", "/").strip().lower()).stem


def _ranked_keys(ranking: list[str]) -> list[str]:
    return list(dict.fromkeys(source_key(title) for title in ranking if title))


def source_ranks(item: dict[str, Any], rankings: list[list[str]]) -> list[int | None]:
    ranked = [_ranked_keys(ranking) for ranking in rankings]
    ranks: list[int | None] = []
    for wanted in (source_key(source) for source in expected_sources(item)):
        positions = [keys.index(wanted) + 1 for keys in ranked if wanted in keys]
        ranks.append(min(positions, default=None))
    return ranks


def _source_result(
    basis: str | None, ranks: list[int | None] | None, correct: bool | None
) -> dict[str, Any]:
    return {"source_basis": basis, "source_ranks": ranks, "source_correct_auto": correct}


def source_check(
    item: dict[str, Any],
    *,
    retrieval_steps: int | None = None,
    retrieved_sources: list[list[str]] | None = None,
    cited_sources: list[str] | None = None,
    events_complete: bool = True,
) -> dict[str, Any]:
    category = item["category"]
    if category == "not_in_corpus" or (category == "direct" and retrieval_steps is None):
        return _source_result(None, None, None)
    if category == "direct":
        if retrieval_steps or cited_sources:
            return _source_result(SOURCE_BASIS_RETRIEVAL, None, False)
        return _source_result(SOURCE_BASIS_RETRIEVAL, None, True if events_complete else None)
    wanted = {source_key(source) for source in expected_sources(item)}
    if cited_sources is not None:
        cited = {source_key(source) for source in cited_sources if source}
        return _source_result(SOURCE_BASIS_CITED, None, bool(wanted) and wanted <= cited)
    if retrieved_sources is None:
        return _source_result(None, None, None)
    ranks = source_ranks(item, retrieved_sources)
    top = len(ranks)
    in_top = bool(ranks) and all(rank is not None and rank <= top for rank in ranks)
    correct = True if in_top else (False if events_complete else None)
    return _source_result(SOURCE_BASIS_RETRIEVAL, ranks, correct)
