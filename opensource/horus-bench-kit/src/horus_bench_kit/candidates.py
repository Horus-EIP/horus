# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from horus_bench_kit.files import SHA256_PATTERN, load_data
from horus_bench_kit.llama_bench import KnownModel

REPORT_KIND = "horus-model-candidates"
SCHEMA_VERSION = 1
SUMMARY_LABEL = "model-candidates"
HUGGING_FACE = "https://huggingface.co"
STEPS = ("fetch", "bench", "probe", "eval")
SERVING_STEPS = frozenset({"probe", "eval"})
ROLES = ("baseline", "candidate")
THINKING_DEFAULTS = ("on", "off", "none")
BENCH_TESTS = ("pp512", "pp2048", "tg128")
GIB = 1024**3
MISSING = "–"
GATE_BUILD = "needs llama.cpp b{since}, the catalog pins b{pinned}"
CONTRACT_HEADLINE_KEYS = (
    "replies",
    "json_valid",
    "failures",
    "thought_first",
    "truncated",
    "expected_correct",
    "patterns_correct",
    "wall_s",
    "completion_tokens",
    "prompt_tps",
    "generation_tps",
)

_REVISION = re.compile(r"^[0-9a-f]{40}$")
_BUILD_TAG = re.compile(r"^b(\d+)$")
_WRITTEN = re.compile(r"(?:\[done\] wrote|writing) (.+?)\s*$")

CATALOG_FIELDS = ("version", "llama_cpp", "licences_allowed", "llama_bench", "candidates")
CANDIDATE_FIELDS = (
    "id",
    "role",
    "name",
    "model_repo",
    "model_revision",
    "licence",
    "licence_statement",
    "licence_flags",
    "architecture",
    "gguf_architecture",
    "llama_cpp",
    "parameters",
    "active_parameters",
    "size_note",
    "context_length",
    "thinking_default",
    "thinking_evidence",
    "notes",
    "ggufs",
)
CANDIDATE_TEXT_FIELDS = (
    "model_repo",
    "licence",
    "licence_statement",
    "architecture",
    "gguf_architecture",
    "size_note",
    "thinking_evidence",
)
OLD_NAME_FIELD = "plan_name"
GGUF_FIELDS = (
    "id",
    "file",
    "quant",
    "repo",
    "revision",
    "upstream_file",
    "publisher",
    "size_bytes",
    "sha256",
    "default",
)


def name_field(candidate: dict[str, Any], name_key: str | None = None) -> str:
    if name_key:
        return name_key
    return OLD_NAME_FIELD if "name" not in candidate and OLD_NAME_FIELD in candidate else "name"


def candidate_name(candidate: dict[str, Any], name_key: str | None = None) -> Any:
    return candidate.get(name_field(candidate, name_key))


@dataclass(frozen=True)
class Variant:
    candidate: dict[str, Any]
    gguf: dict[str, Any]
    name_key: str | None = None

    @property
    def id(self) -> str:
        return self.gguf["id"]

    @property
    def file(self) -> str:
        return self.gguf["file"]

    @property
    def url(self) -> str:
        return download_url(self.gguf)

    @property
    def name(self) -> str:
        return candidate_name(self.candidate, self.name_key)

    def known_model(self) -> KnownModel:
        return KnownModel(self.file, self.url, self.gguf["size_bytes"], self.gguf["sha256"])


def load_catalog(path: Path | str) -> dict[str, Any]:
    return load_data(path, "catalog")


def build_number(tag: Any) -> int | None:
    match = _BUILD_TAG.match(str(tag or ""))
    return int(match.group(1)) if match else None


def download_url(gguf: dict[str, Any]) -> str:
    return f"{HUGGING_FACE}/{gguf['repo']}/resolve/{gguf['revision']}/{gguf['upstream_file']}"


