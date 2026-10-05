from __future__ import annotations

import re
import statistics
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any

from eval_scoring import (
    answer_correct,
    detect_fallback,
    expected_route,
    expected_sources,
    final_status,
    missing_patterns,
    route_correct,
    source_check,
)
from eval_testset import CATEGORIES

REPORT_KIND = "horus-eval"
SCHEMA_VERSION = 1
REVIEWER_SLOTS = 2
COMPLETE_TIMING_SOURCES = frozenset({"websocket", "http"})

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_UNSAFE_LABEL_CHARS = re.compile(r"[^A-Za-z0-9._-]+")
_DOCKER_SIZE = re.compile(r"^\s*([0-9]*\.?[0-9]+)\s*([KMGT]?i?B)\s*$", re.IGNORECASE)
_DOCKER_UNITS = {
    "B": 1,
    "KB": 10**3,
    "MB": 10**6,
    "GB": 10**9,
    "TB": 10**12,
    "KIB": 2**10,
    "MIB": 2**20,
    "GIB": 2**30,
    "TIB": 2**40,
}


def blank_review() -> list[dict[str, Any]]:
    return [{"reviewer": None, "answer_correct": None, "comment": None} for _ in range(REVIEWER_SLOTS)]


def question_record(item: dict[str, Any], outcome: dict[str, Any]) -> dict[str, Any]:
    answer = outcome.get("answer")
    chat_mode = outcome.get("mode", "chat") == "chat"
    observed_route = outcome.get("observed_route")
    status, error = final_status(outcome.get("status", "error"), outcome.get("error"), answer)
    sources = source_check(
        item,
        retrieval_steps=outcome.get("retrieval_steps"),
        retrieved_sources=outcome.get("retrieved_sources"),
        cited_sources=outcome.get("cited_sources"),
        events_complete=outcome.get("timing_source") in COMPLETE_TIMING_SOURCES,
    )
    return {
        "id": item["id"],
        "category": item["category"],
        "difficulty": item["difficulty"],
        "question": item["question"],
        "expected_answer": item["expected_answer"],
        "expected_source": expected_sources(item) or None,
        "expected_route": expected_route(item),
        "status": status,
        "error": error,
        "conversation_id": outcome.get("conversation_id"),
        "task_id": outcome.get("task_id"),
        "observed_route": observed_route,
        "answered_by": outcome.get("answered_by"),
        "models": list(outcome.get("models") or []),
        "devices": list(outcome.get("devices") or []),
        "timing_source": outcome.get("timing_source"),
        "submit_http_s": outcome.get("submit_http_s"),
        "first_event_s": outcome.get("first_event_s"),
        "retrieval_s": outcome.get("retrieval_s"),
        "reasoning_start_s": outcome.get("reasoning_start_s"),
        "ttft_s": outcome.get("ttft_s"),
        "total_s": outcome.get("total_s"),
        "answer": answer,
        "retrieval_steps": outcome.get("retrieval_steps"),
        "retrieved_sources": outcome.get("retrieved_sources"),
        "cited_sources": outcome.get("cited_sources"),
        "fallback": detect_fallback(answer),
        "answer_correct_auto": answer_correct(item, answer) if chat_mode else None,
        "missing_patterns": missing_patterns(item["answer_patterns"], answer) if chat_mode else None,
        **sources,
        "route_correct": route_correct(item, observed_route) if chat_mode else None,
        "review": blank_review() if chat_mode else None,
    }


def rate(flags: list[bool | None]) -> dict[str, Any]:
    known = [flag for flag in flags if flag is not None]
    correct = sum(1 for flag in known if flag)
    return {
        "n": len(known),
        "correct": correct,
        "pct": round(100.0 * correct / len(known), 1) if known else None,
    }


def stats(values: list[float | None]) -> dict[str, Any]:
    known = sorted(value for value in values if value is not None)
    if not known:
        return {"n": 0}
    return {
        "n": len(known),
        "mean": round(statistics.mean(known), 3),
        "median": round(statistics.median(known), 3),
        "p90": round(known[min(int(len(known) * 0.9), len(known) - 1)], 3),
        "min": round(known[0], 3),
        "max": round(known[-1], 3),
        "sum": round(sum(known), 3),
    }


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
        "answer_correct_pct": round(100.0 * agreed_correct / len(reviewed), 1) if reviewed else None,
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


