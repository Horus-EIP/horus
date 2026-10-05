from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from bench_llama import REPORT_KIND as LLAMA_BENCH_KIND
from bench_llama import summary_rows

EVAL_KIND = "horus-eval"
RECORDED_KIND = "horus-recorded"
RAW_LLAMA_BENCH_KIND = "llama-bench"
BENCH_KINDS = frozenset({LLAMA_BENCH_KIND, RAW_LLAMA_BENCH_KIND})
END_TO_END_KINDS = frozenset({EVAL_KIND, RECORDED_KIND})
GIB = 1024**3
LLM_CONTAINER = "llm"
ROUTER = "MAS /metrics, B-92 router"
UNSAMPLED_PEAK_LIMIT_BYTES = GIB // 2
HEADLINE_TESTS = (
    ("pp512", 0),
    ("pp2048", 0),
    ("tg128", 0),
    ("pp512", 4096),
    ("pp2048", 4096),
    ("tg128", 4096),
)
EMPTY = "—"
DECIMALS = {"t/s": 1, "s": 1, "ms": 0, "GiB": 2, "%": 1, "min": 1, "GB": 1}
SMALL_VALUE_UNITS = frozenset({"t/s", "s"})
UNITLESS = frozenset({"count", "text"})


@dataclass(frozen=True)
class Metric:
    value: Any
    n: int | None = None
    note: str | None = None


@dataclass(frozen=True)
class MetricRow:
    key: str
    label: str
    how: str
    unit: str
    is_total: bool = False


@dataclass(frozen=True)
class BenchSelection:
    model: str | None = None
    threads: int | None = None
    cache_type: str = "f16"


@dataclass
class Side:
    name: str
    documents: list[dict[str, Any]]
    metrics: dict[str, Metric] = field(default_factory=dict)
    bench: list[dict[str, Any]] = field(default_factory=list)
    bench_choice: str | None = None

    def first(self, kinds: frozenset[str]) -> dict[str, Any] | None:
        return next((doc for doc in self.documents if doc.get("kind") in kinds), None)

    @property
    def end_to_end(self) -> dict[str, Any] | None:
        return self.first(END_TO_END_KINDS)

    @property
    def machine(self) -> dict[str, Any]:
        for doc in (self.end_to_end, self.first(BENCH_KINDS)):
            if doc and doc.get("machine"):
                return doc["machine"]
        return {}

    @property
    def label(self) -> str:
        return " + ".join(str(doc.get("label") or Path(doc["path"]).stem) for doc in self.documents)


def headline_key(test: str, depth: int) -> str:
    return f"{test}@d{depth}" if depth else test


