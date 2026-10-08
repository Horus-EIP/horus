from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
KIT_SRC = REPO_ROOT / "opensource" / "horus-bench-kit" / "src"
if str(KIT_SRC) not in sys.path:
    sys.path.insert(0, str(KIT_SRC))

from eval_stack import LLM_ROUTING_METHOD  # noqa: E402
from horus_bench_kit import scoring  # noqa: E402
from horus_bench_kit.contract import FAILURE_RETRIEVAL, check_reply  # noqa: E402
from horus_bench_kit.probe import ContractProfile  # noqa: E402
from horus_bench_kit.report import Profile, field_stats  # noqa: E402
from horus_bench_kit.stats import stats  # noqa: E402
from horus_bench_kit.testset import CATEGORIES  # noqa: E402

DEFAULT_TESTSET_PATH = REPO_ROOT / "tests" / "eval" / "testset.yaml"
WARMUP_QUESTION = "In one sentence, what kinds of documents are in the knowledge store?"
FALLBACK_MARKERS = {
    "spiral": "couldn't extract a consistent answer from the retrieved",
    "timeout": "took too long to respond",
    "task_timeout": "exceeded the maximum processing time",
}
STOPPED_BY_WATCHDOG = "stopped by the MAS TASK_TIMEOUT watchdog"
CANNED_NON_ANSWERS = (
    "The retrieved content does not contain this information.",
    "I don't have that information yet.",
)

EVAL_KIND = "horus-eval"
EVAL_SCHEMA_VERSION = 2
OUTCOME_FIELDS = (
    "conversation_id",
    "task_id",
    "observed_route",
    "answered_by",
    "models",
    "devices",
    "timing_source",
    "submit_http_s",
    "first_event_s",
    "dispatch_s",
    "routing_decision",
    "retrieval_s",
    "reasoning_start_s",
    "ttft_s",
    "total_s",
    "llm",
    "resources",
)

CONTRACT_KIND = "horus-contract-probe"
CONTRACT_SCHEMA_VERSION = 1
PROBED_CATEGORIES = ("lookup", "numeric", "multi_hop", "not_in_corpus")
CONTRACT_RATE_FIELDS = ("json_valid", "status_correct", "answer_correct_auto", "source_correct_auto")
STATUS_OK = "ok"
STATUS_NOT_FOUND = "not_found"
ERROR_STAGE_RETRIEVAL = "retrieval"
ERROR_STAGE_LLM = "llm"


def detect_fallback(answer: str | None) -> str | None:
    return scoring.detect_fallback(answer, FALLBACK_MARKERS)


def answer_correct(item: dict[str, Any], answer: str | None) -> bool:
    return scoring.answer_correct(item, answer, FALLBACK_MARKERS)


def final_status(status: str, error: str | None, answer: str | None) -> tuple[str, str | None]:
    if status == "ok" and detect_fallback(answer) == "task_timeout":
        return "timeout", error or STOPPED_BY_WATCHDOG
    return status, error


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


EVAL_PROFILE = Profile(
    kind=EVAL_KIND,
    schema_version=EVAL_SCHEMA_VERSION,
    fallback_markers=FALLBACK_MARKERS,
    final_status=final_status,
    outcome_fields=OUTCOME_FIELDS,
    summary_sections=(
        ("dispatch_s", field_stats("dispatch_s")),
        ("routing", routing_summary),
        ("llm", llm_summary),
    ),
    categories=CATEGORIES,
)


def expected_status(item: dict[str, Any]) -> str:
    return STATUS_NOT_FOUND if item["category"] == "not_in_corpus" else STATUS_OK


def expected_status_head(item: dict[str, Any]) -> dict[str, Any]:
    return {"expected_status": expected_status(item)}


def cited_titles(data: dict[str, Any] | None, sources_by_label: dict[str, Any] | None) -> list[str]:
    cited = (data or {}).get("sources")
    known = sources_by_label or {}
    titles: list[str] = []
    for label in cited if isinstance(cited, list) else []:
        source = known.get(label) if isinstance(label, str) else None
        title = source.get("title") if isinstance(source, dict) else None
        if isinstance(title, str) and title and title not in titles:
            titles.append(title)
    return titles


def contract_scores(item: dict[str, Any], reply: dict[str, Any]) -> dict[str, Any]:
    if reply.get("error_stage") == ERROR_STAGE_RETRIEVAL:
        return {
            "json_valid": None,
            "failure": FAILURE_RETRIEVAL,
            "violations": [],
            "status": None,
            "status_correct": None,
            "answer": None,
            "blank_answer": False,
            "answer_correct_auto": None,
            "cited_sources": [],
            "source_correct_auto": None,
        }
    data, failure, violations = check_reply(reply)
    valid = failure is None
    status = data.get("status") if valid else None
    answer = data.get("answer") if valid else None
    titles = cited_titles(data if valid else None, reply.get("sources_by_label"))
    in_corpus = item["category"] != "not_in_corpus"
    return {
        "json_valid": valid,
        "failure": failure,
        "violations": violations,
        "status": status,
        "status_correct": status == expected_status(item),
        "answer": answer,
        "blank_answer": valid and not str(answer or "").strip(),
        "answer_correct_auto": answer_correct(item, answer) if valid else False,
        "cited_sources": titles,
        "source_correct_auto": scoring.source_check(item, cited_sources=titles)["source_correct_auto"]
        if in_corpus
        else None,
    }


def blank_answer_count(records: list[dict[str, Any]]) -> dict[str, Any]:
    return {"blank_answers": sum(1 for r in records if r["blank_answer"])}


CONTRACT_PROFILE = ContractProfile(
    kind=CONTRACT_KIND,
    schema_version=CONTRACT_SCHEMA_VERSION,
    head=expected_status_head,
    scores=contract_scores,
    rate_fields=CONTRACT_RATE_FIELDS,
    counts=blank_answer_count,
    categories=CATEGORIES,
)