def build_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
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
    summary["manual_review"] = manual_review_summary(records)
    summary["by_category"] = {
        category: _group_summary([r for r in records if r.get("category") == category])
        for category in CATEGORIES
        if any(r.get("category") == category for r in records)
    }
    return summary


def build_report(
    *,
    label: str,
    run: dict[str, Any],
    testset: dict[str, Any],
    records: list[dict[str, Any]],
    llama_cpp_build: str | None = None,
    model: dict[str, Any] | None = None,
    machine: dict[str, Any] | None = None,
    resources: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "kind": REPORT_KIND,
        "schema_version": SCHEMA_VERSION,
        "label": label,
        "run": run,
        "testset": testset,
        "llama_cpp": {"build": llama_cpp_build},
        "model": {"name": None, "file": None, "sha256": None, **(model or {})},
        "machine": machine or {},
        "resources": resources,
        "summary": build_summary(records),
        "questions": records,
    }


def resummarize(report: dict[str, Any]) -> dict[str, Any]:
    if report.get("kind") != REPORT_KIND:
        raise ValueError(f"not a {REPORT_KIND} report (kind={report.get('kind')!r})")
    return {**report, "summary": build_summary(report.get("questions") or [])}


def safe_label(label: str) -> str:
    cleaned = _UNSAFE_LABEL_CHARS.sub("-", label.strip()).strip("-.")
    if not cleaned:
        raise ValueError("label must contain at least one letter or digit")
    return cleaned


def report_path(out_dir: Path | str, label: str, run_date: date) -> Path:
    stem = f"{safe_label(label)}-{run_date.isoformat()}"
    candidate = Path(out_dir) / f"{stem}.json"
    suffix = 2
    while candidate.exists():
        candidate = Path(out_dir) / f"{stem}-{suffix}.json"
        suffix += 1
    return candidate


def is_sha256(value: str | None) -> bool:
    return bool(value) and bool(_SHA256.match(value.strip().lower()))


def parse_docker_size(text: str) -> int | None:
    match = _DOCKER_SIZE.match(text or "")
    if not match:
        return None
    unit = match.group(2).upper()
    return int(float(match.group(1)) * _DOCKER_UNITS[unit]) if unit in _DOCKER_UNITS else None


def parse_docker_stats(output: str) -> dict[str, int]:
    usage = {}
    for line in (output or "").splitlines():
        name, _, mem = line.partition("\t")
        used = parse_docker_size(mem.split("/")[0]) if mem else None
        if name.strip() and used is not None:
            usage[name.strip()] = used
    return usage


def parse_meminfo_swap_used(meminfo: str) -> int | None:
    fields = {}
    for line in (meminfo or "").splitlines():
        key, _, rest = line.partition(":")
        parts = rest.split()
        if parts and parts[0].isdigit():
            fields[key.strip()] = int(parts[0]) * 1024
    if "SwapTotal" not in fields or "SwapFree" not in fields:
        return None
    return fields["SwapTotal"] - fields["SwapFree"]


class ResourcePeaks:
    def __init__(self) -> None:
        self.samples = 0
        self.container_peaks: dict[str, int] = {}
        self.containers_sum_peak: int | None = None
        self.swap_peak: int | None = None

    def add(self, container_usage: dict[str, int], swap_used: int | None = None) -> None:
        self.samples += 1
        for name, used in container_usage.items():
            self.container_peaks[name] = max(used, self.container_peaks.get(name, 0))
        if container_usage:
            total = sum(container_usage.values())
            self.containers_sum_peak = max(total, self.containers_sum_peak or 0)
        if swap_used is not None:
            self.swap_peak = max(swap_used, self.swap_peak or 0)

    def as_dict(self) -> dict[str, Any]:
        return {
            "samples": self.samples,
            "container_peak_mem_bytes": dict(sorted(self.container_peaks.items())),
            "containers_sum_peak_mem_bytes": self.containers_sum_peak,
            "swap_peak_used_bytes": self.swap_peak,
        }


def titles_from_query_result(raw: Any) -> list[str]:
    metadatas = raw.get("metadatas") if isinstance(raw, dict) else None
    if not isinstance(metadatas, list):
        return []
    rows = metadatas[0] if metadatas and isinstance(metadatas[0], list) else metadatas
    titles = []
    for meta in rows:
        title = meta.get("title") if isinstance(meta, dict) else None
        if isinstance(title, str) and title and title not in titles:
            titles.append(title)
    return titles
