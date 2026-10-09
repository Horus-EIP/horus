from llm_mock.call import Call
from llm_mock.schemas import dumps
from llm_mock.settings import Settings

REFUSAL = "I don't have that information yet."
ANSWER_SCHEMAS = frozenset({"agent_answer"})
ANSWER_PURPOSES: frozenset[str] = frozenset()


def is_answer(call: Call) -> bool:
    return call.schema_name in ANSWER_SCHEMAS or (
        not call.structured and call.purpose in ANSWER_PURPOSES
    )


def refusal(call: Call) -> str:
    if call.schema_name not in ANSWER_SCHEMAS:
        return REFUSAL
    reply = {"status": "not_found", "answer": REFUSAL}
    if "sources" in (call.schema.get("properties") or {}):
        reply["sources"] = []
    return dumps(reply)


def agent_answer(call: Call, settings: Settings) -> str:
    return refusal(call)
