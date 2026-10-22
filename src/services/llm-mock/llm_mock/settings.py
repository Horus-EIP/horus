import logging
import math
import os
from collections.abc import Mapping
from dataclasses import dataclass

SCENARIOS = ("normal", "slow", "invalid_json", "refuse", "error")
DEFAULT_SCENARIO = "normal"
DEFAULT_LATENCY_MS = 300
DEFAULT_MIN_SCORE = 0.2
DEFAULT_MODEL = "horus-mock"
DEFAULT_PORT = 8080

logger = logging.getLogger("llm_mock")


@dataclass(frozen=True)
class Settings:
    scenario: str = DEFAULT_SCENARIO
    latency_ms: int = DEFAULT_LATENCY_MS
    min_score: float = DEFAULT_MIN_SCORE
    model: str = DEFAULT_MODEL

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "Settings":
        env = os.environ if environ is None else environ
        return cls(
            scenario=_scenario(env.get("HORUS_MOCK_SCENARIO", "")),
            latency_ms=int(_number(env, "HORUS_MOCK_LATENCY_MS", DEFAULT_LATENCY_MS)),
            min_score=_number(env, "HORUS_MOCK_MIN_SCORE", DEFAULT_MIN_SCORE),
            model=env.get("LLM_VLLM_MODEL", "").strip() or DEFAULT_MODEL,
        )


def _scenario(raw: str) -> str:
    value = raw.strip().lower() or DEFAULT_SCENARIO
    if value in SCENARIOS:
        return value
    logger.warning(
        "HORUS_MOCK_SCENARIO=%r is not one of %s; using %s",
        raw,
        ", ".join(SCENARIOS),
        DEFAULT_SCENARIO,
    )
    return DEFAULT_SCENARIO


def _number(env: Mapping[str, str], name: str, default: float) -> float:
    raw = env.get(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        value = -1.0
    if math.isfinite(value) and value >= 0:
        return value
    logger.warning("%s=%r is not a number of 0 or more; using %s", name, raw, default)
    return default
