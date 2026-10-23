from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

KIT_SRC = Path(__file__).resolve().parents[2] / "opensource" / "horus-bench-kit" / "src"
if str(KIT_SRC) not in sys.path:
    sys.path.insert(0, str(KIT_SRC))

from eval_stack import LLM_PROCESS_NAME  # noqa: E402
from horus_bench_kit import report as kit  # noqa: E402
from horus_bench_kit.report import (  # noqa: E402, F401
    COMPLETE_TIMING_SOURCES,
    REVIEWER_SLOTS,
    blank_review,
    manual_review_summary,
    rank_summary,
)
from horus_bench_kit.stats import rate, stats  # noqa: E402, F401
from horus_eval_profile import EVAL_KIND as REPORT_KIND  # noqa: E402, F401
from horus_eval_profile import (  # noqa: E402, F401
    EVAL_PROFILE,
    OUTCOME_FIELDS,
    llm_summary,
    routing_summary,
)
from horus_eval_profile import EVAL_SCHEMA_VERSION as SCHEMA_VERSION  # noqa: E402, F401

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


def question_record(item: dict[str, Any], outcome: dict[str, Any]) -> dict[str, Any]:
    return kit.question_record(item, outcome, EVAL_PROFILE)


def build_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    return kit.build_summary(records, EVAL_PROFILE)


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
    sections = {
        "llama_cpp": {"build": llama_cpp_build, "server": llama_server},
        "model": {"name": None, "file": None, "sha256": None, **(model or {})},
        "machine": machine or {},
        "resources": resources,
    }
    return kit.build_report(
        label=label,
        run=run,
        testset=testset,
        records=records,
        sections=sections,
        profile=EVAL_PROFILE,
    )


def resummarize(report: dict[str, Any]) -> dict[str, Any]:
    return kit.resummarize(report, EVAL_PROFILE)


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
        self.stack_peak: int | None = None
        self.llm_mapped_outside_at_stack_peak: int | None = None
        self.samples_without_llm_pages = 0
        self.swap_peak: int | None = None
        self.docker_host_swap_peak: int | None = None

    def add(
        self,
        container_usage: dict[str, int],
        swap_used: int | None = None,
        docker_host_swap_used: int | None = None,
        llm_container: str | None = None,
        llm_mapped_outside: int | None = None,
    ) -> None:
        self.samples += 1
        for name, used in container_usage.items():
            self.container_peaks[name] = max(used, self.container_peaks.get(name, 0))
        if container_usage:
            total = sum(container_usage.values())
            self.containers_sum_peak = max(total, self.containers_sum_peak or 0)
            if llm_container in container_usage:
                self._add_stack_total(total, llm_mapped_outside)
        if swap_used is not None:
            self.swap_peak = max(swap_used, self.swap_peak or 0)
        if docker_host_swap_used is not None:
            self.docker_host_swap_peak = max(docker_host_swap_used, self.docker_host_swap_peak or 0)

    def _add_stack_total(self, containers_total: int, llm_mapped_outside: int | None) -> None:
        if llm_mapped_outside is None:
            self.samples_without_llm_pages += 1
        elif self.stack_peak is None or containers_total + llm_mapped_outside > self.stack_peak:
            self.stack_peak = containers_total + llm_mapped_outside
            self.llm_mapped_outside_at_stack_peak = llm_mapped_outside

    def as_dict(self) -> dict[str, Any]:
        return {
            "samples": self.samples,
            "container_peak_mem_bytes": dict(sorted(self.container_peaks.items())),
            "containers_sum_peak_mem_bytes": self.containers_sum_peak,
            "llm_mapped_outside_docker_stats_bytes": self.llm_mapped_outside_at_stack_peak,
            "stack_peak_mem_bytes": self.stack_peak,
            "samples_without_llm_pages": self.samples_without_llm_pages,
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
        if name not in sampled:
            continue
        if end_peak is None or start_peak is None:
            excess[name] = None
            continue
        if end_peak <= start_peak:
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
        "docker_host_swap_growth_bytes": max(questions_swap_peak - swap_at_start, 0)
        if swap_known
        else None,
    }


def llm_mapped_outside_docker_stats(
    process: dict[str, Any] | None, memory_stat: dict[str, int] | None
) -> int | None:
    if (
        not process
        or process.get("name") != LLM_PROCESS_NAME
        or process.get("rss_file_bytes") is None
    ):
        return None
    if not memory_stat:
        return None
    counted_by_docker_stats = min(memory_stat["file_mapped"], memory_stat["active_file"])
    return max(process["rss_file_bytes"] - counted_by_docker_stats, 0)


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
