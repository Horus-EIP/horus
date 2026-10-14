import re
from collections.abc import Sequence

from tasks.arithmetic import arithmetic_answer
from tasks.intent_rules import TrivialIntent, trivial_clauses

ASSISTANT_NAME = "Horus"
GREETING_REPLY = "Hello!"
OPEN_OFFER = "What can I help you with?"
FOLLOW_UP_OFFER = "What else can I help you with?"
ACKNOWLEDGEMENT_REPLY = "Glad to help."

_HOW_ARE_YOU = re.compile(
    r"\bhow\s+(?:are|r)\s+(?:you|u)\b|\bhow(?:'s|s|\s+is)\s+it\s+going\b"
    r"|\bhow\s+have\s+you\s+been\b|\bhow\s+do\s+you\s+do\b|\bwhat'?s\s+up\b|\bsup\b|\bwh?assup\b"
)
_MEETING = re.compile(r"\b(?:nice|pleased)\s+to\s+meet\s+you\b")
_IDENTITY = re.compile(
    r"\bwho\s+are\s+you\b|\bwhat\s+are\s+you\b|\byour\s+name\b|\bwhat\s+can\s+you\s+do\b"
    r"|\bare\s+you\s+there\b"
)
_THANKS = re.compile(r"\bthank|\bthx\b|\bty\b|\bcheers\b|\bappreciate")
_CLOSING = re.compile(
    r"\bthat(?:'s|\s+is|\s+will\s+be|'ll\s+be)\s+all\b|\bnothing\s+else\b"
)
_FAREWELL = re.compile(
    r"\b(?:good\s*)?bye\b|\bsee\s+(?:you|ya)\b|\bgood\s+night\b|\btake\s+care\b"
)


def direct_answer(text: str | None, agent_names: Sequence[str] = ()) -> str | None:
    clauses = trivial_clauses(text)
    if not clauses:
        return None
    expressions = [
        clause.text for clause in clauses if clause.intent is TrivialIntent.ARITHMETIC
    ]
    if expressions:
        return _arithmetic_reply(expressions)
    greeted = any(clause.intent is TrivialIntent.GREETING for clause in clauses)
    small_talk = " ".join(
        clause.text for clause in clauses if clause.intent is TrivialIntent.SMALL_TALK
    )
    return _small_talk_reply(greeted, small_talk, agent_names)


def _arithmetic_reply(expressions: list[str]) -> str | None:
    answers = [arithmetic_answer(expression) for expression in expressions]
    if any(answer is None for answer in answers):
        return None
    return "\n".join(answers)


def _small_talk_reply(
    greeted: bool, small_talk: str, agent_names: Sequence[str]
) -> str:
    thanked = bool(_THANKS.search(small_talk))
    leaving = bool(_CLOSING.search(small_talk) or _FAREWELL.search(small_talk))
    sentences: list[str] = []
    if greeted and not (thanked or leaving):
        sentences.append(GREETING_REPLY)
    if _HOW_ARE_YOU.search(small_talk):
        sentences.append("I'm doing well, thanks for asking.")
    if _MEETING.search(small_talk):
        sentences.append("Nice to meet you too!")
    if _IDENTITY.search(small_talk):
        sentences.append(_identity_sentence(agent_names))
    if thanked:
        sentences.append("You're welcome!")
    if _CLOSING.search(small_talk):
        sentences.append("Have a good day.")
    if _FAREWELL.search(small_talk):
        sentences.append("Goodbye, and come back any time.")
    acknowledged = small_talk and not sentences
    if acknowledged:
        sentences.append(ACKNOWLEDGEMENT_REPLY)
    if not leaving:
        sentences.append(FOLLOW_UP_OFFER if thanked or acknowledged else OPEN_OFFER)
    return " ".join(sentences)


def _identity_sentence(agent_names: Sequence[str]) -> str:
    sentence = (
        f"I'm {ASSISTANT_NAME}, a multi-agent assistant: I pass each question to the "
        "specialist agent best placed to answer it"
    )
    if agent_names:
        return f"{sentence} ({', '.join(agent_names)})."
    return f"{sentence}."
