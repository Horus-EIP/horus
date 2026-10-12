# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from horus_bench_kit.files import check_report, read_json
from horus_bench_kit.llama_bench import RAW_REPORT_KIND, summary_rows
from horus_bench_kit.llama_bench import REPORT_KIND as LLAMA_BENCH_KIND
from horus_bench_kit.llama_bench import SCHEMA_VERSION as LLAMA_BENCH_VERSION
from horus_bench_kit.markdown import (
    UNITLESS,
    Metric,
    MetricRow,
    format_change,
    format_metric,
    row_change,
    short_hash,
    table,
)
from horus_bench_kit.report import REPORT_KIND as EVAL_KIND
from horus_bench_kit.report import SCHEMA_VERSION as EVAL_VERSION

BENCH_KINDS = frozenset({LLAMA_BENCH_KIND, RAW_REPORT_KIND})
GIB = 1024**3
HEADLINE_TESTS = (
    ("pp512", 0),
    ("pp2048", 0),
    ("tg128", 0),
    ("pp512", 4096),
    ("pp2048", 4096),
    ("tg128", 4096),
)
LLAMA_BENCH_ROWS = (
    MetricRow("pp512", "Prompt processing pp512", "llama-bench", "t/s"),
    MetricRow("pp2048", "Prompt processing pp2048", "llama-bench", "t/s"),
    MetricRow("tg128", "Generation tg128", "llama-bench", "t/s"),
    MetricRow("pp512@d4096", "Prompt processing pp512, depth 4096", "llama-bench", "t/s"),
    MetricRow("pp2048@d4096", "Prompt processing pp2048, depth 4096", "llama-bench", "t/s"),
    MetricRow("tg128@d4096", "Generation tg128, depth 4096", "llama-bench", "t/s"),
)
EVAL_ROWS = (
    MetricRow("questions", "Questions", "test set items run", "count"),
    MetricRow("ttft_median_s", "Time to first token, median", "first streamed token", "s"),
    MetricRow("ttft_p90_s", "Time to first token, p90", "first streamed token", "s"),
    MetricRow("total_median_s", "Total time, median", "question sent to full answer", "s"),
    MetricRow("total_p90_s", "Total time, p90", "question sent to full answer", "s"),
    MetricRow("total_sum_s", "Total time, whole run", "sum over the questions", "s", is_total=True),
    MetricRow("answer_correct_reviewed_pct", "Answer correct, two reviewers", "manual review", "%"),
    MetricRow("answer_correct_auto_pct", "Answer correct, automatic", "answer patterns", "%"),
    MetricRow("source_correct_auto_pct", "Source correct", "expected document", "%"),
    MetricRow("fallbacks", "Fallback answers", "fallback markers", "count"),
)


@dataclass(frozen=True)
class BenchSelection:
    model: str | None = None
    threads: int | None = None
    cache_type: str = "f16"


def no_warnings(_document: dict[str, Any]) -> list[str]:
    return []


def llama_cpp_build(document: dict[str, Any]) -> Any:
    return (document.get("llama_cpp") or {}).get("build")


def run_started(document: dict[str, Any]) -> Any:
    return (document.get("run") or {}).get("started_at")


def model_section(document: dict[str, Any]) -> tuple[Any, Any] | None:
    model = document.get("model")
    if not isinstance(model, dict):
        return None
    return model.get("file") or model.get("name"), model.get("sha256")


@dataclass(frozen=True)
class Family:
    kind: str
    schema_version: int
    metrics: Callable[[dict[str, Any]], dict[str, Metric]]
    warnings: Callable[[dict[str, Any]], list[str]] = no_warnings
    build: Callable[[dict[str, Any]], Any] = llama_cpp_build
    started: Callable[[dict[str, Any]], Any] = run_started
    model: Callable[[dict[str, Any]], tuple[Any, Any] | None] = model_section