def _is_whole(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def is_bare_gguf_name(value: Any) -> bool:
    return (
        _is_text(value)
        and value.endswith(".gguf")
        and not value.startswith(".")
        and "/" not in value
        and "\\" not in value
    )


def _gguf_problems(where: str, gguf: Any) -> list[str]:
    if not isinstance(gguf, dict):
        return [f"{where}: each gguf must be a mapping"]
    label = f"{where} gguf {gguf.get('id') or '?'}"
    problems = [f"{label}: missing {name}" for name in GGUF_FIELDS if name not in gguf]
    if problems:
        return problems
    for name in ("id", "quant", "repo", "upstream_file", "publisher"):
        if not _is_text(gguf[name]):
            problems.append(f"{label}: {name} must be a non-empty string")
    if not is_bare_gguf_name(gguf["file"]):
        problems.append(f"{label}: file must be a plain .gguf file name")
    if not _REVISION.match(str(gguf["revision"])):
        problems.append(f"{label}: revision must be a 40-character commit id")
    if not _is_whole(gguf["size_bytes"]) or gguf["size_bytes"] <= 0:
        problems.append(f"{label}: size_bytes must be a positive whole number")
    if not SHA256_PATTERN.match(str(gguf["sha256"])):
        problems.append(f"{label}: sha256 must be 64 lower-case hexadecimal characters")
    if not isinstance(gguf["default"], bool):
        problems.append(f"{label}: default must be true or false")
    return problems


def _support_problems(where: str, support: Any, pinned: int | None) -> list[str]:
    if not isinstance(support, dict):
        return [f"{where}: llama_cpp must be a mapping"]
    problems = [
        f"{where}: llama_cpp lacks {name}"
        for name in ("since_build", "since_pr", "evidence")
        if name not in support
    ]
    since = support.get("since_build")
    if since is not None and not _is_whole(since):
        problems.append(f"{where}: llama_cpp.since_build must be a build number or null")
    elif since is not None and pinned is not None and since > pinned:
        problems.append(f"{where}: needs llama.cpp b{since}, newer than the pinned b{pinned}")
    if support.get("since_pr") is not None and not _is_whole(support["since_pr"]):
        problems.append(f"{where}: llama_cpp.since_pr must be a pull request number or null")
    if not _is_text(support.get("evidence")):
        problems.append(f"{where}: llama_cpp.evidence must say where the support comes from")
    return problems


def _candidate_problems(
    candidate: Any, pinned: int | None, name_key: str | None = None
) -> list[str]:
    if not isinstance(candidate, dict):
        return ["each candidate must be a mapping"]
    where = f"candidate {candidate.get('id') or '?'}"
    names = name_field(candidate, name_key)
    required = [names if name == "name" else name for name in CANDIDATE_FIELDS]
    problems = [f"{where}: missing {name}" for name in required if name not in candidate]
    if problems:
        return problems
    for name in ("id", names, *CANDIDATE_TEXT_FIELDS):
        if not _is_text(candidate[name]):
            problems.append(f"{where}: {name} must be a non-empty string")
    if candidate["role"] not in ROLES:
        problems.append(f"{where}: role must be one of {', '.join(ROLES)}")
    if not _REVISION.match(str(candidate["model_revision"])):
        problems.append(f"{where}: model_revision must be a 40-character commit id")
    for name in ("licence_flags", "notes"):
        if not isinstance(candidate[name], list) or not all(
            _is_text(text) for text in candidate[name]
        ):
            problems.append(f"{where}: {name} must be a list of sentences")
    for name in ("parameters", "context_length"):
        if not _is_whole(candidate[name]) or candidate[name] <= 0:
            problems.append(f"{where}: {name} must be a positive whole number")
    active = candidate["active_parameters"]
    if active is not None and (not _is_whole(active) or active <= 0):
        problems.append(f"{where}: active_parameters must be a positive whole number or null")
    if candidate["thinking_default"] not in THINKING_DEFAULTS:
        problems.append(f"{where}: thinking_default must be one of {', '.join(THINKING_DEFAULTS)}")
    problems.extend(_support_problems(where, candidate["llama_cpp"], pinned))
    ggufs = candidate["ggufs"]
    if not isinstance(ggufs, list) or not ggufs:
        return [*problems, f"{where}: ggufs must be a non-empty list"]
    for gguf in ggufs:
        problems.extend(_gguf_problems(where, gguf))
    if not any(isinstance(g, dict) and g.get("default") is True for g in ggufs):
        problems.append(f"{where}: at least one gguf must be a default")
    return problems


def _repeated(values: list[Any]) -> list[str]:
    return sorted({str(value) for value in values if values.count(value) > 1})


def catalog_problems(catalog: Any, name_key: str | None = None) -> list[str]:
    if not isinstance(catalog, dict):
        return ["the catalog must be a mapping"]
    problems = [f"missing top-level {name}" for name in CATALOG_FIELDS if name not in catalog]
    if problems:
        return problems
    llama_cpp = catalog["llama_cpp"] if isinstance(catalog["llama_cpp"], dict) else {}
    pinned_tag = llama_cpp.get("pinned_build")
    pinned = build_number(pinned_tag)
    if pinned is None:
        problems.append("llama_cpp.pinned_build must look like b11382")
    for name in ("server_image", "bench_image"):
        if not str(llama_cpp.get(name) or "").endswith(f"-{pinned_tag}"):
            problems.append(f"llama_cpp.{name} must be tagged with the pinned build {pinned_tag}")
    allowed = catalog["licences_allowed"]
    if not isinstance(allowed, list) or not all(_is_text(name) for name in allowed):
        problems.append("licences_allowed must be a list of licence names")
    candidates = catalog["candidates"]
    if not isinstance(candidates, list) or not candidates:
        return [*problems, "candidates must be a non-empty list"]
    for candidate in candidates:
        problems.extend(_candidate_problems(candidate, pinned, name_key))
    mappings = [c for c in candidates if isinstance(c, dict)]
    ggufs = [g for c in mappings for g in c.get("ggufs") or [] if isinstance(g, dict)]
    for name, values in (
        ("candidate ids", [c.get("id") for c in mappings]),
        ("gguf ids", [g.get("id") for g in ggufs]),
        ("gguf files", [g.get("file") for g in ggufs]),
    ):
        repeated = _repeated(values)
        if repeated:
            problems.append(f"{name} must be unique: {', '.join(repeated)}")
    if not any(c.get("role") == "baseline" for c in mappings):
        problems.append("the catalog needs a baseline candidate")
    return problems


def all_variants(catalog: dict[str, Any], name_key: str | None = None) -> list[Variant]:
    return [
        Variant(candidate, gguf, name_key)
        for candidate in catalog["candidates"]
        for gguf in candidate["ggufs"]
    ]


def known_models_of(catalog: dict[str, Any]) -> dict[str, KnownModel]:
    return {variant.file: variant.known_model() for variant in all_variants(catalog)}


def select_variants(
    catalog: dict[str, Any],
    only: list[str] | None = None,
    all_quants: bool = False,
    name_key: str | None = None,
) -> list[Variant]:
    variants = all_variants(catalog, name_key)
    if not only:
        return [v for v in variants if all_quants or v.gguf["default"]]
    known = {v.id for v in variants} | {v.candidate["id"] for v in variants}
    unknown = [name for name in only if name not in known]
    if unknown:
        raise ValueError(f"unknown candidate or gguf id: {', '.join(unknown)}")
    chosen = set(only)
    return [
        v
        for v in variants
        if v.id in chosen or (v.candidate["id"] in chosen and (all_quants or v.gguf["default"]))
    ]


def variant_gate(
    variant: Variant, catalog: dict[str, Any], build_text: str = GATE_BUILD
) -> list[str]:
    problems = []
    licence = variant.candidate["licence"]
    if licence not in catalog["licences_allowed"]:
        problems.append(
            f"the licence {licence} is not one of {', '.join(catalog['licences_allowed'])}"
        )
    pinned = build_number(catalog["llama_cpp"]["pinned_build"])
    since = variant.candidate["llama_cpp"].get("since_build")
    if since is not None and pinned is not None and since > pinned:
        problems.append(build_text.format(since=since, pinned=pinned))
    return problems


def written_report(lines: list[str]) -> str | None:
    found = None
    for line in lines:
        match = _WRITTEN.search(line)
        if match:
            found = match.group(1)
    return found


def bench_speeds(
    bench_report: dict[str, Any] | None, cache_type: str = "f16"
) -> list[dict[str, Any]]:
    best: dict[tuple[str, int], dict[str, Any]] = {}
    for row in (bench_report or {}).get("summary") or []:
        if row.get("type_k") != cache_type or row.get("type_v") != cache_type:
            continue
        if not isinstance(row.get("avg_ts"), (int, float)):
            continue
        key = (row.get("test"), int(row.get("n_depth") or 0))
        if key not in best or row["avg_ts"] > best[key]["tps"]:
            best[key] = {
                "test": key[0],
                "depth": key[1],
                "tps": row["avg_ts"],
                "stddev": row.get("stddev_ts"),
                "threads": row.get("n_threads"),
            }
    order = {test: index for index, test in enumerate(BENCH_TESTS)}
    return sorted(
        best.values(), key=lambda s: (order.get(s["test"], len(order)), str(s["test"]), s["depth"])
    )


def bench_headline(
    bench_report: dict[str, Any] | None, variant: Variant, cache_type: str
) -> dict[str, Any] | None:
    if not bench_report:
        return None
    model = next((m for m in bench_report.get("models") or [] if m.get("file") == variant.file), {})
    sha256 = model.get("sha256")
    return {
        "build": (bench_report.get("llama_cpp") or {}).get("build"),
        "speeds": bench_speeds(bench_report, cache_type),
        "model_sha256": sha256,
        "sha256_matches_catalog": sha256 == variant.gguf["sha256"] if sha256 else None,
    }


def contract_headline(
    contract_report: dict[str, Any] | None, keys: tuple[str, ...] = CONTRACT_HEADLINE_KEYS
) -> dict[str, Any] | None:
    if not contract_report:
        return None
    summary = contract_report.get("summary") or {}
    return {key: summary.get(key) for key in keys}


def eval_headline(eval_report: dict[str, Any] | None) -> dict[str, Any] | None:
    if not eval_report:
        return None
    summary = eval_report.get("summary") or {}
    review = summary.get("manual_review") or {}
    return {
        "completed": (eval_report.get("run") or {}).get("completed"),
        "questions": summary.get("questions"),
        "status": summary.get("status"),
        "answer_correct_auto": summary.get("answer_correct_auto"),
        "answer_correct_reviewed_pct": review.get("answer_correct_pct"),
        "review_pending": review.get("pending"),
        "source_correct_auto": summary.get("source_correct_auto"),
        "route_correct": summary.get("route_correct"),
        "fallbacks": summary.get("fallbacks"),
        "total_s": summary.get("total_s"),
        "ttft_s": summary.get("ttft_s"),
    }


def rate_text(value: Any) -> str:
    if not isinstance(value, dict) or not value.get("n"):
        return MISSING
    return f"{value['correct']}/{value['n']} ({value['pct']:.1f}%)"


def gib_text(value: Any) -> str:
    return f"{value / GIB:.2f} GiB" if isinstance(value, (int, float)) and value else MISSING


def number_text(value: Any, digits: int = 1) -> str:
    return (
        f"{value:.{digits}f}"
        if isinstance(value, (int, float)) and not isinstance(value, bool)
        else MISSING
    )


def median_text(value: Any) -> str:
    return number_text(value.get("median")) if isinstance(value, dict) else MISSING


def section(variant: dict[str, Any], name: str) -> dict[str, Any]:
    return variant.get(name) or {}


def speed_text(variant: dict[str, Any], test: str, depth: int = 0) -> str:
    speeds = section(variant, "llama_bench").get("speeds") or []
    found = next((s for s in speeds if s["test"] == test and s["depth"] == depth), None)
    return number_text(found["tps"]) if found else MISSING


def model_cell(variant: dict[str, Any]) -> str:
    suffix = " (baseline)" if variant["role"] == "baseline" else ""
    return f"{variant['name']}{suffix}"


def gguf_cell(variant: dict[str, Any]) -> str:
    return f"{variant['quant']}, {variant['publisher']}"


def _snapshots(variant: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        snapshot
        for snapshot in (variant.get("memory") or {}).values()
        if isinstance(snapshot, dict)
    ]


def process_peak(variant: dict[str, Any]) -> Any:
    known = [
        peak
        for peak in (
            (snapshot.get("process") or {}).get("vm_hwm_bytes") for snapshot in _snapshots(variant)
        )
        if isinstance(peak, int)
    ]
    return max(known) if known else None


def cgroup_peak(variant: dict[str, Any]) -> Any:
    known = [
        peak
        for peak in (s.get("cgroup_peak_bytes") for s in _snapshots(variant))
        if isinstance(peak, int)
    ]
    return max(known) if known else None


def oom_kills_text(variant: dict[str, Any]) -> str:
    known = [
        count
        for count in (s.get("oom_kills") for s in _snapshots(variant))
        if isinstance(count, int)
    ]
    return str(max(known)) if known else MISSING


def evaluation_name(variants: list[dict[str, Any]]) -> str:
    counts = sorted({(variant.get("eval") or {}).get("questions") for variant in variants} - {None})
    if len(counts) == 1:
        return f"the {counts[0]}-question evaluation"
    if counts:
        return f"the evaluation ({counts[0]} to {counts[-1]} questions)"
    return "the evaluation"


def rate_cell(name: str, key: str) -> Callable[[dict[str, Any]], str]:
    return lambda variant: rate_text(section(variant, name).get(key))


def median_cell(name: str, key: str) -> Callable[[dict[str, Any]], str]:
    return lambda variant: median_text(section(variant, name).get(key))


def speed_cell(test: str, depth: int = 0) -> Callable[[dict[str, Any]], str]:
    return lambda variant: speed_text(variant, test, depth)


def thought_first_cell(variant: dict[str, Any]) -> str:
    count = section(variant, "contract").get("thought_first")
    return str(count) if isinstance(count, int) else MISSING


def reviewed_cell(variant: dict[str, Any]) -> str:
    reviewed = section(variant, "eval").get("answer_correct_reviewed_pct")
    return f"{reviewed:.1f}%" if isinstance(reviewed, (int, float)) else MISSING


@dataclass(frozen=True)
class Column:
    header: str
    cell: Callable[[dict[str, Any]], str]
    align: str = "---:"


def table_lines(columns: tuple[Column, ...], variants: list[dict[str, Any]]) -> list[str]:
    return [
        "| " + " | ".join(column.header for column in columns) + " |",
        "|" + "|".join(column.align for column in columns) + "|",
        *[
            "| " + " | ".join(column.cell(variant) for column in columns) + " |"
            for variant in variants
        ],
    ]


NAME_COLUMNS = (Column("Model", model_cell, "---"), Column("GGUF", gguf_cell, "---"))
QUALITY_COLUMNS = (
    *NAME_COLUMNS,
    Column("Licence", lambda variant: variant["licence"], "---"),
    Column("JSON valid", rate_cell("contract", "json_valid")),
    Column("Thought first", thought_first_cell),
    Column("Expected correct (probe)", rate_cell("contract", "expected_correct")),
    Column("Patterns correct (probe)", rate_cell("contract", "patterns_correct")),
    Column("Answer correct (eval, auto)", rate_cell("eval", "answer_correct_auto")),
    Column("Answer correct (reviewed)", reviewed_cell),
    Column("Source correct (eval)", rate_cell("eval", "source_correct_auto")),
)
SPEED_COLUMNS = (
    *NAME_COLUMNS,
    Column("File", lambda variant: gib_text(variant["size_bytes"])),
    Column("pp512", speed_cell("pp512")),
    Column("pp2048", speed_cell("pp2048")),
    Column("tg128", speed_cell("tg128")),
    Column("tg128 @ 4096", speed_cell("tg128", 4096)),
    Column("Probe reply", median_cell("contract", "wall_s")),
    Column("Eval answer", median_cell("eval", "total_s")),
    Column("Eval first token", median_cell("eval", "ttft_s")),
    Column("Server VmHWM", lambda variant: gib_text(process_peak(variant))),
    Column("Server cgroup peak", lambda variant: gib_text(cgroup_peak(variant))),
    Column("OOM kills", oom_kills_text),
)


@dataclass(frozen=True)
class MarkdownTexts:
    title: str = "# Model candidates, {date}"
    quality_heading: str = "## Reliability and answers"
    quality_intro: str = (
        "JSON valid: probe replies that parse and validate against the schema they were sent with. "
        "Probe columns come from the contract probe, evaluation columns from {evaluation}."
    )
    quality_columns: tuple[Column, ...] = QUALITY_COLUMNS
    speed_heading: str = "## Speed and memory"
    speed_intro: str = (
        "llama-bench tokens per second with the catalog's first KV cache type, best thread count, depth 0 "
        "unless named. Medians in seconds. Server VmHWM and cgroup peak: the candidate llama-server's peak "
        "resident memory and the peak memory of its container."
    )
    speed_columns: tuple[Column, ...] = SPEED_COLUMNS
    flags_heading: str = "## Licence flags"
    problems_heading: str = "## Problems"


DEFAULT_TEXTS = MarkdownTexts()


@dataclass(frozen=True)
class CandidatesProfile:
    kind: str = REPORT_KIND
    schema_version: int = SCHEMA_VERSION
    label: str = SUMMARY_LABEL
    contract_keys: tuple[str, ...] = CONTRACT_HEADLINE_KEYS
    eval_headline: Callable[[dict[str, Any] | None], dict[str, Any] | None] = eval_headline
    gate_build: str = GATE_BUILD
    markdown: MarkdownTexts = DEFAULT_TEXTS
    name_key: str | None = None


DEFAULT_PROFILE = CandidatesProfile()


def variant_summary(
    variant: Variant,
    *,
    profile: CandidatesProfile = DEFAULT_PROFILE,
    cache_type: str = "f16",
    fetch: dict[str, Any] | None = None,
    reports: dict[str, str | None] | None = None,
    bench_report: dict[str, Any] | None = None,
    contract_report: dict[str, Any] | None = None,
    eval_report: dict[str, Any] | None = None,
    server: dict[str, Any] | None = None,
    memory: dict[str, Any] | None = None,
    problems: list[str] | None = None,
) -> dict[str, Any]:
    candidate, gguf = variant.candidate, variant.gguf
    return {
        "id": variant.id,
        "candidate": candidate["id"],
        "role": candidate["role"],
        "name": variant.name,
        "model_repo": candidate["model_repo"],
        "licence": candidate["licence"],
        "licence_flags": list(candidate["licence_flags"]),
        "gguf_architecture": candidate["gguf_architecture"],
        "thinking_default": candidate["thinking_default"],
        "quant": gguf["quant"],
        "file": gguf["file"],
        "gguf_repo": gguf["repo"],
        "revision": gguf["revision"],
        "publisher": gguf["publisher"],
        "size_bytes": gguf["size_bytes"],
        "sha256": gguf["sha256"],
        "fetch": fetch,
        "reports": {"llama_bench": None, "contract": None, "eval": None, **(reports or {})},
        "llama_bench": bench_headline(bench_report, variant, cache_type),
        "contract": contract_headline(contract_report, profile.contract_keys),
        "eval": profile.eval_headline(eval_report),
        "server": server,
        "memory": memory,
        "problems": list(problems or []),
    }


def build_report(
    *,
    run: dict[str, Any],
    catalog: dict[str, Any],
    machine: dict[str, Any] | None,
    variants: list[dict[str, Any]],
    profile: CandidatesProfile = DEFAULT_PROFILE,
) -> dict[str, Any]:
    return {
        "kind": profile.kind,
        "schema_version": profile.schema_version,
        "label": profile.label,
        "catalog": catalog,
        "run": run,
        "machine": machine or {},
        "variants": variants,
    }


def markdown_summary(report: dict[str, Any], texts: MarkdownTexts = DEFAULT_TEXTS) -> str:
    run = report.get("run") or {}
    catalog = report.get("catalog") or {}
    machine = report.get("machine") or {}
    variants = report.get("variants") or []
    lines = [
        texts.title.format(date=str(run.get("started_at") or "")[:10]),
        "",
        f"Catalog `{catalog.get('path')}` version {catalog.get('version')}, llama.cpp "
        f"{catalog.get('pinned_build')}, reasoning `{run.get('reasoning')}`, steps "
        f"{', '.join(run.get('steps') or [])}. Machine: {machine.get('reference') or MISSING}, "
        f"{machine.get('cpu_model') or MISSING}, {machine.get('ram') or MISSING}. "
        f"Run {'completed' if run.get('completed') else 'not completed'}.",
        "",
        texts.quality_heading,
        "",
        texts.quality_intro.format(evaluation=evaluation_name(variants)),
        "",
        *table_lines(texts.quality_columns, variants),
        "",
        texts.speed_heading,
        "",
        texts.speed_intro,
        "",
        *table_lines(texts.speed_columns, variants),
    ]
    flagged = [v for v in variants if v.get("licence_flags")]
    if flagged:
        lines += ["", texts.flags_heading, ""]
        seen: set[str] = set()
        for variant in flagged:
            if variant["candidate"] in seen:
                continue
            seen.add(variant["candidate"])
            for flag in variant["licence_flags"]:
                lines.append(f"- {variant['name']}: {flag}")
    troubled = [v for v in variants if v.get("problems")]
    if troubled:
        lines += ["", texts.problems_heading, ""]
        for variant in troubled:
            for problem in variant["problems"]:
                lines.append(f"- `{variant['id']}`: {problem}")
    return "\n".join(lines) + "\n"
