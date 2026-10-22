from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

BENCH_DIR = Path(__file__).resolve().parent
REPO_ROOT = BENCH_DIR.parents[1]
EVAL_DIR = REPO_ROOT / "scripts" / "eval"
KIT_SRC = REPO_ROOT / "opensource" / "horus-bench-kit" / "src"
if str(KIT_SRC) not in sys.path:
    sys.path.insert(0, str(KIT_SRC))
if str(EVAL_DIR) not in sys.path:
    sys.path.insert(1, str(EVAL_DIR))

from horus_bench_kit.candidates import (  # noqa: E402
    NAME_COLUMNS,
    STEPS,
    CandidatesProfile,
    Column,
    MarkdownTexts,
    cgroup_peak,
    gib_text,
    median_cell,
    oom_kills_text,
    process_peak,
    rate_cell,
    reviewed_cell,
    section,
    speed_cell,
    thought_first_cell,
)
from horus_bench_kit.candidates import eval_headline as kit_eval_headline  # noqa: E402
from horus_bench_kit.cli.candidates import RunnerProfile  # noqa: E402
from horus_bench_kit.cli.llama_bench import LlamaBenchProfile  # noqa: E402
from horus_bench_kit.compare import (  # noqa: E402
    GIB,
    LLAMA_BENCH_ROWS,
    CompareProfile,
    Family,
    container_total,
    gib,
    llama_cpp_build,
    methods_text,
    run_started,
    stat_metric,
)
from horus_bench_kit.compare import eval_metrics as evaluation_metrics  # noqa: E402
from horus_bench_kit.llama_bench import KnownModel  # noqa: E402
from horus_bench_kit.markdown import Metric, MetricRow  # noqa: E402
from horus_bench_kit.shell import Shell  # noqa: E402
from horus_bench_kit.testset import CATEGORIES  # noqa: E402
from horus_eval_profile import (  # noqa: E402
    CONTRACT_PROFILE,
    DEFAULT_TESTSET_PATH,
    EVAL_KIND,
    EVAL_SCHEMA_VERSION,
)

DEFAULT_OUT_DIR = REPO_ROOT / "benchmarks"
DEFAULT_MODELS_DIR = REPO_ROOT / "models"
DEFAULT_CATALOG = BENCH_DIR / "model-candidates.yaml"
FETCH_SCRIPT = REPO_ROOT / "src" / "infra" / "llm" / "fetch-model.sh"
RUN_LLAMA_BENCH = BENCH_DIR / "run-llama-bench.py"
RUN_EVAL = EVAL_DIR / "run-eval.py"
PROBE_SCRIPT = EVAL_DIR / "agent-contract-probe.py"
INSTALLER_DIR = REPO_ROOT / "installer"
DEFAULT_REFERENCE = "cpu16"

BENCH_IMAGE = "ghcr.io/ggml-org/llama.cpp:full-b11382"
FETCH_IMAGE = "ghcr.io/ggml-org/llama.cpp:server-b11382"
CONTAINER_FETCH_SCRIPT = "/opt/horus/fetch-model.sh"
UNSLOTH_FILES_URL = (
    "https://huggingface.co/unsloth/Qwen3-4B-Instruct-2507-GGUF/resolve/"
    "a06e946bb6b655725eafa393f4a9745d460374c9"
)
KNOWN_MODELS = {
    model.file: model
    for model in (
        KnownModel(
            "qwen3-4b-instruct-2507-Q4_K_M.gguf",
            f"{UNSLOTH_FILES_URL}/Qwen3-4B-Instruct-2507-Q4_K_M.gguf",
            2_497_281_120,
            "3605803b982cb64aead44f6c1b2ae36e3acdb41d8e46c8a94c6533bc4c67e597",
        ),
        KnownModel(
            "qwen3-4b-instruct-2507-Q5_K_M.gguf",
            f"{UNSLOTH_FILES_URL}/Qwen3-4B-Instruct-2507-Q5_K_M.gguf",
            2_889_514_080,
            "5bde5e9d883622acb02bf77fe7dcbc56a8b9a9ad4be78a72ca23a532658b4ecb",
        ),
    )
}
DEFAULT_MODEL_FILES = tuple(KNOWN_MODELS)
STACK_CONTAINERS = ("llm", "mas", "agent", "knowledge_store", "vllm")
LLAMA_BENCH_HELP = {
    "--models-dir": "Host folder that holds the GGUF files.",
    "--models-volume": "Docker volume that holds the GGUF files.",
    "--model": "GGUF file name inside the models folder or volume; repeat for several.",
}