def gib(value: Any) -> float | None:
    return round(value / GIB, 2) if isinstance(value, (int, float)) else None


def stat_metric(block: dict[str, Any], field_name: str, statistic: str, scale: float = 1.0) -> Metric:
    values = block.get(field_name) or {}
    value = values.get(statistic)
    scaled = round(value * scale, 3) if isinstance(value, (int, float)) else None
    return Metric(scaled, values.get("n"))


def rate_metric(block: dict[str, Any] | None) -> Metric:
    block = block or {}
    return Metric(block.get("pct"), block.get("n"))


def count_total(values: Any) -> int | None:
    return sum(values.values()) if isinstance(values, dict) else None


def container_total(values: Any) -> int | None:
    if not isinstance(values, dict) or not values or None in values.values():
        return None
    return sum(values.values())


def methods_text(methods: Any) -> str | None:
    if not isinstance(methods, dict) or not methods:
        return None
    return ", ".join(f"{method} {count}" for method, count in sorted(methods.items()))


def eval_metrics(report: dict[str, Any]) -> dict[str, Metric]:
    summary = report.get("summary") or {}
    review = summary.get("manual_review") or {}
    return {
        "questions": Metric(summary.get("questions")),
        "ttft_median_s": stat_metric(summary, "ttft_s", "median"),
        "ttft_p90_s": stat_metric(summary, "ttft_s", "p90"),
        "total_median_s": stat_metric(summary, "total_s", "median"),
        "total_p90_s": stat_metric(summary, "total_s", "p90"),
        "total_sum_s": stat_metric(summary, "total_s", "sum"),
        "answer_correct_reviewed_pct": Metric(review.get("answer_correct_pct"), review.get("reviewed")),
        "answer_correct_auto_pct": rate_metric(summary.get("answer_correct_auto")),
        "source_correct_auto_pct": rate_metric(summary.get("source_correct_auto")),
        "fallbacks": Metric(count_total(summary.get("fallbacks")), summary.get("questions")),
    }


def eval_warnings(report: dict[str, Any]) -> list[str]:
    warnings = []
    if (report.get("run") or {}).get("completed") is False:
        warnings.append(f"{report.get('label')}: the run did not complete.")
    pending = ((report.get("summary") or {}).get("manual_review") or {}).get("pending")
    if pending:
        warnings.append(f"{report.get('label')}: {pending} answers still wait for the two reviewers.")
    return warnings


def eval_model(report: dict[str, Any]) -> tuple[Any, Any] | None:
    return model_section(report) or ((report.get("run") or {}).get("model"), None)


EVAL_FAMILY = Family(EVAL_KIND, EVAL_VERSION, eval_metrics, eval_warnings, model=eval_model)


@dataclass(frozen=True)
class CompareProfile:
    rows: tuple[MetricRow, ...] = (*LLAMA_BENCH_ROWS, *EVAL_ROWS)
    families: tuple[Family, ...] = (EVAL_FAMILY,)
    heading: str = "## Metrics"
    headline_tests: tuple[tuple[str, int], ...] = HEADLINE_TESTS

    def family(self, kind: Any) -> Family | None:
        return next((family for family in self.families if family.kind == kind), None)

    @property
    def end_to_end_kinds(self) -> frozenset[str]:
        return frozenset(family.kind for family in self.families)


DEFAULT_PROFILE = CompareProfile()


@dataclass
class Side:
    name: str
    documents: list[dict[str, Any]]
    end_to_end_kinds: frozenset[str] = frozenset()
    metrics: dict[str, Metric] = field(default_factory=dict)
    bench: list[dict[str, Any]] = field(default_factory=list)
    bench_choice: str | None = None

    def first(self, kinds: frozenset[str]) -> dict[str, Any] | None:
        return next((doc for doc in self.documents if doc.get("kind") in kinds), None)

    @property
    def end_to_end(self) -> dict[str, Any] | None:
        return self.first(self.end_to_end_kinds)

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


