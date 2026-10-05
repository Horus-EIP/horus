from __future__ import annotations

import time

import pytest

from tasks import intent_rules
from tasks.intent_rules import TrivialIntent, classify_trivial_intent


@pytest.mark.parametrize(
    "text",
    [
        "hello",
        "Hi",
        "hey there",
        "Hello!",
        "Good morning, Horus",
        "hiii",
        "heyyy 👋",
        "Ｈｅｌｌｏ",
        "bonjour",
        "  hello   everyone  ",
    ],
)
def test_greetings_are_classified_as_greeting(text):
    assert classify_trivial_intent(text) is TrivialIntent.GREETING


@pytest.mark.parametrize(
    "text",
    [
        "How are you?",
        "hi, how are you doing today?",
        "Thanks a lot!",
        "thank you so much",
        "thanks for the help",
        "What’s up?",
        "bye",
        "see you later",
        "who are you?",
        "what can you do?",
        "what is your name",
        "ok",
        "nice to meet you",
        "Hello Horus! Thank you.",
    ],
)
def test_small_talk_is_classified_as_small_talk(text):
    assert classify_trivial_intent(text) is TrivialIntent.SMALL_TALK


@pytest.mark.parametrize(
    "text",
    [
        "2+2",
        "what's 2+2?",
        "What is 6x7?",
        "what is 12 * (3 + 4)",
        "calculate 15% of 200",
        "how much is 10 divided by 4?",
        "1,000 + 2,500 =",
        "what is 3.5 times 2",
        "square root of 16",
        "２＋２",
        "hi, what's 2+2?",
        "can you calculate 3*3",
        "4 squared",
        "what is 5 cubed?",
        "what is the square root of 16",
        "√16",
        "15 percent of 200",
        "what is 10 % 3",
        "2 + 2 equals?",
        "what is 7*6 please",
        "2 - -3",
        "(1+2)*(3+4)",
    ],
)
def test_arithmetic_is_classified_as_arithmetic(text):
    assert classify_trivial_intent(text) is TrivialIntent.ARITHMETIC


@pytest.mark.parametrize(
    "text",
    [
        "What is the capital of Peru?",
        "capital of Peru",
        "Hello! What is the capital of Peru?",
        "What was Q4 2025 revenue?",
        "what is 2025?",
        "Summarize the employee handbook",
        "thanks, now compare Q3 and Q4",
        "what is the travel reimbursement limit?",
        "how are the Q4 numbers?",
        "who is the CFO?",
        "what is your refund policy?",
        "what is 2+2 and who is the CFO?",
        "what is x+y",
        "hello, what does the IT security policy say about passwords?",
    ],
)
def test_factual_and_document_questions_are_not_trivial(text):
    assert classify_trivial_intent(text) is None


@pytest.mark.parametrize(
    "text",
    ["what is 1x", "xx+1", "what is 10 percent", "10%", "2025-10-05", "what is 2025-10-05 minus 3"],
)
def test_numbers_without_an_operation_between_operands_are_not_arithmetic(text):
    assert classify_trivial_intent(text) is None


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("thanks! " * 30, id="repeated-small-talk"),
        pytest.param("1+" * 120 + "1", id="long-sum"),
        pytest.param("hello " + "=" * 50_000 + " what is the capital of Peru", id="50k-equals"),
    ],
)
def test_input_longer_than_a_trivial_message_is_not_trivial(text):
    assert classify_trivial_intent(text) is None


def test_repeated_small_talk_within_the_length_limit_is_still_small_talk():
    assert classify_trivial_intent("thanks! " * 20) is TrivialIntent.SMALL_TALK


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("1" + " " * 50_000 + "a", id="spaces"),
        pytest.param("=" * 50_000 + "a", id="equals"),
        pytest.param("= " * 25_000 + "a", id="equals-and-spaces"),
        pytest.param("2 equals " * 6_000 + "a", id="equals-words"),
        pytest.param("1 " * 25_000 + "a", id="numbers-without-operator"),
        pytest.param("1+" + "-" * 50_000 + "a", id="signs"),
        pytest.param("hello " + "=" * 50_000 + " what is the capital of Peru", id="greeting-then-question"),
    ],
)
def test_long_pathological_input_is_classified_quickly_even_without_the_length_limit(
    monkeypatch, text
):
    monkeypatch.setattr(intent_rules, "_MAX_TRIVIAL_LENGTH", len(text))
    started = time.perf_counter()
    assert classify_trivial_intent(text) is None
    assert time.perf_counter() - started < 1.0


@pytest.mark.parametrize("text", ["", "   ", "!!!", "👋", "Horus", None])
def test_empty_symbol_or_addressee_only_input_is_not_trivial(text):
    assert classify_trivial_intent(text) is None


def test_trivial_intent_values_are_plain_strings_for_logging():
    assert [intent.value for intent in TrivialIntent] == [
        "greeting",
        "small_talk",
        "arithmetic",
    ]
