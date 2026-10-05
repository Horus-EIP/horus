from __future__ import annotations

import json
import re
from typing import Any

LLM_CONTAINER = "llm"
LLM_PORT = 8080
DEFAULT_CACHE_TYPE = "f16"
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

_PROMETHEUS_LINE = re.compile(r"^([A-Za-z_:][A-Za-z0-9_:]*)(\{[^}]*\})?\s+(\S+)")
_BUILD = re.compile(r"(?:^|[^0-9A-Za-z])b?(\d{3,})(?:$|[^0-9])")


def parse_prometheus(text: str | None) -> dict[str, float]:
    values: dict[str, float] = {}
    for line in (text or "").splitlines():
        match = _PROMETHEUS_LINE.match(line.strip())
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
    usage["prompt_tps"] = _rate(usage.get("prompt_tokens"), usage.get("prompt_s"))
    usage["generation_tps"] = _rate(usage.get("generated_tokens"), usage.get("generation_s"))
    return usage


def _rate(tokens: float | None, seconds: float | None) -> float | None:
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


def parse_cgroup_bytes(text: str | None) -> int | None:
    value = (text or "").strip()
    return int(value) if value.isdigit() else None


def parse_memory_events(text: str | None) -> dict[str, int]:
    events: dict[str, int] = {}
    for line in (text or "").splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].isdigit():
            events[parts[0]] = int(parts[1])
    return events