SECTION_10_ROWS = (
    MetricRow("pp512", "Prompt processing pp512", "llama-bench", "t/s"),
    MetricRow("pp2048", "Prompt processing pp2048", "llama-bench", "t/s"),
    MetricRow("tg128", "Generation tg128", "llama-bench", "t/s"),
    MetricRow("pp512@d4096", "Prompt processing pp512, depth 4096", "llama-bench", "t/s"),
    MetricRow("pp2048@d4096", "Prompt processing pp2048, depth 4096", "llama-bench", "t/s"),
    MetricRow("tg128@d4096", "Generation tg128, depth 4096", "llama-bench", "t/s"),
    MetricRow("questions", "Questions", "test set items run", "count"),
    MetricRow("ttft_median_s", "Time to first token, median", "first streamed token", "s"),
    MetricRow("ttft_p90_s", "Time to first token, p90", "first streamed token", "s"),
    MetricRow("total_median_s", "Total time, median", "submit to final answer", "s"),
    MetricRow("total_p90_s", "Total time, p90", "submit to final answer", "s"),
    MetricRow("total_sum_s", "Total time, whole run", "sum over the questions", "s", is_total=True),
    MetricRow("llm_prompt_median_s", "Prompt reading per question, median", "llama-server /metrics", "s"),
    MetricRow("llm_generation_tps", "Generation speed in the stack", "llama-server /metrics", "t/s"),
    MetricRow("routing_decision_median_ms", "Routing decision, median", ROUTER, "ms"),
    MetricRow("routing_decision_without_llm_p90_ms", "Routing decision without the LLM, p90", ROUTER, "ms"),
    MetricRow("routing_llm_pct", "Routed by the LLM fallback", ROUTER, "%"),
    MetricRow("routing_methods", "Routing methods", ROUTER, "text"),
    MetricRow("dispatch_median_ms", "Submit to dispatch, median", "task events, queue wait included", "ms"),
    MetricRow("peak_ram_gib", "Peak RAM, all containers at once", "docker stats samples (ADR-005 P)", "GiB"),
    MetricRow("peak_ram_llm_gib", "Peak RAM, llm container", "docker stats", "GiB"),
    MetricRow("lifetime_peak_llm_gib", "Peak RAM, llm, since it started", "cgroup memory.peak", "GiB"),
    MetricRow("oom_kills", "Out-of-memory kills", "cgroup memory.events", "count"),
    MetricRow("restarts", "Container restarts", "docker inspect", "count"),
    MetricRow("swap_peak_gib", "Peak swap used", "Docker host /proc/meminfo", "GiB"),
    MetricRow("swap_growth_gib", "Swap growth during the questions", "Docker host /proc/meminfo", "GiB"),
    MetricRow("install_min", "Install time without the model", "clean VM (not in these files)", "min"),
    MetricRow("peak_disk_gb", "Peak disk during install", "clean VM (not in these files)", "GB"),
    MetricRow("answer_correct_reviewed_pct", "Answer correct, two reviewers", "manual review", "%"),
    MetricRow("answer_correct_auto_pct", "Answer correct, automatic", "answer patterns", "%"),
    MetricRow("source_correct_auto_pct", "Source correct", "expected document", "%"),
    MetricRow("fallbacks", "Canned fallback answers", "spiral, timeout, watchdog", "count"),
    MetricRow("kv_cache", "KV cache K/V (q8_0 quality check)", "llama-server arguments", "text"),
)


def load_document(path: Path | str) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, list):
        return {"kind": RAW_LLAMA_BENCH_KIND, "label": Path(path).stem, "results": data, "path": str(path)}
    kind = data.get("kind") if isinstance(data, dict) else None
    if kind not in BENCH_KINDS | END_TO_END_KINDS:
        raise ValueError(f"{path}: not a benchmark file (kind={kind!r})")
    return {**data, "path": str(path)}


def _gib(value: Any) -> float | None:
    return round(value / GIB, 2) if isinstance(value, (int, float)) else None


def _stat(block: dict[str, Any], field_name: str, statistic: str, scale: float = 1.0) -> Metric:
    values = block.get(field_name) or {}
    value = values.get(statistic)
    scaled = round(value * scale, 3) if isinstance(value, (int, float)) else None
    return Metric(scaled, values.get("n"))


def _rate(block: dict[str, Any] | None) -> Metric:
    block = block or {}
    return Metric(block.get("pct"), block.get("n"))


def _total(values: Any) -> int | None:
    return sum(values.values()) if isinstance(values, dict) else None


def _methods_text(methods: Any) -> str | None:
    if not isinstance(methods, dict) or not methods:
        return None
    return ", ".join(f"{method} {count}" for method, count in sorted(methods.items()))


