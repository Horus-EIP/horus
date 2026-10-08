# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import json
import re
from typing import Any

from horus_bench_kit.llama_bench import CONTAINER_MODELS_DIR, MODELS_DIR_PLACEHOLDER

DEFAULT_PORT = 8080
DEFAULT_CACHE_TYPE = "f16"
SERVER_PROCESS_NAME = "llama-server"
CANDIDATE_CONTAINER = "hbk-candidate"
LLM_COUNTERS = {
    "prompt_tokens": "llamacpp:prompt_tokens_total",
    "prompt_s": "llamacpp:prompt_seconds_total",
    "generated_tokens": "llamacpp:tokens_predicted_total",
    "generation_s": "llamacpp:tokens_predicted_seconds_total",
    "decode_calls": "llamacpp:n_decode_total",
}
COUNTED_LLM_VALUES = frozenset({"prompt_tokens", "generated_tokens", "decode_calls"})
SERVER_FLAGS = {
    "-m": "model",
    "--model": "model",
    "-a": "alias",
    "--alias": "alias",
    "--port": "port",
    "-c": "ctx_size",
    "--ctx-size": "ctx_size",
    "-ctk": "cache_type_k",
    "--cache-type-k": "cache_type_k",
    "-ctv": "cache_type_v",
    "--cache-type-v": "cache_type_v",
    "-cram": "cache_ram_mib",
    "--cache-ram": "cache_ram_mib",
    "-t": "threads",
    "--threads": "threads",
    "-np": "parallel",
    "--parallel": "parallel",
    "-fa": "flash_attn",
    "--flash-attn": "flash_attn",
    "--load-mode": "load_mode",
}
INTEGER_SETTINGS = frozenset({"port", "ctx_size", "cache_ram_mib", "threads", "parallel"})
MEMORY_STAT_FIELDS = ("anon", "file", "active_file", "inactive_file", "file_mapped")
MODEL_FLAGS = frozenset({"-m", "--model"})
REASONING_FLAGS = frozenset({"-rea", "--reasoning"})
REASONING_MODES = ("off", "on", "auto")
PROCESS_MEMORY_FIELDS = {
    "VmHWM": "vm_hwm_bytes",
    "VmRSS": "vm_rss_bytes",
    "RssAnon": "rss_anon_bytes",
    "RssFile": "rss_file_bytes",
}

PROMETHEUS_LINE = re.compile(r"^([A-Za-z_:][A-Za-z0-9_:]*)(\{[^}]*\})?\s+(\S+)")
_BUILD = re.compile(r"(?:^|[^0-9A-Za-z])b?(\d{3,})(?:$|[^0-9])")
_STATUS_FIELD = re.compile(r"^(\w+):\s+(\d+)\s*kB\s*$")


def parse_prometheus(text: str | None) -> dict[str, float]:
    values: dict[str, float] = {}
    for line in (text or "").splitlines():
        match = PROMETHEUS_LINE.match(line.strip())
        if not match or match.group(2):
            continue
        try:
            values[match.group(1)] = float(match.group(3))
        except ValueError:
            continue
    return values


def llm_usage(before: dict[str, float] | None, after: dict[str, float] | None) -> dict[str, Any] | None:
    if not before or not after:
        return None
    usage: dict[str, Any] = {}
    for key, name in LLM_COUNTERS.items():
        if name not in before or name not in after:
            continue
        delta = after[name] - before[name]
        if delta < 0:
            return {"restarted": True}
        usage[key] = int(round(delta)) if key in COUNTED_LLM_VALUES else round(delta, 3)
    if "prompt_s" not in usage:
        return None
    usage["prompt_tps"] = token_rate(usage.get("prompt_tokens"), usage.get("prompt_s"))
    usage["generation_tps"] = token_rate(usage.get("generated_tokens"), usage.get("generation_s"))
    return usage


def token_rate(tokens: float | None, seconds: float | None) -> float | None:
    if not tokens or not seconds:
        return None
    return round(tokens / seconds, 2)