class HorusShell(Shell):
    start_errors = ()


LLAMA_BENCH = LlamaBenchProfile(
    prog=None,
    description="Run llama-bench in the pinned llama.cpp image and save the enriched result.",
    out_dir=str(DEFAULT_OUT_DIR),
    reference=DEFAULT_REFERENCE,
    bench_image=BENCH_IMAGE,
    fetch_image=FETCH_IMAGE,
    known_models=KNOWN_MODELS,
    fetch_script=FETCH_SCRIPT,
    container_fetch_script=CONTAINER_FETCH_SCRIPT,
    git_dir=REPO_ROOT,
    busy_containers=STACK_CONTAINERS,
    busy_warning="Horus containers are running ({names}) and compete for CPU and RAM",
    fetch_hint="pass --fetch to download the known models, see benchmarks/README.md",
    known_mismatch="{file} is not the unsloth file; record its SHA-256 with the result",
    option_help=LLAMA_BENCH_HELP,
    known_models_option=False,
    version_option=False,
    input_errors=(),
)

RECORDED_KIND = "horus-recorded"
RECORDED_SCHEMA_VERSION = 1
LLM_CONTAINER = "llm"
ROUTER = "MAS /metrics, B-92 router"
UNSAMPLED_PEAK_LIMIT_BYTES = GIB // 2
CONTAINER_COUNTS = (("container_oom_kills", "OOM kills"), ("container_restarts", "restart count"))
COMPARE_DESCRIPTION = "Print the dev plan's section 10 metrics table for one benchmark run, or the difference between two."
SECTION_10_ROWS = (
    *LLAMA_BENCH_ROWS,
    MetricRow("questions", "Questions", "test set items run", "count"),
    MetricRow("ttft_median_s", "Time to first token, median", "first streamed token", "s"),
    MetricRow("ttft_p90_s", "Time to first token, p90", "first streamed token", "s"),
    MetricRow("total_median_s", "Total time, median", "submit to final answer", "s"),
    MetricRow("total_p90_s", "Total time, p90", "submit to final answer", "s"),
    MetricRow("total_sum_s", "Total time, whole run", "sum over the questions", "s", is_total=True),
    MetricRow(
        "llm_prompt_median_s", "Prompt reading per question, median", "llama-server /metrics", "s"
    ),
    MetricRow(
        "llm_generation_tps", "Generation speed in the stack", "llama-server /metrics", "t/s"
    ),
    MetricRow("routing_decision_median_ms", "Routing decision, median", ROUTER, "ms"),
    MetricRow(
        "routing_decision_without_llm_p90_ms", "Routing decision without the LLM, p90", ROUTER, "ms"
    ),
    MetricRow("routing_llm_pct", "Routed by the LLM fallback", ROUTER, "%"),
    MetricRow("routing_methods", "Routing methods", ROUTER, "text"),
    MetricRow(
        "dispatch_median_ms", "Submit to dispatch, median", "task events, queue wait included", "ms"
    ),
    MetricRow(
        "stack_peak_gib",
        "Peak RAM of the stack (ADR-006 P)",
        "docker stats total + model pages left out, in one sample",
        "GiB",
    ),
    MetricRow("peak_ram_gib", "Peak RAM, all containers at once", "docker stats samples", "GiB"),
    MetricRow(
        "llm_mapped_outside_gib",
        "Model pages docker stats left out",
        "llama-server RssFile, memory.stat, in the sample of P",
        "GiB",
    ),
    MetricRow("peak_ram_llm_gib", "Peak RAM, llm container", "docker stats", "GiB"),
    MetricRow(
        "lifetime_peak_llm_gib", "Peak RAM, llm, since it started", "cgroup memory.peak", "GiB"
    ),
    MetricRow("oom_kills", "Out-of-memory kills", "cgroup memory.events", "count"),
    MetricRow("restarts", "Container restarts", "docker inspect", "count"),
    MetricRow("swap_peak_gib", "Peak swap used", "Docker host /proc/meminfo", "GiB"),
    MetricRow(
        "swap_growth_gib", "Swap growth during the questions", "Docker host /proc/meminfo", "GiB"
    ),
    MetricRow(
        "install_min", "Install time without the model", "clean VM (not in these files)", "min"
    ),
    MetricRow("peak_disk_gb", "Peak disk during install", "clean VM (not in these files)", "GB"),
    MetricRow("answer_correct_reviewed_pct", "Answer correct, two reviewers", "manual review", "%"),
    MetricRow("answer_correct_auto_pct", "Answer correct, automatic", "answer patterns", "%"),
    MetricRow("source_correct_auto_pct", "Source correct", "expected document", "%"),
    MetricRow("fallbacks", "Canned fallback answers", "spiral, timeout, watchdog", "count"),
    MetricRow("kv_cache", "KV cache K/V (q8_0 quality check)", "llama-server arguments", "text"),
)