def load_document(path: Path | str, profile: CompareProfile = DEFAULT_PROFILE) -> dict[str, Any]:
    data = read_json(path)
    if isinstance(data, list):
        return {"kind": RAW_REPORT_KIND, "label": Path(path).stem, "results": data, "path": str(path)}
    kind = data.get("kind") if isinstance(data, dict) else None
    family = profile.family(kind)
    if kind not in BENCH_KINDS and family is None:
        raise ValueError(f"{path}: not a benchmark file (kind={kind!r})")
    try:
        check_report(data, kind, family.schema_version if family else LLAMA_BENCH_VERSION)
    except ValueError as exc:
        raise ValueError(f"{path}: {exc}") from exc
    return {**data, "path": str(path)}


def choose_model(rows: list[dict[str, Any]], wanted: str | None) -> str | None:
    models = list(dict.fromkeys(row["model"] for row in rows if row["model"]))
    if wanted:
        return next((model for model in models if wanted.lower() in model.lower()), None)
    return models[0] if models else None


def bench_metrics(
    rows: list[dict[str, Any]],
    selection: BenchSelection,
    headline_tests: tuple[tuple[str, int], ...] = HEADLINE_TESTS,
) -> tuple[dict[str, Metric], str]:
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
    for test, depth in headline_tests:
        candidates = [row for row in chosen if row["test"] == test and row["n_depth"] == depth]
        if candidates:
            best = max(candidates, key=lambda row: row["avg_ts"])
            metrics[headline_key(test, depth)] = Metric(best["avg_ts"], note=f"t={best['n_threads']}")
    threads = f"{selection.threads} threads" if selection.threads else "the fastest thread count"
    choice = f"{model or 'no matching model'}, KV {selection.cache_type}/{selection.cache_type}, {threads}"
    return metrics, choice


def build_side(
    name: str,
    documents: list[dict[str, Any]],
    selection: BenchSelection,
    profile: CompareProfile = DEFAULT_PROFILE,
) -> Side:
    end_to_end_kinds = profile.end_to_end_kinds
    bench_documents = [doc for doc in documents if doc.get("kind") in BENCH_KINDS]
    end_to_end = [doc for doc in documents if doc.get("kind") in end_to_end_kinds]
    if len(bench_documents) > 1 or len(end_to_end) > 1:
        raise ValueError(f"{name}: give at most one llama-bench file and one end-to-end file")
    side = Side(name, documents, end_to_end_kinds)
    if bench_documents:
        side.bench = summary_rows(bench_documents[0].get("results") or [])
        found, side.bench_choice = bench_metrics(side.bench, selection, profile.headline_tests)
        side.metrics.update(found)
    if end_to_end:
        document = end_to_end[0]
        side.metrics.update(profile.family(document["kind"]).metrics(document))
    return side


def machine_text(machine: dict[str, Any]) -> str | None:
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


def ram_text(machine: dict[str, Any]) -> str | None:
    parts = [machine.get("ram"), machine.get("ram_type"), machine.get("ram_speed")]
    return ", ".join(str(part) for part in parts if part) or None


def docker_memory(machine: dict[str, Any]) -> str | None:
    docker = machine.get("docker") or {}
    memory = gib(docker.get("mem_total_bytes"))
    return f"{memory} GiB" if memory is not None else None


def _document_value(document: dict[str, Any], profile: CompareProfile, name: str, default: Callable) -> Any:
    family = profile.family(document.get("kind"))
    return getattr(family, name)(document) if family else default(document)


def models_text(side: Side, profile: CompareProfile) -> tuple[str | None, str | None]:
    names, hashes = [], []
    end_to_end = side.end_to_end
    model = _document_value(end_to_end, profile, "model", model_section) if end_to_end else None
    if model:
        names.append(model[0])
        hashes.append(short_hash(model[1]))
    bench = side.first(BENCH_KINDS)
    for found in (bench or {}).get("models") or []:
        names.append(found.get("file"))
        hashes.append(short_hash(found.get("sha256")))
    return (
        ", ".join(dict.fromkeys(str(name) for name in names if name)) or None,
        ", ".join(dict.fromkeys(str(value) for value in hashes if value)) or None,
    )