def parse_server_args(args: list[Any] | None) -> dict[str, Any]:
    settings: dict[str, Any] = {}
    items = [str(arg) for arg in args or []]
    index = 0
    while index < len(items):
        flag, value = items[index], None
        if flag.startswith("--") and "=" in flag:
            flag, value = flag.split("=", 1)
        key = SERVER_FLAGS.get(flag)
        if key and value is None and index + 1 < len(items):
            index += 1
            value = items[index]
        if key and value is not None:
            settings[key] = int(value) if key in INTEGER_SETTINGS and _is_integer(value) else value
        index += 1
    settings.setdefault("cache_type_k", DEFAULT_CACHE_TYPE)
    settings.setdefault("cache_type_v", DEFAULT_CACHE_TYPE)
    return settings


def _is_integer(value: str) -> bool:
    return value.lstrip("-").isdigit()


def parse_props(text: str | None) -> dict[str, Any]:
    try:
        props = json.loads(text or "")
    except ValueError:
        return {}
    if not isinstance(props, dict):
        return {}
    generation = props.get("default_generation_settings")
    generation = generation if isinstance(generation, dict) else {}
    return {
        "build_info": props.get("build_info"),
        "model_path": props.get("model_path"),
        "n_ctx": generation.get("n_ctx") or props.get("n_ctx"),
        "total_slots": props.get("total_slots"),
    }


def build_tag(text: str | None) -> str | None:
    match = _BUILD.search(text or "")
    return f"b{match.group(1)}" if match else None


def parse_whole_number(text: str | None) -> int | None:
    value = (text or "").strip()
    return int(value) if value.isdigit() else None


def _name_counts(text: str | None) -> dict[str, int]:
    counts: dict[str, int] = {}
    for line in (text or "").splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].isdigit():
            counts[parts[0]] = int(parts[1])
    return counts


def parse_memory_events(text: str | None) -> dict[str, int]:
    return _name_counts(text)


def parse_memory_stat(text: str | None) -> dict[str, int] | None:
    counts = _name_counts(text)
    if any(field not in counts for field in MEMORY_STAT_FIELDS):
        return None
    return {field: counts[field] for field in MEMORY_STAT_FIELDS}


def parse_process_status(text: str | None) -> dict[str, Any] | None:
    fields = {}
    for line in (text or "").splitlines():
        key, _, rest = line.partition(":")
        fields[key.strip()] = rest.split()
    if not fields.get("Name"):
        return None
    rss_file = fields.get("RssFile") or []
    return {
        "name": " ".join(fields["Name"]),
        "rss_file_bytes": int(rss_file[0]) * 1024 if rss_file and rss_file[0].isdigit() else None,
    }


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


def parse_memory_limit(text: str | None) -> int | None:
    match = re.match(r"^\s*(\d+(?:\.\d+)?)\s*([kmgt]?)b?\s*$", str(text or ""), re.IGNORECASE)
    if not match:
        return None
    scale = {"": 1, "k": 2**10, "m": 2**20, "g": 2**30, "t": 2**40}[match.group(2).lower()]
    return int(float(match.group(1)) * scale)


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


def candidate_network(networks: list[str], preferred_suffix: str | None = None) -> str | None:
    preferred = [name for name in networks if preferred_suffix and name.endswith(preferred_suffix)]
    return (preferred or networks or [None])[0]


def candidate_run_command(
    *,
    image: str,
    models_dir: str,
    args: list[str],
    memory_bytes: int | None,
    name: str = CANDIDATE_CONTAINER,
    network: str | None = None,
    alias: str | None = None,
    publish: str | None = None,
) -> list[str]:
    command = ["docker", "run", "-d", "--name", name]
    if network:
        command += ["--network", network]
    if alias:
        command += ["--network-alias", alias]
    if publish:
        command += ["-p", publish]
    if memory_bytes:
        command += ["--memory", str(memory_bytes), "--memory-swap", str(memory_bytes)]
    return [*command, "-v", f"{models_dir}:{CONTAINER_MODELS_DIR}:ro", image, *args]