def eval_metrics(report: dict[str, Any]) -> dict[str, Metric]:
    summary = report.get("summary") or {}
    resources = report.get("resources") or {}
    llm = summary.get("llm") or {}
    routing = summary.get("routing") or {}
    peaks = resources.get("container_peak_mem_bytes") or {}
    lifetime = resources.get("container_lifetime_peak_mem_bytes") or {}
    swap = resources.get("docker_host_swap_peak_used_bytes")
    if swap is None:
        swap = resources.get("swap_peak_used_bytes")
    metrics = {
        **evaluation_metrics(report),
        "llm_prompt_median_s": stat_metric(llm, "prompt_s", "median"),
        "llm_generation_tps": Metric(llm.get("generation_tps"), llm.get("questions")),
        "routing_decision_median_ms": stat_metric(routing, "decision_s", "median", 1000.0),
        "routing_decision_without_llm_p90_ms": stat_metric(
            routing, "decision_s_without_llm", "p90", 1000.0
        ),
        "routing_llm_pct": Metric(routing.get("llm_pct"), routing.get("decided_once")),
        "routing_methods": Metric(methods_text(routing.get("methods"))),
        "dispatch_median_ms": stat_metric(summary, "dispatch_s", "median", 1000.0),
        "stack_peak_gib": Metric(gib(resources.get("stack_peak_mem_bytes"))),
        "peak_ram_gib": Metric(gib(resources.get("containers_sum_peak_mem_bytes"))),
        "llm_mapped_outside_gib": Metric(
            gib(resources.get("llm_mapped_outside_docker_stats_bytes"))
        ),
        "peak_ram_llm_gib": Metric(gib(peaks.get(LLM_CONTAINER))),
        "lifetime_peak_llm_gib": Metric(gib(lifetime.get(LLM_CONTAINER))),
        "oom_kills": Metric(container_total(resources.get("container_oom_kills"))),
        "restarts": Metric(container_total(resources.get("container_restarts"))),
        "swap_peak_gib": Metric(gib(swap)),
        "swap_growth_gib": Metric(gib(resources.get("docker_host_swap_growth_bytes"))),
    }
    settings = ((report.get("llama_cpp") or {}).get("server") or {}).get("settings") or {}
    if settings:
        metrics["kv_cache"] = Metric(
            f"{settings.get('cache_type_k')}/{settings.get('cache_type_v')}"
        )
    return metrics


def recorded_metrics(document: dict[str, Any]) -> dict[str, Metric]:
    return {
        key: Metric(entry.get("value"), entry.get("n"), entry.get("note"))
        for key, entry in (document.get("metrics") or {}).items()
        if isinstance(entry, dict)
    }


def sampling_warnings(doc: dict[str, Any]) -> list[str]:
    excess = (doc.get("resources") or {}).get("unsampled_peak_excess_bytes") or {}
    warnings = []
    unchecked = sorted(name for name, over in excess.items() if over is None)
    if unchecked:
        warnings.append(
            f"{doc.get('label')}: no sampling check for {', '.join(unchecked)}: a memory.peak or memory.stat "
            "could not be read (memory.peak needs cgroup v2 and Linux 5.19 or later), so a spike between two "
            "samples cannot be ruled out."
        )
    for name, over in sorted(excess.items()):
        if over is not None and over > UNSAMPLED_PEAK_LIMIT_BYTES:
            warnings.append(
                f"{doc.get('label')}: the memory.peak of {name}, less its inactive page cache, went "
                f"{gib(over):.2f} GiB above its docker stats peak during the questions: a spike fell between "
                "two samples. Repeat the run with --sample-interval 2 before taking ADR-006's P from it."
            )
    return warnings


def stack_peak_warnings(doc: dict[str, Any]) -> list[str]:
    resources = doc.get("resources")
    missing = resources.get("samples_without_llm_pages") if isinstance(resources, dict) else None
    if not missing:
        return []
    unread = (
        f"{doc.get('label')}: llama-server's RssFile or the llm memory.stat could not be read in"
    )
    if resources.get("stack_peak_mem_bytes") is None:
        return [
            f"{unread} any of the {missing} samples taken while llm ran, so ADR-006's P is unknown: "
            "fix the read and run again."
        ]
    return [f"{unread} {missing} samples: ADR-006's P leaves them out."]


