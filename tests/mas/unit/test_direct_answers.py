from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from tasks.direct_answers import direct_answer

EVAL_TESTSET = Path(__file__).resolve().parents[2] / "eval" / "testset.yaml"
AGENTS = ["General-Assistant", "Finance-Analyst"]


@pytest.mark.parametrize(
    ("text", "reply"),
    [
        ("hello", "Hello! What can I help you with?"),
        ("Good morning, Horus", "Hello! What can I help you with?"),
        (
            "Hi, how are you today?",
            "Hello! I'm doing well, thanks for asking. What can I help you with?",
        ),
        ("Thanks a lot!", "You're welcome! What else can I help you with?"),
        ("Hello Horus! Thank you.", "You're welcome! What else can I help you with?"),
        ("Thanks, that's all for now.", "You're welcome! Have a good day."),
        ("bye", "Goodbye, and come back any time."),
        ("goodbye", "Goodbye, and come back any time."),
        ("ok", "Glad to help. What else can I help you with?"),
        ("nice to meet you", "Nice to meet you too! What can I help you with?"),
    ],
)
def test_greetings_and_small_talk_get_a_fixed_reply(text, reply):
    assert direct_answer(text, AGENTS) == reply


def test_who_are_you_names_the_agents_that_are_online():
    reply = direct_answer("who are you?", AGENTS)

    assert reply.startswith("I'm Horus, a multi-agent assistant")
    assert "(General-Assistant, Finance-Analyst)" in reply
    assert reply.endswith("What can I help you with?")


def test_who_are_you_without_agents_online_names_none():
    assert "(" not in direct_answer("what can you do?", [])


@pytest.mark.parametrize(
    ("text", "reply"),
    [
        ("What is 2 + 2?", "2 + 2 = 4"),
        ("what's 12 multiplied by 7", "12 multiplied by 7 = 84"),
        ("hi, what is 100 divided by 4?", "100 divided by 4 = 25"),
        ("calculate 15% of 200", "15% of 200 = 30"),
        ("2+2; 3*3", "2+2 = 4\n3*3 = 9"),
        ("what is 1/0", "1/0 is undefined: a number cannot be divided by zero."),
    ],
)
def test_arithmetic_is_computed_not_generated(text, reply):
    assert direct_answer(text, AGENTS) == reply


@pytest.mark.parametrize(
    "text",
    [
        "What is the capital of Peru?",
        "hello, what does the IT security policy say about passwords?",
        "what is 555-1234",
        "what is 50% + 10",
        "what is 9^9^9",
        "",
        None,
    ],
)
def test_anything_else_has_no_direct_answer(text):
    assert direct_answer(text, AGENTS) is None


def _eval_direct_items():
    if not EVAL_TESTSET.exists():
        return []
    items = yaml.safe_load(EVAL_TESTSET.read_text(encoding="utf-8"))["items"]
    return [
        pytest.param(item["question"], item["answer_patterns"], id=item["id"])
        for item in items
        if item["id"].startswith("direct-")
    ]


@pytest.mark.parametrize(("question", "patterns"), _eval_direct_items())
def test_the_eval_set_direct_questions_get_an_answer_that_passes_their_patterns(question, patterns):
    reply = direct_answer(question, AGENTS)

    assert reply is not None
    for pattern in patterns:
        assert re.search(pattern, reply, re.IGNORECASE), (pattern, reply)