def build_text(side: Side, profile: CompareProfile) -> str | None:
    builds = []
    for doc in side.documents:
        build = _document_value(doc, profile, "build", llama_cpp_build)
        if build:
            builds.append(str(build))
    return ", ".join(dict.fromkeys(builds)) or None


def testset_text(side: Side) -> str | None:
    testset = (side.end_to_end or {}).get("testset") or {}
    if not testset.get("version"):
        return None
    return f"{testset['version']} ({short_hash(testset.get('sha256'))})"


def started_text(side: Side, profile: CompareProfile) -> str | None:
    values = [_document_value(doc, profile, "started", run_started) for doc in side.documents]
    return ", ".join(str(value) for value in values if value) or None


def header_rows(sides: list[Side], profile: CompareProfile = DEFAULT_PROFILE) -> list[list[Any]]:
    model_texts = [models_text(side, profile) for side in sides]
    return [
        ["Files", *[", ".join(Path(doc["path"]).name for doc in side.documents) for side in sides]],
        ["Label", *[side.label for side in sides]],
        ["Run started", *[started_text(side, profile) for side in sides]],
        ["Machine", *[machine_text(side.machine) for side in sides]],
        ["RAM", *[ram_text(side.machine) for side in sides]],
        ["Docker memory", *[docker_memory(side.machine) for side in sides]],
        ["Disk", *[side.machine.get("disk_type") for side in sides]],
        ["llama.cpp / runtime", *[build_text(side, profile) for side in sides]],
        ["Model", *[text[0] for text in model_texts]],
        ["Model SHA-256", *[text[1] for text in model_texts]],
        ["Test set", *[testset_text(side) for side in sides]],
        ["llama-bench rows shown", *[side.bench_choice for side in sides]],
    ]


def comparison_warnings(sides: list[Side], profile: CompareProfile = DEFAULT_PROFILE) -> list[str]:
    warnings = []
    for side in sides:
        for doc in side.documents:
            family = profile.family(doc.get("kind"))
            if family:
                warnings += family.warnings(doc)
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
    return ["", "## llama-bench, every configuration", "", *table(header, rows)]


def render(sides: list[Side], profile: CompareProfile = DEFAULT_PROFILE) -> str:
    title = "# Benchmark comparison" if len(sides) == 2 else "# Benchmark"
    names = [side.name for side in sides]
    lines = [title, "", *table(["", *names], header_rows(sides, profile))]
    warnings = comparison_warnings(sides, profile)
    if warnings:
        lines += ["", *[f"- {warning}" for warning in warnings]]
    header = ["Metric", "How it's measured", *names]
    if len(sides) == 2:
        header.append("Change")
    rows = []
    for row in profile.rows:
        metrics = [side.metrics.get(row.key) for side in sides]
        label = row.label if row.unit in UNITLESS else f"{row.label} ({row.unit})"
        cells = [label, row.how]
        cells += [format_metric(metric, row.unit) for metric in metrics]
        if len(sides) == 2:
            cells.append(row_change(row, metrics[0], metrics[1]))
        rows.append(cells)
    lines += ["", profile.heading, "", *table(header, rows)]
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
    before: list[Path | str],
    after: list[Path | str] | None,
    selection: BenchSelection,
    profile: CompareProfile = DEFAULT_PROFILE,
) -> str:
    sides = [
        build_side("before" if after else "run", [load_document(path, profile) for path in before], selection, profile)
    ]
    if after:
        sides.append(build_side("after", [load_document(path, profile) for path in after], selection, profile))
    return render(sides, profile)
