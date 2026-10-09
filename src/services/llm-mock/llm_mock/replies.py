import logging
from collections.abc import Callable
from dataclasses import dataclass

from llm_mock import agent_calls, mas_calls
from llm_mock.call import Call
from llm_mock.schemas import broken, dumps, example
from llm_mock.settings import Settings

NEUTRAL_TEXT = "This is a simulated reply: Horus is running in mock AI mode."
ERROR_TEXT = "Simulated model server failure (HORUS_MOCK_SCENARIO=error)."
SLOW_SECONDS = (5.0, 40.0)

Handler = Callable[[Call, Settings], str]

STRUCTURED_CALLS: dict[str, Handler] = {
    "task_route": mas_calls.task_route,
    "agent_answer": agent_calls.agent_answer,
}
TEXT_CALLS: dict[str, Handler] = {
    "intent": mas_calls.intent,
    "plan": mas_calls.plan,
    "announce": mas_calls.announce,
    "review": mas_calls.review,
    "aggregate": mas_calls.aggregate,
}
JSON_TEXT_CALLS = frozenset({"intent", "plan", "review"})

logger = logging.getLogger("llm_mock")


@dataclass(frozen=True)
class Reply:
    content: str = ""
    status: int = 200
    error: str = ""


def reply_to(call: Call, settings: Settings) -> Reply:
    if settings.scenario == "error":
        return Reply(status=500, error=ERROR_TEXT)
    if settings.scenario == "refuse" and agent_calls.is_answer(call):
        return Reply(agent_calls.refusal(call))
    content = answer(call, settings)
    if settings.scenario == "invalid_json" and returns_json(call):
        content = broken(content)
    return Reply(content)


def answer(call: Call, settings: Settings) -> str:
    calls, name = (STRUCTURED_CALLS, call.schema_name) if call.structured else (TEXT_CALLS, call.purpose)
    handler = calls.get(name)
    if handler is None:
        logger.warning(
            "No simulated reply for this call (schema %r, purpose %r): sending a neutral one",
            call.schema_name or None, call.purpose or None,
        )
        return neutral(call)
    try:
        return handler(call, settings)
    except Exception:
        logger.exception("The simulated %s reply failed: sending a neutral one", name)
        return neutral(call)


def neutral(call: Call) -> str:
    return dumps(example(call.schema, NEUTRAL_TEXT)) if call.structured else NEUTRAL_TEXT


def returns_json(call: Call) -> bool:
    return call.structured or call.purpose in JSON_TEXT_CALLS


def delay_seconds(call: Call, settings: Settings) -> float:
    if settings.scenario == "slow":
        low, high = SLOW_SECONDS
        return low + (high - low) * int(call.digest[:8] or "0", 16) / 0xFFFFFFFF
    return settings.latency_ms / 1000
