from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from bench_llama import MODELS_DIR_PLACEHOLDER

REPORT_KIND = "horus-model-candidates"
SCHEMA_VERSION = 1
SUMMARY_LABEL = "model-candidates"
DEFAULT_CATALOG = Path(__file__).resolve().parent / "model-candidates.yaml"
HUGGING_FACE = "https://huggingface.co"
CONTAINER_MODELS_DIR = "/models"
CANDIDATE_CONTAINER = "llm-candidate"
STACK_LLM_CONTAINER = "llm"
AGENT_CONTAINER = "agent"
LLM_NETWORK_ALIAS = "llm"
RESPONSE_CACHE_SETTING = "AGENT_RESPONSE_CACHE"
ENABLED_SETTING_VALUES = frozenset({"1", "true", "yes", "on"})
STEPS = ("fetch", "bench", "probe", "eval")
SERVING_STEPS = frozenset({"probe", "eval"})
REASONING_MODES = ("off", "on", "auto")
ROLES = ("baseline", "candidate")
THINKING_DEFAULTS = ("on", "off", "none")
MODEL_FLAGS = frozenset({"-m", "--model"})
REASONING_FLAGS = frozenset({"-rea", "--reasoning"})
BENCH_TESTS = ("pp512", "pp2048", "tg128")
GIB = 1024**3
MISSING = "–"

_REVISION = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_BUILD_TAG = re.compile(r"^b(\d+)$")
_WRITTEN = re.compile(r"(?:\[done\] wrote|writing) (.+?)\s*$")
_STATUS_FIELD = re.compile(r"^(\w+):\s+(\d+)\s*kB\s*$")