def unread_count_warnings(doc: dict[str, Any]) -> list[str]:
    resources = doc.get("resources")
    if not isinstance(resources, dict):
        return []
    warnings = []
    for field_name, what in CONTAINER_COUNTS:
        values = resources.get(field_name) or {}
        unread = sorted(name for name, value in values.items() if value is None)
        if unread or not values:
            names = ", ".join(unread) or "every container"
            warnings.append(
                f"{doc.get('label')}: the {what} of {names} could not be read, so its row stays empty."
            )
    return warnings


def eval_warnings(doc: dict[str, Any]) -> list[str]:
    warnings = []
    if (doc.get("run") or {}).get("completed") is False:
        warnings.append(f"{doc.get('label')}: the run did not complete.")
    warnings += sampling_warnings(doc) + stack_peak_warnings(doc) + unread_count_warnings(doc)
    pending = ((doc.get("summary") or {}).get("manual_review") or {}).get("pending")
    if pending:
        warnings.append(f"{doc.get('label')}: {pending} answers still wait for the two reviewers.")
    return warnings


def recorded_warnings(doc: dict[str, Any]) -> list[str]:
    sources = ", ".join((doc.get("recorded") or {}).get("sources") or [])
    return [f"{doc.get('label')} is a recorded result ({sources}), not a run of the test set."]


def recorded_build(doc: dict[str, Any]) -> Any:
    return llama_cpp_build(doc) or (doc.get("recorded") or {}).get("runtime")


def recorded_started(doc: dict[str, Any]) -> Any:
    return run_started(doc) or (doc.get("recorded") or {}).get("date")


COMPARE = CompareProfile(
    rows=SECTION_10_ROWS,
    families=(
        Family(EVAL_KIND, EVAL_SCHEMA_VERSION, eval_metrics, eval_warnings),
        Family(
            RECORDED_KIND,
            RECORDED_SCHEMA_VERSION,
            recorded_metrics,
            recorded_warnings,
            build=recorded_build,
            started=recorded_started,
        ),
    ),
    heading="## Section 10 metrics",
)

CANDIDATE_CONTAINER = "llm-candidate"
STACK_LLM_CONTAINER = "llm"
AGENT_CONTAINER = "agent"
LLM_NETWORK_ALIAS = "llm"
NETWORK_SUFFIX = "horus-net"
RESPONSE_CACHE_SETTING = "AGENT_RESPONSE_CACHE"
ENABLED_SETTING_VALUES = frozenset({"1", "true", "yes", "on"})
PROBE_TARGET = "/tmp/horus-agent-contract-probe.py"
AGENT_WORKDIR = "/app"
DOWNLOAD_LOG = "model-candidates-download.log"
CONTRACT_HEADLINE_KEYS = (
    "replies",
    "json_valid",
    "failures",
    "thought_first",
    "truncated",
    "blank_answers",
    "status_correct",
    "answer_correct_auto",
    "source_correct_auto",
    "wall_s",
    "completion_tokens",
    "prompt_tps",
    "generation_tps",
)


def setting_enabled(value: str | None) -> bool:
    return str(value or "").strip().lower() in ENABLED_SETTING_VALUES


def response_cache_finding(env: dict[str, str] | None, container: str) -> str | None:
    if env is None:
        return f"could not read the environment of the {container!r} container to see whether its response cache is off"
    value = env.get(RESPONSE_CACHE_SETTING)
    if not setting_enabled(value):
        return None
    return (
        f"the agent's response cache is on ({RESPONSE_CACHE_SETTING}={value}): its key does not change with the "
        "model, so the evaluation could score answers cached for another model"
    )


def eval_headline(
    eval_report: dict[str, Any] | None, container: str = CANDIDATE_CONTAINER
) -> dict[str, Any] | None:
    headline = kit_eval_headline(eval_report)
    if headline is None:
        return None
    summary = eval_report.get("summary") or {}
    resources = eval_report.get("resources") or {}
    llm = summary.get("llm") or {}

    def per_container(name: str) -> Any:
        values = resources.get(name)
        return values.get(container) if isinstance(values, dict) else None

    return {
        **headline,
        "llm_prompt_tps": llm.get("prompt_tps"),
        "llm_generation_tps": llm.get("generation_tps"),
        "stack_peak_mem_bytes": resources.get("stack_peak_mem_bytes"),
        "containers_sum_peak_mem_bytes": resources.get("containers_sum_peak_mem_bytes"),
        "llm_peak_mem_bytes": per_container("container_peak_mem_bytes"),
        "llm_lifetime_peak_mem_bytes": per_container("container_lifetime_peak_mem_bytes"),
        "llm_oom_kills": per_container("container_oom_kills"),
        "docker_host_swap_growth_bytes": resources.get("docker_host_swap_growth_bytes"),
    }