def eval_metrics(report: dict[str, Any]) -> dict[str, Metric]:
    summary = report.get("summary") or {}
    resources = report.get("resources") or {}
    llm = summary.get("llm") or {}
    routing = summary.get("routing") or {}
    review = summary.get("manual_review") or {}
    peaks = resources.get("container_peak_mem_bytes") or {}
    lifetime = resources.get("container_lifetime_peak_mem_bytes") or {}
    swap = resources.get("docker_host_swap_peak_used_bytes")
    if swap is None:
        swap = resources.get("swap_peak_used_bytes")
    metrics = {
        "questions": Metric(summary.get("questions")),
        "ttft_median_s": _stat(summary, "ttft_s", "median"),
        "ttft_p90_s": _stat(summary, "ttft_s", "p90"),
        "total_median_s": _stat(summary, "total_s", "median"),
        "total_p90_s": _stat(summary, "total_s", "p90"),
        "total_sum_s": _stat(summary, "total_s", "sum"),
        "llm_prompt_median_s": _stat(llm, "prompt_s", "median"),
        "llm_generation_tps": Metric(llm.get("generation_tps"), llm.get("questions")),
        "routing_decision_median_ms": _stat(routing, "decision_s", "median", 1000.0),
        "routing_decision_without_llm_p90_ms": _stat(routing, "decision_s_without_llm", "p90", 1000.0),
        "routing_llm_pct": Metric(routing.get("llm_pct"), routing.get("decided_once")),
        "routing_methods": Metric(_methods_text(routing.get("methods"))),
        "dispatch_median_ms": _stat(summary, "dispatch_s", "median", 1000.0),
        "peak_ram_gib": Metric(_gib(resources.get("containers_sum_peak_mem_bytes"))),
        "peak_ram_llm_gib": Metric(_gib(peaks.get(LLM_CONTAINER))),
        "lifetime_peak_llm_gib": Metric(_gib(lifetime.get(LLM_CONTAINER))),
        "oom_kills": Metric(_total(resources.get("container_oom_kills"))),
        "restarts": Metric(_total(resources.get("container_restarts"))),
        "swap_peak_gib": Metric(_gib(swap)),
        "swap_growth_gib": Metric(_gib(resources.get("docker_host_swap_growth_bytes"))),
        "answer_correct_reviewed_pct": Metric(review.get("answer_correct_pct"), review.get("reviewed")),
        "answer_correct_auto_pct": _rate(summary.get("answer_correct_auto")),
        "source_correct_auto_pct": _rate(summary.get("source_correct_auto")),
        "fallbacks": Metric(_total(summary.get("fallbacks")), summary.get("questions")),
    }
    settings = ((report.get("llama_cpp") or {}).get("server") or {}).get("settings") or {}
    if settings:
        metrics["kv_cache"] = Metric(f"{settings.get('cache_type_k')}/{settings.get('cache_type_v')}")
    return metrics


def recorded_metrics(document: dict[str, Any]) -> dict[str, Metric]:
    return {
        key: Metric(entry.get("value"), entry.get("n"), entry.get("note"))
        for key, entry in (document.get("metrics") or {}).items()
        if isinstance(entry, dict)
    }


def choose_model(rows: list[dict[str, Any]], wanted: str | None) -> str | None:
    models = list(dict.fromkeys(row["model"] for row in rows if row["model"]))
    if wanted:
        return next((model for model in models if wanted.lower() in model.lower()), None)
    return models[0] if models else None


def bench_metrics(rows: list[dict[str, Any]], selection: BenchSelection) -> tuple[dict[str, Metric], str]:
    model = choose_model(rows, selection.model)
    chosen = [
        row
        for row in rows
        if row["model"] == model
        and row["type_k"] == selection.cache_type
        and row["type_v"] == selection.cache_type
        and (selection.threads is None or str(row["n_threads"]) == str(selection.threads))
        and row["avg_ts"] is not None
    ]
    metrics = {}
    for test, depth in HEADLINE_TESTS:
        candidates = [row for row in chosen if row["test"] == test and row["n_depth"] == depth]
        if candidates:
            best = max(candidates, key=lambda row: row["avg_ts"])
            metrics[headline_key(test, depth)] = Metric(best["avg_ts"], note=f"t={best['n_threads']}")
    threads = f"{selection.threads} threads" if selection.threads else "the fastest thread count"
    choice = f"{model or 'no matching model'}, KV {selection.cache_type}/{selection.cache_type}, {threads}"
    return metrics, choice


