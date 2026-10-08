from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

KIT_SRC = Path(__file__).resolve().parents[2] / "opensource" / "horus-bench-kit" / "src"
if str(KIT_SRC) not in sys.path:
    sys.path.insert(0, str(KIT_SRC))

from horus_bench_kit.llama_server import (  # noqa: E402, F401
    COUNTED_LLM_VALUES,
    DEFAULT_CACHE_TYPE,
    INTEGER_SETTINGS,
    LLM_COUNTERS,
    MEMORY_STAT_FIELDS,
    PROMETHEUS_LINE,
    SERVER_FLAGS,
    build_tag,
    llm_usage,
    parse_memory_events,
    parse_memory_stat,
    parse_process_status,
    parse_prometheus,
    parse_props,
    parse_server_args,
    parse_whole_number,
)
from horus_bench_kit.llama_server import DEFAULT_PORT as LLM_PORT  # noqa: E402, F401
from horus_bench_kit.llama_server import SERVER_PROCESS_NAME as LLM_PROCESS_NAME  # noqa: E402, F401

LLM_CONTAINER = "llm"
ROUTING_HISTOGRAM = "mas_routing_decision_seconds"
ROUTING_HISTOGRAM_FIELDS = {f"{ROUTING_HISTOGRAM}_count": "count", f"{ROUTING_HISTOGRAM}_sum": "seconds"}
LLM_ROUTING_METHOD = "llm"

_PROMETHEUS_LABEL = re.compile(r'([A-Za-z_][A-Za-z0-9_]*)="((?:[^"\\]|\\.)*)"')


def parse_routing_decisions(text: str | None) -> dict[str, dict[str, float]] | None:
    if f"# TYPE {ROUTING_HISTOGRAM} histogram" not in (text or ""):
        return None
    decisions: dict[str, dict[str, float]] = {}
    for line in text.splitlines():
        match = PROMETHEUS_LINE.match(line.strip())
        field = ROUTING_HISTOGRAM_FIELDS.get(match.group(1)) if match else None
        method = dict(_PROMETHEUS_LABEL.findall(match.group(2) or "")).get("method") if field else None
        if method is None:
            continue
        try:
            value = float(match.group(3))
        except ValueError:
            continue
        decisions.setdefault(method, {"count": 0.0, "seconds": 0.0})[field] = value
    return decisions


def routing_decision(
    before: dict[str, dict[str, float]] | None, after: dict[str, dict[str, float]] | None
) -> dict[str, Any] | None:
    if before is None or after is None:
        return None
    methods: dict[str, int] = {}
    seconds = 0.0
    for method in sorted(before.keys() | after.keys()):
        earlier = before.get(method, {})
        later = after.get(method)
        if later is None:
            return {"restarted": True}
        count = later.get("count", 0.0) - earlier.get("count", 0.0)
        if count < 0:
            return {"restarted": True}
        if count:
            methods[method] = int(round(count))
            seconds += later.get("seconds", 0.0) - earlier.get("seconds", 0.0)
    return {"decisions": sum(methods.values()), "methods": methods, "seconds": round(max(seconds, 0.0), 4)}
