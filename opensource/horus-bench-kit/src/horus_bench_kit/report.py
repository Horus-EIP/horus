# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from horus_bench_kit.files import check_report
from horus_bench_kit.scoring import (
    answer_correct,
    detect_fallback,
    expected_route,
    expected_sources,
    missing_patterns,
    route_correct,
    source_check,
)
from horus_bench_kit.stats import rate, stats
from horus_bench_kit.target import MODE_CHAT
from horus_bench_kit.testset import CATEGORIES

REPORT_KIND = "horus-bench-kit-eval"
SCHEMA_VERSION = 1
REVIEWER_SLOTS = 2
COMPLETE_TIMING_SOURCES = frozenset({"websocket", "http"})
OUTCOME_FIELDS = ("observed_route", "models", "timing_source", "ttft_s", "total_s", "usage")
LIST_FIELDS = frozenset({"models", "devices"})

Summarizer = Callable[[list[dict[str, Any]]], Any]


def keep_status(status: str, error: str | None, _answer: str | None) -> tuple[str, str | None]:
    return status, error


def usage_summary(records: list[dict[str, Any]]) -> dict[str, Any] | None:
    usages = [r["usage"] for r in records if isinstance(r.get("usage"), dict)]
    if not usages:
        return None
    return {
        "questions": len(usages),
        "prompt_tokens": stats([usage.get("prompt_tokens") for usage in usages]),
        "completion_tokens": stats([usage.get("completion_tokens") for usage in usages]),
    }


@dataclass(frozen=True)
class Profile:
    kind: str = REPORT_KIND
    schema_version: int = SCHEMA_VERSION
    fallback_markers: Mapping[str, str] = field(default_factory=dict)
    final_status: Callable[[str, str | None, str | None], tuple[str, str | None]] = keep_status
    outcome_fields: tuple[str, ...] = OUTCOME_FIELDS
    list_fields: frozenset[str] = LIST_FIELDS
    summary_sections: tuple[tuple[str, Summarizer], ...] = (("usage", usage_summary),)
    categories: tuple[str, ...] = CATEGORIES


DEFAULT_PROFILE = Profile()


def blank_review() -> list[dict[str, Any]]:
    return [
        {"reviewer": None, "answer_correct": None, "comment": None} for _ in range(REVIEWER_SLOTS)
    ]


def question_record(
    item: dict[str, Any], outcome: dict[str, Any], profile: Profile = DEFAULT_PROFILE
) -> dict[str, Any]:
    answer = outcome.get("answer")
    chat_mode = outcome.get("mode", MODE_CHAT) == MODE_CHAT
    observed_route = outcome.get("observed_route")
    status, error = profile.final_status(
        outcome.get("status", "error"), outcome.get("error"), answer
    )
    sources = source_check(
        item,
        retrieval_steps=outcome.get("retrieval_steps"),
        retrieved_sources=outcome.get("retrieved_sources"),
        cited_sources=outcome.get("cited_sources"),
        events_complete=outcome.get("timing_source") in COMPLETE_TIMING_SOURCES,
    )
    record: dict[str, Any] = {
        "id": item["id"],
        "category": item["category"],
        "difficulty": item["difficulty"],
        "question": item["question"],
        "expected_answer": item["expected_answer"],
        "expected_source": expected_sources(item) or None,
        "expected_route": expected_route(item),
        "status": status,
        "error": error,
    }
    for name in profile.outcome_fields:
        value = outcome.get(name)
        record[name] = list(value or []) if name in profile.list_fields else value
    markers = profile.fallback_markers
    record.update(
        {
            "answer": answer,
            "retrieval_steps": outcome.get("retrieval_steps"),
            "retrieved_sources": outcome.get("retrieved_sources"),
            "cited_sources": outcome.get("cited_sources"),
            "fallback": detect_fallback(answer, markers),
            "answer_correct_auto": answer_correct(item, answer, markers) if chat_mode else None,
            "missing_patterns": missing_patterns(item["answer_patterns"], answer)
            if chat_mode
            else None,
            **sources,
            "route_correct": route_correct(item, observed_route) if chat_mode else None,
            "review": blank_review() if chat_mode else None,
        }
    )
    return record


def field_stats(name: str) -> Summarizer:
    return lambda records: stats([record.get(name) for record in records])


def manual_review_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    reviewable = [record for record in records if record.get("review")]
    reviewed = [
        record
        for record in reviewable
        if all(slot.get("answer_correct") is not None for slot in record["review"])
    ]
    agreed_correct = sum(
        1 for record in reviewed if all(slot["answer_correct"] is True for slot in record["review"])
    )
    disagreements = [
        record["id"]
        for record in reviewed
        if len({bool(slot["answer_correct"]) for slot in record["review"]}) > 1
    ]
    return {
        "reviewed": len(reviewed),
        "pending": len(reviewable) - len(reviewed),
        "agreed_correct": agreed_correct,
        "disagreements": disagreements,
        "answer_correct_pct": round(100.0 * agreed_correct / len(reviewed), 1)
        if reviewed
        else None,
    }


def rank_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    ranks = [rank for record in records for rank in record.get("source_ranks") or []]
    return {
        **stats([rank for rank in ranks if rank is not None]),
        "first": sum(1 for rank in ranks if rank == 1),
        "not_retrieved": sum(1 for rank in ranks if rank is None),
    }


def _group_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "questions": len(records),
        "answer_correct_auto": rate([r.get("answer_correct_auto") for r in records]),
        "source_correct_auto": rate([r.get("source_correct_auto") for r in records]),
        "source_rank": rank_summary(records),
        "route_correct": rate([r.get("route_correct") for r in records]),
        "total_s": stats([r.get("total_s") for r in records]),
    }


def build_summary(
    records: list[dict[str, Any]], profile: Profile = DEFAULT_PROFILE
) -> dict[str, Any]:
    summary = _group_summary(records)
    summary["status"] = dict(Counter(r.get("status") for r in records))
    summary["fallbacks"] = dict(Counter(r["fallback"] for r in records if r.get("fallback")))
    summary["source_basis"] = dict(
        Counter(
            r.get("source_basis") or "not_observable"
            for r in records
            if r.get("category") != "not_in_corpus"
        )
    )
    summary["ttft_s"] = stats([r.get("ttft_s") for r in records])
    for key, summarize in profile.summary_sections:
        summary[key] = summarize(records)
    summary["manual_review"] = manual_review_summary(records)
    summary["by_category"] = {
        category: _group_summary([r for r in records if r.get("category") == category])
        for category in profile.categories
        if any(r.get("category") == category for r in records)
    }
    return summary


def build_report(
    *,
    label: str,
    run: dict[str, Any],
    testset: dict[str, Any],
    records: list[dict[str, Any]],
    sections: Mapping[str, Any] | None = None,
    profile: Profile = DEFAULT_PROFILE,
) -> dict[str, Any]:
    return {
        "kind": profile.kind,
        "schema_version": profile.schema_version,
        "label": label,
        "run": run,
        "testset": testset,
        **(sections or {}),
        "summary": build_summary(records, profile),
        "questions": records,
    }


def resummarize(report: dict[str, Any], profile: Profile = DEFAULT_PROFILE) -> dict[str, Any]:
    check_report(report, profile.kind, profile.schema_version)
    return {**report, "summary": build_summary(report.get("questions") or [], profile)}