def build_side(name: str, documents: list[dict[str, Any]], selection: BenchSelection) -> Side:
    bench_documents = [doc for doc in documents if doc.get("kind") in BENCH_KINDS]
    end_to_end = [doc for doc in documents if doc.get("kind") in END_TO_END_KINDS]
    if len(bench_documents) > 1 or len(end_to_end) > 1:
        raise ValueError(f"{name}: give at most one llama-bench file and one end-to-end file")
    side = Side(name, documents)
    if bench_documents:
        side.bench = summary_rows(bench_documents[0].get("results") or [])
        found, side.bench_choice = bench_metrics(side.bench, selection)
        side.metrics.update(found)
    if end_to_end:
        document = end_to_end[0]
        found = eval_metrics(document) if document["kind"] == EVAL_KIND else recorded_metrics(document)
        side.metrics.update(found)
    return side


def format_number(value: float, unit: str) -> str:
    if unit == "count":
        return f"{int(value)}"
    digits = DECIMALS.get(unit, 2)
    if unit in SMALL_VALUE_UNITS and abs(value) < 10:
        digits = 2
    text = f"{value:,.{digits}f}"
    return f"{text}%" if unit == "%" else f"{text} {unit}"


def format_metric(metric: Metric | None, unit: str) -> str:
    if metric is None or metric.value is None:
        return EMPTY
    text = str(metric.value) if unit == "text" else format_number(metric.value, unit)
    extras = [f"n={metric.n}"] if metric.n is not None else []
    if metric.note:
        extras.append(metric.note)
    return f"{text} ({', '.join(extras)})" if extras else text


def format_change(before: Metric | None, after: Metric | None, unit: str) -> str:
    if before is None or after is None or before.value is None or after.value is None:
        return ""
    if unit == "text":
        return "same" if before.value == after.value else "changed"
    delta = after.value - before.value
    if unit == "%":
        return f"{delta:+.1f} pts"
    if unit == "count":
        return f"{int(delta):+d}"
    digits = DECIMALS.get(unit, 2)
    if unit in SMALL_VALUE_UNITS and abs(delta) < 10:
        digits = 2
    relative = f" ({delta / before.value * 100:+.0f}%)" if before.value else ""
    return f"{delta:+,.{digits}f} {unit}{relative}"


def row_change(row: MetricRow, before: Metric | None, after: Metric | None) -> str:
    if row.is_total and before and after and before.n != after.n:
        return "not comparable: different question counts"
    return format_change(before, after, row.unit)


def _cell(text: Any) -> str:
    return str(text if text not in (None, "") else EMPTY).replace("|", "\\|")