CANDIDATES_TEXTS = MarkdownTexts(
    quality_intro=(
        "JSON valid: replies to the B-98 request that parse and validate against the schema sent. "
        "Probe columns come from the direct contract probe, chat columns from {evaluation}."
    ),
    quality_columns=(
        *NAME_COLUMNS,
        Column("Licence", lambda variant: variant["licence"], "---"),
        Column("JSON valid", rate_cell("contract", "json_valid")),
        Column("Thought first", thought_first_cell),
        Column("Status correct", rate_cell("contract", "status_correct")),
        Column("Answer correct (probe)", rate_cell("contract", "answer_correct_auto")),
        Column("Source correct (probe)", rate_cell("contract", "source_correct_auto")),
        Column("Answer correct (chat, auto)", rate_cell("eval", "answer_correct_auto")),
        Column("Answer correct (reviewed)", reviewed_cell),
        Column("Source correct (chat)", rate_cell("eval", "source_correct_auto")),
    ),
    speed_intro=(
        "llama-bench tokens per second with an f16 KV cache, best thread count, depth 0 unless named. "
        "Medians in seconds. llm VmHWM and cgroup peak: the candidate llama-server; stack peak: the evaluation's "
        "`stack_peak_mem_bytes`, the ADR-006 `P`: the peak memory of the whole stack, model pages included."
    ),
    speed_columns=(
        *NAME_COLUMNS,
        Column("File", lambda variant: gib_text(variant["size_bytes"])),
        Column("pp512", speed_cell("pp512")),
        Column("pp2048", speed_cell("pp2048")),
        Column("tg128", speed_cell("tg128")),
        Column("tg128 @ 4096", speed_cell("tg128", 4096)),
        Column("Probe reply", median_cell("contract", "wall_s")),
        Column("Chat answer", median_cell("eval", "total_s")),
        Column("Chat first token", median_cell("eval", "ttft_s")),
        Column("llm VmHWM", lambda variant: gib_text(process_peak(variant))),
        Column("llm cgroup peak", lambda variant: gib_text(cgroup_peak(variant))),
        Column(
            "Stack peak",
            lambda variant: gib_text(section(variant, "eval").get("stack_peak_mem_bytes")),
        ),
        Column("OOM kills", oom_kills_text),
    ),
)

CANDIDATES = CandidatesProfile(
    contract_keys=CONTRACT_HEADLINE_KEYS,
    eval_headline=eval_headline,
    gate_build="needs llama.cpp b{since}, the stack pins b{pinned}",
    markdown=CANDIDATES_TEXTS,
    name_key="plan_name",
)
RUNNER_HELP = {
    "--only": "Candidate or GGUF ids, comma-separated.",
    "--all-quants": "Also the GGUFs that are not defaults.",
    "--steps": "Among fetch,bench,probe,eval.",
    "--llm-mem-limit": "Memory limit of the candidate llama-server, e.g. 6g.",
    "--server-image": "Default: the catalog's pinned server image.",
    "--bench-arg": "Extra run-llama-bench.py argument.",
    "--eval-arg": "Extra run-eval.py argument.",
    "--resume": "Run more steps into an earlier summary.",
}

RUNNER = RunnerProfile(
    prog=None,
    description="Benchmark the B-102 model candidates against the Qwen3-4B baseline: "
    "download and verify each GGUF, run llama-bench, probe the B-98 answer contract and run "
    "the 100-question evaluation with that model behind the CPU stack's llama-server.",
    summary=CANDIDATES,
    contract=CONTRACT_PROFILE,
    catalog=str(DEFAULT_CATALOG),
    models_dir=str(DEFAULT_MODELS_DIR),
    out_dir=str(DEFAULT_OUT_DIR),
    reference=DEFAULT_REFERENCE,
    testset=str(DEFAULT_TESTSET_PATH),
    steps=STEPS,
    categories=CATEGORIES,
    base_dir=REPO_ROOT,
    git_dir=REPO_ROOT,
    candidate_container=CANDIDATE_CONTAINER,
    fetch_script=FETCH_SCRIPT,
    container_fetch_script=CONTAINER_FETCH_SCRIPT,
    option_help=RUNNER_HELP,
    version_option=False,
    input_errors=(),
)