CATALOG_FIELDS = ("version", "llama_cpp", "licences_allowed", "llama_bench", "candidates")
CANDIDATE_FIELDS = (
    "id",
    "role",
    "plan_name",
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
PROCESS_MEMORY_FIELDS = {
    "VmHWM": "vm_hwm_bytes",
    "VmRSS": "vm_rss_bytes",
    "RssAnon": "rss_anon_bytes",
    "RssFile": "rss_file_bytes",
}


@dataclass(frozen=True)
class Variant:
    candidate: dict[str, Any]
    gguf: dict[str, Any]

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
        return self.candidate["plan_name"]


def load_catalog(path: Path | str = DEFAULT_CATALOG) -> dict[str, Any]:
    with open(path, encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def build_number(tag: Any) -> int | None:
    match = _BUILD_TAG.match(str(tag or ""))
    return int(match.group(1)) if match else None


def download_url(gguf: dict[str, Any]) -> str:
    return f"{HUGGING_FACE}/{gguf['repo']}/resolve/{gguf['revision']}/{gguf['upstream_file']}"


def _is_whole(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _is_bare_gguf_name(value: Any) -> bool:
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
    if not _is_bare_gguf_name(gguf["file"]):
        problems.append(f"{label}: file must be a plain .gguf file name")
    if not _REVISION.match(str(gguf["revision"])):
        problems.append(f"{label}: revision must be a 40-character commit id")
    if not _is_whole(gguf["size_bytes"]) or gguf["size_bytes"] <= 0:
        problems.append(f"{label}: size_bytes must be a positive whole number")
    if not _SHA256.match(str(gguf["sha256"])):
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


def _candidate_problems(candidate: Any, pinned: int | None) -> list[str]:
    if not isinstance(candidate, dict):
        return ["each candidate must be a mapping"]
    where = f"candidate {candidate.get('id') or '?'}"
    problems = [f"{where}: missing {name}" for name in CANDIDATE_FIELDS if name not in candidate]
    if problems:
        return problems
    for name in (
        "id",
        "plan_name",
        "model_repo",
        "licence",
        "licence_statement",
        "architecture",
        "gguf_architecture",
        "size_note",
        "thinking_evidence",
    ):
        if not _is_text(candidate[name]):
            problems.append(f"{where}: {name} must be a non-empty string")
    if candidate["role"] not in ROLES:
        problems.append(f"{where}: role must be one of {', '.join(ROLES)}")
    if not _REVISION.match(str(candidate["model_revision"])):
        problems.append(f"{where}: model_revision must be a 40-character commit id")
    for name in ("licence_flags", "notes"):
        if not isinstance(candidate[name], list) or not all(_is_text(text) for text in candidate[name]):
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


def catalog_problems(catalog: Any) -> list[str]:
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
        problems.extend(_candidate_problems(candidate, pinned))
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


def all_variants(catalog: dict[str, Any]) -> list[Variant]:
    return [Variant(candidate, gguf) for candidate in catalog["candidates"] for gguf in candidate["ggufs"]]


def select_variants(
    catalog: dict[str, Any], only: list[str] | None = None, all_quants: bool = False
) -> list[Variant]:
    variants = all_variants(catalog)
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


def variant_gate(variant: Variant, catalog: dict[str, Any]) -> list[str]:
    problems = []
    licence = variant.candidate["licence"]
    if licence not in catalog["licences_allowed"]:
        problems.append(
            f"the licence {licence} is not one of {', '.join(catalog['licences_allowed'])}"
        )
    pinned = build_number(catalog["llama_cpp"]["pinned_build"])
    since = variant.candidate["llama_cpp"].get("since_build")
    if since is not None and pinned is not None and since > pinned:
        problems.append(f"needs llama.cpp b{since}, the stack pins b{pinned}")
    return problems


def _flag_value(args: list[str], index: int) -> tuple[str, str | None, int]:
    flag = args[index]
    if flag.startswith("--") and "=" in flag:
        name, value = flag.split("=", 1)
        return name, value, index + 1
    if index + 1 < len(args):
        return flag, args[index + 1], index + 2
    return flag, None, index + 1


def server_args(stack_args: list[str], model_file: str, reasoning: str) -> list[str]:
    args = [str(arg) for arg in stack_args]
    result: list[str] = []
    model_seen = False
    index = 0
    while index < len(args):
        flag = args[index].split("=", 1)[0] if args[index].startswith("--") else args[index]
        if flag in MODEL_FLAGS:
            _name, _value, index = _flag_value(args, index)
            result += ["--model", f"{CONTAINER_MODELS_DIR}/{model_file}"]
            model_seen = True
            continue
        if flag in REASONING_FLAGS:
            _name, _value, index = _flag_value(args, index)
            continue
        result.append(args[index])
        index += 1
    if not model_seen:
        result = ["--model", f"{CONTAINER_MODELS_DIR}/{model_file}", *result]
    return [*result, "--reasoning", reasoning]


def _inspected_container(text: str | None) -> dict[str, Any] | None:
    try:
        data = json.loads(text or "")
    except ValueError:
        return None
    if isinstance(data, list):
        data = data[0] if data else None
    return data if isinstance(data, dict) else None


def parse_container_env(text: str | None) -> dict[str, str] | None:
    data = _inspected_container(text)
    if data is None:
        return None
    env: dict[str, str] = {}
    for entry in (data.get("Config") or {}).get("Env") or []:
        name, separator, value = str(entry).partition("=")
        if separator:
            env[name] = value
    return env


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


def parse_container_inspect(text: str | None) -> dict[str, Any] | None:
    data = _inspected_container(text)
    if data is None:
        return None
    config = data.get("Config") or {}
    host = data.get("HostConfig") or {}
    state = data.get("State") or {}
    networks = (data.get("NetworkSettings") or {}).get("Networks") or {}
    mounts = data.get("Mounts") or []
    models_mount = next(
        (m for m in mounts if isinstance(m, dict) and m.get("Destination") == CONTAINER_MODELS_DIR),
        None,
    )
    models_source = None
    if models_mount is not None:
        volume = models_mount.get("Name") if models_mount.get("Type") == "volume" else None
        models_source = volume or MODELS_DIR_PLACEHOLDER
    return {
        "name": str(data.get("Name") or "").lstrip("/") or None,
        "image": config.get("Image"),
        "args": [str(arg) for arg in config.get("Cmd") or []],
        "networks": sorted(networks),
        "memory_bytes": host.get("Memory") or None,
        "running": bool(state.get("Running")),
        "oom_killed": bool(state.get("OOMKilled")),
        "restart_count": data.get("RestartCount"),
        "models_source": models_source,
    }


def candidate_network(networks: list[str]) -> str | None:
    preferred = [name for name in networks if name.endswith("horus-net")]
    return (preferred or networks or [None])[0]


def candidate_run_command(
    *,
    image: str,
    network: str,
    models_dir: str,
    args: list[str],
    memory_bytes: int | None,
    name: str = CANDIDATE_CONTAINER,
    alias: str = LLM_NETWORK_ALIAS,
) -> list[str]:
    command = ["docker", "run", "-d", "--name", name, "--network", network, "--network-alias", alias]
    if memory_bytes:
        command += ["--memory", str(memory_bytes), "--memory-swap", str(memory_bytes)]
    return [*command, "-v", f"{models_dir}:{CONTAINER_MODELS_DIR}:ro", image, *args]


def parse_memory_limit(text: str | None) -> int | None:
    match = re.match(r"^\s*(\d+(?:\.\d+)?)\s*([kmgt]?)b?\s*$", str(text or ""), re.IGNORECASE)
    if not match:
        return None
    scale = {"": 1, "k": 2**10, "m": 2**20, "g": 2**30, "t": 2**40}[match.group(2).lower()]
    return int(float(match.group(1)) * scale)


def parse_process_memory(text: str | None) -> dict[str, Any] | None:
    found: dict[str, Any] = {}
    name = None
    for line in (text or "").splitlines():
        if line.startswith("Name:"):
            name = line.partition(":")[2].strip()
            continue
        match = _STATUS_FIELD.match(line.strip())
        if match and match.group(1) in PROCESS_MEMORY_FIELDS:
            found[PROCESS_MEMORY_FIELDS[match.group(1)]] = int(match.group(2)) * 1024
    if name is None:
        return None
    return {"name": name, **{field: found.get(field) for field in PROCESS_MEMORY_FIELDS.values()}}


def written_report(lines: list[str]) -> str | None:
    found = None
    for line in lines:
        match = _WRITTEN.search(line)
        if match:
            found = match.group(1)
    return found


def bench_speeds(bench_report: dict[str, Any] | None, cache_type: str = "f16") -> list[dict[str, Any]]:
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
    return sorted(best.values(), key=lambda s: (order.get(s["test"], len(order)), str(s["test"]), s["depth"]))


def bench_headline(bench_report: dict[str, Any] | None, variant: Variant, cache_type: str) -> dict[str, Any] | None:
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


def contract_headline(contract_report: dict[str, Any] | None) -> dict[str, Any] | None:
    if not contract_report:
        return None
    summary = contract_report.get("summary") or {}
    keys = (
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
    return {key: summary.get(key) for key in keys}


def eval_headline(eval_report: dict[str, Any] | None, container: str = CANDIDATE_CONTAINER) -> dict[str, Any] | None:
    if not eval_report:
        return None
    summary = eval_report.get("summary") or {}
    resources = eval_report.get("resources") or {}
    llm = summary.get("llm") or {}

    def per_container(name: str) -> Any:
        values = resources.get(name)
        return values.get(container) if isinstance(values, dict) else None

    return {
        "completed": (eval_report.get("run") or {}).get("completed"),
        "questions": summary.get("questions"),
        "status": summary.get("status"),
        "answer_correct_auto": summary.get("answer_correct_auto"),
        "answer_correct_reviewed_pct": (summary.get("manual_review") or {}).get("answer_correct_pct"),
        "review_pending": (summary.get("manual_review") or {}).get("pending"),
        "source_correct_auto": summary.get("source_correct_auto"),
        "route_correct": summary.get("route_correct"),
        "fallbacks": summary.get("fallbacks"),
        "total_s": summary.get("total_s"),
        "ttft_s": summary.get("ttft_s"),
        "llm_prompt_tps": llm.get("prompt_tps"),
        "llm_generation_tps": llm.get("generation_tps"),
        "stack_peak_mem_bytes": resources.get("stack_peak_mem_bytes"),
        "containers_sum_peak_mem_bytes": resources.get("containers_sum_peak_mem_bytes"),
        "llm_peak_mem_bytes": per_container("container_peak_mem_bytes"),
        "llm_lifetime_peak_mem_bytes": per_container("container_lifetime_peak_mem_bytes"),
        "llm_oom_kills": per_container("container_oom_kills"),
        "docker_host_swap_growth_bytes": resources.get("docker_host_swap_growth_bytes"),
    }


def variant_summary(
    variant: Variant,
    *,
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
        "name": candidate["plan_name"],
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
        "contract": contract_headline(contract_report),
        "eval": eval_headline(eval_report),
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
) -> dict[str, Any]:
    return {
        "kind": REPORT_KIND,
        "schema_version": SCHEMA_VERSION,
        "label": SUMMARY_LABEL,
        "catalog": catalog,
        "run": run,
        "machine": machine or {},
        "variants": variants,
    }


def _rate_text(value: Any) -> str:
    if not isinstance(value, dict) or not value.get("n"):
        return MISSING
    return f"{value['correct']}/{value['n']} ({value['pct']:.1f}%)"


def _gib(value: Any) -> str:
    return f"{value / GIB:.2f} GiB" if isinstance(value, (int, float)) and value else MISSING


def _number(value: Any, digits: int = 1) -> str:
    return f"{value:.{digits}f}" if isinstance(value, (int, float)) and not isinstance(value, bool) else MISSING


def _median(value: Any) -> str:
    return _number(value.get("median")) if isinstance(value, dict) else MISSING


def _speed(variant: dict[str, Any], test: str, depth: int = 0) -> str:
    speeds = (variant.get("llama_bench") or {}).get("speeds") or []
    found = next((s for s in speeds if s["test"] == test and s["depth"] == depth), None)
    return _number(found["tps"]) if found else MISSING


def _model_cell(variant: dict[str, Any]) -> str:
    suffix = " (baseline)" if variant["role"] == "baseline" else ""
    return f"{variant['name']}{suffix}"


def _gguf_cell(variant: dict[str, Any]) -> str:
    return f"{variant['quant']}, {variant['publisher']}"


def _process_peak(variant: dict[str, Any]) -> Any:
    peaks = [
        (snapshot.get("process") or {}).get("vm_hwm_bytes")
        for snapshot in (variant.get("memory") or {}).values()
        if isinstance(snapshot, dict)
    ]
    known = [peak for peak in peaks if isinstance(peak, int)]
    return max(known) if known else None


def _cgroup_peak(variant: dict[str, Any]) -> Any:
    peaks = [
        snapshot.get("cgroup_peak_bytes")
        for snapshot in (variant.get("memory") or {}).values()
        if isinstance(snapshot, dict)
    ]
    known = [peak for peak in peaks if isinstance(peak, int)]
    return max(known) if known else None


def _oom_kills(variant: dict[str, Any]) -> str:
    counts = [
        snapshot.get("oom_kills")
        for snapshot in (variant.get("memory") or {}).values()
        if isinstance(snapshot, dict)
    ]
    known = [count for count in counts if isinstance(count, int)]
    return str(max(known)) if known else MISSING


def _quality_row(variant: dict[str, Any]) -> str:
    contract = variant.get("contract") or {}
    chat = variant.get("eval") or {}
    reviewed = chat.get("answer_correct_reviewed_pct")
    cells = [
        _model_cell(variant),
        _gguf_cell(variant),
        variant["licence"],
        _rate_text(contract.get("json_valid")),
        str(contract["thought_first"]) if isinstance(contract.get("thought_first"), int) else MISSING,
        _rate_text(contract.get("status_correct")),
        _rate_text(contract.get("answer_correct_auto")),
        _rate_text(contract.get("source_correct_auto")),
        _rate_text(chat.get("answer_correct_auto")),
        f"{reviewed:.1f}%" if isinstance(reviewed, (int, float)) else MISSING,
        _rate_text(chat.get("source_correct_auto")),
    ]
    return "| " + " | ".join(cells) + " |"


def _speed_row(variant: dict[str, Any]) -> str:
    contract = variant.get("contract") or {}
    chat = variant.get("eval") or {}
    cells = [
        _model_cell(variant),
        _gguf_cell(variant),
        _gib(variant["size_bytes"]),
        _speed(variant, "pp512"),
        _speed(variant, "pp2048"),
        _speed(variant, "tg128"),
        _speed(variant, "tg128", 4096),
        _median(contract.get("wall_s")),
        _median(chat.get("total_s")),
        _median(chat.get("ttft_s")),
        _gib(_process_peak(variant)),
        _gib(_cgroup_peak(variant)),
        _gib(chat.get("stack_peak_mem_bytes")),
        _oom_kills(variant),
    ]
    return "| " + " | ".join(cells) + " |"


def _evaluation_name(variants: list[dict[str, Any]]) -> str:
    counts = sorted({(variant.get("eval") or {}).get("questions") for variant in variants} - {None})
    if len(counts) == 1:
        return f"the {counts[0]}-question evaluation"
    if counts:
        return f"the evaluation ({counts[0]} to {counts[-1]} questions)"
    return "the evaluation"


def markdown_summary(report: dict[str, Any]) -> str:
    run = report.get("run") or {}
    catalog = report.get("catalog") or {}
    machine = report.get("machine") or {}
    variants = report.get("variants") or []
    lines = [
        f"# Model candidates, {str(run.get('started_at') or '')[:10]}",
        "",
        f"Catalog `{catalog.get('path')}` version {catalog.get('version')}, llama.cpp "
        f"{catalog.get('pinned_build')}, reasoning `{run.get('reasoning')}`, steps "
        f"{', '.join(run.get('steps') or [])}. Machine: {machine.get('reference') or MISSING}, "
        f"{machine.get('cpu_model') or MISSING}, {machine.get('ram') or MISSING}. "
        f"Run {'completed' if run.get('completed') else 'not completed'}.",
        "",
        "## Reliability and answers",
        "",
        "JSON valid: replies to the B-98 request that parse and validate against the schema sent. "
        "Probe columns come from the direct contract probe, chat columns from "
        f"{_evaluation_name(variants)}.",
        "",
        "| Model | GGUF | Licence | JSON valid | Thought first | Status correct | Answer correct (probe) | "
        "Source correct (probe) | Answer correct (chat, auto) | Answer correct (reviewed) | Source correct (chat) |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        *[_quality_row(variant) for variant in variants],
        "",
        "## Speed and memory",
        "",
        "llama-bench tokens per second with an f16 KV cache, best thread count, depth 0 unless named. "
        "Medians in seconds. llm VmHWM and cgroup peak: the candidate llama-server; stack peak: the evaluation's "
        "`stack_peak_mem_bytes`, the ADR-006 `P`: the peak memory of the whole stack, model pages included.",
        "",
        "| Model | GGUF | File | pp512 | pp2048 | tg128 | tg128 @ 4096 | Probe reply | Chat answer | "
        "Chat first token | llm VmHWM | llm cgroup peak | Stack peak | OOM kills |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        *[_speed_row(variant) for variant in variants],
    ]
    flagged = [v for v in variants if v.get("licence_flags")]
    if flagged:
        lines += ["", "## Licence flags", ""]
        seen: set[str] = set()
        for variant in flagged:
            if variant["candidate"] in seen:
                continue
            seen.add(variant["candidate"])
            for flag in variant["licence_flags"]:
                lines.append(f"- {variant['name']}: {flag}")
    troubled = [v for v in variants if v.get("problems")]
    if troubled:
        lines += ["", "## Problems", ""]
        for variant in troubled:
            for problem in variant["problems"]:
                lines.append(f"- `{variant['id']}`: {problem}")
    return "\n".join(lines) + "\n"