def _table(header: list[str], rows: list[list[Any]]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    lines += ["| " + " | ".join(_cell(value) for value in row) + " |" for row in rows]
    return lines


def _short_hash(value: Any) -> str | None:
    return f"{value[:12]}…" if isinstance(value, str) and len(value) > 12 else value


def _machine_text(machine: dict[str, Any]) -> str | None:
    if not machine:
        return None
    details = []
    if machine.get("physical_cores"):
        details.append(f"{machine['physical_cores']} cores")
    if machine.get("avx2") is not None:
        details.append("AVX2" if machine["avx2"] else "no AVX2")
    cpu = machine.get("cpu_model") or "CPU not recorded"
    text = f"{cpu} ({', '.join(details)})" if details else cpu
    return f"{machine['reference']}: {text}" if machine.get("reference") else text


def _ram_text(machine: dict[str, Any]) -> str | None:
    parts = [machine.get("ram"), machine.get("ram_type"), machine.get("ram_speed")]
    return ", ".join(str(part) for part in parts if part) or None


def _docker_memory(machine: dict[str, Any]) -> str | None:
    docker = machine.get("docker") or {}
    memory = _gib(docker.get("mem_total_bytes"))
    return f"{memory} GiB" if memory is not None else None


def _models_text(side: Side) -> tuple[str | None, str | None]:
    names, hashes = [], []
    end_to_end = side.end_to_end
    if end_to_end and isinstance(end_to_end.get("model"), dict):
        model = end_to_end["model"]
        names.append(model.get("file") or model.get("name"))
        hashes.append(_short_hash(model.get("sha256")))
    bench = side.first(BENCH_KINDS)
    for model in (bench or {}).get("models") or []:
        names.append(model.get("file"))
        hashes.append(_short_hash(model.get("sha256")))
    return (
        ", ".join(dict.fromkeys(str(name) for name in names if name)) or None,
        ", ".join(dict.fromkeys(str(value) for value in hashes if value)) or None,
    )


def _build_text(side: Side) -> str | None:
    builds = []
    for doc in side.documents:
        llama_cpp = doc.get("llama_cpp") or {}
        build = llama_cpp.get("build") or (doc.get("recorded") or {}).get("runtime")
        if build:
            builds.append(str(build))
    return ", ".join(dict.fromkeys(builds)) or None


def _testset_text(side: Side) -> str | None:
    testset = (side.end_to_end or {}).get("testset") or {}
    if not testset.get("version"):
        return None
    return f"{testset['version']} ({_short_hash(testset.get('sha256'))})"


def _started(side: Side) -> str | None:
    values = [
        (doc.get("run") or {}).get("started_at") or (doc.get("recorded") or {}).get("date")
        for doc in side.documents
    ]
    return ", ".join(str(value) for value in values if value) or None


def header_rows(sides: list[Side]) -> list[list[Any]]:
    model_texts = [_models_text(side) for side in sides]
    return [
        ["Files", *[", ".join(Path(doc["path"]).name for doc in side.documents) for side in sides]],
        ["Label", *[side.label for side in sides]],
        ["Run started", *[_started(side) for side in sides]],
        ["Machine", *[_machine_text(side.machine) for side in sides]],
        ["RAM", *[_ram_text(side.machine) for side in sides]],
        ["Docker memory", *[_docker_memory(side.machine) for side in sides]],
        ["Disk", *[side.machine.get("disk_type") for side in sides]],
        ["llama.cpp / runtime", *[_build_text(side) for side in sides]],
        ["Model", *[text[0] for text in model_texts]],
        ["Model SHA-256", *[text[1] for text in model_texts]],
        ["Test set", *[_testset_text(side) for side in sides]],
        ["llama-bench rows shown", *[side.bench_choice for side in sides]],
    ]


def sampling_warnings(doc: dict[str, Any]) -> list[str]:
    excess = (doc.get("resources") or {}).get("unsampled_peak_excess_bytes") or {}
    return [
        f"{doc.get('label')}: the cgroup memory.peak of {name} rose {_gib(over):.2f} GiB above its docker stats "
        "peak during the questions (a spike between samples, or page cache). Repeat the run with "
        "--sample-interval 2 before taking ADR-005's P from it."
        for name, over in sorted(excess.items())
        if isinstance(over, (int, float)) and over > UNSAMPLED_PEAK_LIMIT_BYTES
    ]


def comparison_warnings(sides: list[Side]) -> list[str]:
    warnings = []
    for side in sides:
        for doc in side.documents:
            run = doc.get("run") or {}
            if doc.get("kind") == EVAL_KIND and run.get("completed") is False:
                warnings.append(f"{doc.get('label')}: the run did not complete.")
            if doc.get("kind") == EVAL_KIND:
                warnings += sampling_warnings(doc)
            pending = ((doc.get("summary") or {}).get("manual_review") or {}).get("pending")
            if doc.get("kind") == EVAL_KIND and pending:
                warnings.append(f"{doc.get('label')}: {pending} answers still wait for the two reviewers.")
            if doc.get("kind") == RECORDED_KIND:
                sources = ", ".join((doc.get("recorded") or {}).get("sources") or [])
                warnings.append(
                    f"{doc.get('label')} is a recorded result ({sources}), not a run of the test set."
                )
    if len(sides) < 2:
        return warnings
    testsets = [(side.end_to_end or {}).get("testset") or {} for side in sides]
    if all(testset.get("sha256") for testset in testsets) and testsets[0].get("sha256") != testsets[1].get("sha256"):
        warnings.append("The two runs used different test sets: the answer and source rates are not comparable.")
    machines = [(side.machine.get("cpu_model"), side.machine.get("ram")) for side in sides]
    if all(side.machine for side in sides) and machines[0] != machines[1]:
        warnings.append("The two sides come from different machines.")
    kv = [side.metrics.get("kv_cache") for side in sides]
    if all(kv) and kv[0].value != kv[1].value:
        warnings.append(
            f"The KV cache differs ({kv[0].value} before, {kv[1].value} after): the answer and source "
            "rows measure its quality cost."
        )
    return warnings


def bench_detail(sides: list[Side]) -> list[str]:
    keyed = [
        {
            (row["model"], row["test"], row["n_depth"], row["type_k"], row["type_v"], str(row["n_threads"])): row
            for row in side.bench
        }
        for side in sides
    ]
    keys = list(dict.fromkeys(key for rows in keyed for key in rows))
    if not keys:
        return []
    header = ["Model", "Test", "Depth", "KV K/V", "Threads", *[f"{side.name} (t/s)" for side in sides]]
    if len(sides) == 2:
        header.append("Change")
    rows = []
    for key in keys:
        model, test, depth, type_k, type_v, threads = key
        values = [rows_by_key.get(key) for rows_by_key in keyed]
        metrics = [
            Metric(row["avg_ts"], note=f"± {row['stddev_ts']}") if row else None for row in values
        ]
        cells = [model, test, depth, f"{type_k}/{type_v}", threads]
        cells += [format_metric(metric, "t/s") for metric in metrics]
        if len(sides) == 2:
            cells.append(format_change(metrics[0], metrics[1], "t/s"))
        rows.append(cells)
    return ["", "## llama-bench, every configuration", "", *_table(header, rows)]


def render(sides: list[Side]) -> str:
    title = "# Benchmark comparison" if len(sides) == 2 else "# Benchmark"
    names = [side.name for side in sides]
    lines = [title, "", *_table(["", *names], header_rows(sides))]
    warnings = comparison_warnings(sides)
    if warnings:
        lines += ["", *[f"- {warning}" for warning in warnings]]
    header = ["Metric", "How it's measured", *names]
    if len(sides) == 2:
        header.append("Change")
    rows = []
    for row in SECTION_10_ROWS:
        metrics = [side.metrics.get(row.key) for side in sides]
        label = row.label if row.unit in UNITLESS else f"{row.label} ({row.unit})"
        cells = [label, row.how]
        cells += [format_metric(metric, row.unit) for metric in metrics]
        if len(sides) == 2:
            cells.append(row_change(row, metrics[0], metrics[1]))
        rows.append(cells)
    lines += ["", "## Section 10 metrics", "", *_table(header, rows)]
    lines += bench_detail(sides)
    notes = [
        f"- {doc.get('label')}: {note}"
        for side in sides
        for doc in side.documents
        for note in doc.get("notes") or []
    ]
    if notes:
        lines += ["", "## Notes", "", *notes]
    return "\n".join(lines) + "\n"


def compare_markdown(
    before: list[Path | str], after: list[Path | str] | None, selection: BenchSelection
) -> str:
    sides = [build_side("before" if after else "run", [load_document(path) for path in before], selection)]
    if after:
        sides.append(build_side("after", [load_document(path) for path in after], selection))
    return render(sides)
