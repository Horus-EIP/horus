from __future__ import annotations

import re
import statistics
from collections import Counter
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
from eval_stack import LLM_PROCESS_NAME, LLM_ROUTING_METHOD
from eval_testset import CATEGORIES

REPORT_KIND = "horus-eval"
SCHEMA_VERSION = 2
REVIEWER_SLOTS = 2
COMPLETE_TIMING_SOURCES = frozenset({"websocket", "http"})

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
        "dispatch_s": outcome.get("dispatch_s"),
        "routing_decision": outcome.get("routing_decision"),
        "retrieval_s": outcome.get("retrieval_s"),
        "reasoning_start_s": outcome.get("reasoning_start_s"),
        "ttft_s": outcome.get("ttft_s"),
        "total_s": outcome.get("total_s"),
        "llm": outcome.get("llm"),
        "resources": outcome.get("resources"),
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


def _throughput(tokens: float, seconds: float) -> float | None:
    return round(tokens / seconds, 2) if seconds > 0 else None


def llm_summary(records: list[dict[str, Any]]) -> dict[str, Any] | None:
    usages = [
        r["llm"] for r in records if isinstance(r.get("llm"), dict) and "prompt_s" in r["llm"]
    ]
    restarts = sum(1 for r in records if isinstance(r.get("llm"), dict) and r["llm"].get("restarted"))
    if not usages and not restarts:
        return None

    def total(key: str) -> float:
        return sum(usage.get(key) or 0 for usage in usages)

    return {
        "questions": len(usages),
        "server_restarts": restarts,
        "prompt_s": stats([usage.get("prompt_s") for usage in usages]),
        "prompt_tokens": stats([usage.get("prompt_tokens") for usage in usages]),
        "generation_s": stats([usage.get("generation_s") for usage in usages]),
        "generated_tokens": stats([usage.get("generated_tokens") for usage in usages]),
        "prompt_tps": _throughput(total("prompt_tokens"), total("prompt_s")),
        "generation_tps": _throughput(total("generated_tokens"), total("generation_s")),
    }


def routing_summary(records: list[dict[str, Any]]) -> dict[str, Any] | None:
    probed = [r["routing_decision"] for r in records if isinstance(r.get("routing_decision"), dict)]
    observed = [probe for probe in probed if "decisions" in probe]
    restarts = sum(1 for probe in probed if probe.get("restarted"))
    if not observed and not restarts:
        return None
    single = [probe for probe in observed if probe["decisions"] == 1]
    methods = Counter(method for probe in single for method in probe.get("methods") or {})
    without_llm = [probe for probe in single if LLM_ROUTING_METHOD not in (probe.get("methods") or {})]
    return {
        "questions": len(observed),
        "mas_restarts": restarts,
        "decided_once": len(single),
        "without_decision": sum(1 for probe in observed if probe["decisions"] == 0),
        "several_decisions": sum(1 for probe in observed if probe["decisions"] > 1),
        "methods": dict(sorted(methods.items())),
        "llm_pct": round(100.0 * methods[LLM_ROUTING_METHOD] / len(single), 1) if single else None,
        "decision_s": stats([probe.get("seconds") for probe in single]),
        "decision_s_without_llm": stats([probe.get("seconds") for probe in without_llm]),
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
    summary["dispatch_s"] = stats([r.get("dispatch_s") for r in records])
    summary["routing"] = routing_summary(records)
    summary["llm"] = llm_summary(records)
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
    llama_server: dict[str, Any] | None = None,
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
        "llama_cpp": {"build": llama_cpp_build, "server": llama_server},
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
        self.docker_host_swap_peak: int | None = None

    def add(
        self,
        container_usage: dict[str, int],
        swap_used: int | None = None,
        docker_host_swap_used: int | None = None,
    ) -> None:
        self.samples += 1
        for name, used in container_usage.items():
            self.container_peaks[name] = max(used, self.container_peaks.get(name, 0))
        if container_usage:
            total = sum(container_usage.values())
            self.containers_sum_peak = max(total, self.containers_sum_peak or 0)
        if swap_used is not None:
            self.swap_peak = max(swap_used, self.swap_peak or 0)
        if docker_host_swap_used is not None:
            self.docker_host_swap_peak = max(docker_host_swap_used, self.docker_host_swap_peak or 0)

    def as_dict(self) -> dict[str, Any]:
        return {
            "samples": self.samples,
            "container_peak_mem_bytes": dict(sorted(self.container_peaks.items())),
            "containers_sum_peak_mem_bytes": self.containers_sum_peak,
            "swap_peak_used_bytes": self.swap_peak,
            "docker_host_swap_peak_used_bytes": self.docker_host_swap_peak,
        }

    def window_dict(self) -> dict[str, Any] | None:
        if not self.samples:
            return None
        return {
            "samples": self.samples,
            "containers_sum_peak_mem_bytes": self.containers_sum_peak,
            "swap_peak_used_bytes": self.swap_peak,
            "docker_host_swap_peak_used_bytes": self.docker_host_swap_peak,
        }


def questions_peak_checks(
    resources: dict[str, Any], at_start: dict[str, Any] | None, questions_swap_peak: int | None
) -> dict[str, Any]:
    if not at_start:
        return {
            "at_questions_start": None,
            "unsampled_peak_excess_bytes": None,
            "docker_host_swap_growth_bytes": None,
        }
    start_peaks = at_start.get("container_lifetime_peak_mem_bytes") or {}
    sampled = resources.get("container_peak_mem_bytes") or {}
    memory_stats = resources.get("container_memory_stat") or {}
    excess: dict[str, int | None] = {}
    for name, end_peak in (resources.get("container_lifetime_peak_mem_bytes") or {}).items():
        start_peak = start_peaks.get(name)
        if name not in sampled or end_peak is None or start_peak is None or end_peak <= start_peak:
            continue
        inactive_file = (memory_stats.get(name) or {}).get("inactive_file")
        if inactive_file is None:
            excess[name] = None
        elif end_peak - inactive_file > sampled[name]:
            excess[name] = end_peak - inactive_file - sampled[name]
    swap_at_start = at_start.get("docker_host_swap_used_bytes")
    swap_known = swap_at_start is not None and questions_swap_peak is not None
    return {
        "at_questions_start": at_start,
        "unsampled_peak_excess_bytes": dict(sorted(excess.items())),
        "docker_host_swap_growth_bytes": max(questions_swap_peak - swap_at_start, 0) if swap_known else None,
    }


def llm_mapped_outside_docker_stats(
    process: dict[str, Any] | None, memory_stat: dict[str, int] | None
) -> int | None:
    if not process or process.get("name") != LLM_PROCESS_NAME or process.get("rss_file_bytes") is None:
        return None
    if not memory_stat:
        return None
    counted_by_docker_stats = min(memory_stat["file_mapped"], memory_stat["active_file"])
    return max(process["rss_file_bytes"] - counted_by_docker_stats, 0)


def stack_peak_fields(resources: dict[str, Any], llm_container: str | None) -> dict[str, Any]:
    memory_stat = (resources.get("container_memory_stat") or {}).get(llm_container) if llm_container else None
    outside = llm_mapped_outside_docker_stats(resources.get("llm_process"), memory_stat)
    total = resources.get("containers_sum_peak_mem_bytes")
    return {
        "llm_mapped_outside_docker_stats_bytes": outside,
        "stack_peak_mem_bytes": None if total is None or outside is None else total + outside,
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
