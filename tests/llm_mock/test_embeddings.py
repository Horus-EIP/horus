import json
import math
import os
import subprocess
import sys
from collections import Counter

import pytest
from clients import REPO
from corpus import demo_chunks

from llm_mock import embeddings
from llm_mock.embeddings import DEFAULT_DIMENSIONS, embed, features, slot
from llm_mock.replies import ERROR_TEXT

MOCK = REPO / "src" / "services" / "llm-mock"
QUESTION = "What was our Q4 2025 revenue?"


def cosine(first: list[float], second: list[float]) -> float:
    return sum(a * b for a, b in zip(first, second, strict=True))


def length(vector: list[float]) -> float:
    return math.sqrt(sum(value * value for value in vector))


def post(server, body):
    status, _, raw = server.request("POST", "/v1/embeddings", body)
    return status, json.loads(raw)


def vector_in_a_new_process(text: str, dimensions: int, seed: str) -> list[float]:
    script = ("import json, sys; from llm_mock.embeddings import embed; "
              "print(json.dumps(embed(sys.argv[1], int(sys.argv[2]))))")
    env = {**os.environ, "PYTHONHASHSEED": seed, "PYTHONPATH": str(MOCK)}
    out = subprocess.run([sys.executable, "-B", "-c", script, text, str(dimensions)],
                         capture_output=True, text=True, env=env, check=True)
    return json.loads(out.stdout)


def test_the_same_text_gives_the_same_vector_in_two_processes():
    first = vector_in_a_new_process(QUESTION, 384, "1")
    second = vector_in_a_new_process(QUESTION, 384, "2")
    assert first == second == embed(QUESTION, 384)


@pytest.mark.parametrize("dimensions", [1, 16, 384, 768, 1536])
def test_the_vector_has_the_requested_size_and_unit_length(dimensions):
    vector = embed("FinCorp closed Q4 2025 with total revenue of $4.2M.", dimensions)
    assert len(vector) == dimensions
    assert length(vector) == pytest.approx(1.0)


@pytest.mark.parametrize("text", ["", "   ", "the of and to what was our", "?!"])
def test_a_text_without_words_gets_a_fixed_unit_vector(text):
    vector = embed(text, 384)
    assert length(vector) == pytest.approx(1.0)
    assert vector == embed("", 384)


def test_words_and_word_pairs_are_the_features_with_damped_counts():
    counted = features("Revenue grew. Revenue fell.")
    assert counted["w:revenue"] == 2
    assert counted["p:revenue grew"] == 1
    assert "w:the" not in features("the revenue")
    word, _ = slot("w:revenue", 768)
    pair, _ = slot("p:revenue revenue", 768)
    assert word != pair
    vector = embed("revenue revenue", 768)
    assert abs(vector[word]) / abs(vector[pair]) == pytest.approx(1 + math.log(2))


def test_features_that_cancel_still_give_a_unit_vector(monkeypatch):
    for dimensions in (1, 2):
        assert length(embed("revenue margin profit cash budget", dimensions)) == pytest.approx(1.0)
    monkeypatch.setattr(embeddings, "features", lambda text: Counter({"w:up": 1, "w:down": 1}))
    monkeypatch.setattr(embeddings, "slot",
                        lambda feature, dimensions: (0, -1.0 if feature == "w:down" else 1.0))
    assert embeddings.embed("up down", 4) == [1.0, 0.0, 0.0, 0.0]


def test_a_passage_is_closer_to_a_question_that_shares_its_words():
    chunks = dict(demo_chunks())
    q4 = next(text for title, text in demo_chunks() if "total revenue of **$4.2M**" in text)
    unrelated = chunks["2_Employee_Handbook.md"]
    question = embed(QUESTION, 768)
    assert cosine(question, embed(q4, 768)) > cosine(question, embed(unrelated, 768))
    assert cosine(question, embed(q4, 768)) > 0.1


def test_the_api_answers_a_string_or_a_list_in_order(server):
    status, body = post(server, {"model": "horus-mock", "input": QUESTION, "dimensions": 384})
    assert status == 200
    assert body["object"] == "list"
    assert body["model"] == "horus-mock"
    assert body["data"] == [{"object": "embedding", "index": 0, "embedding": embed(QUESTION, 384)}]
    assert body["usage"]["prompt_tokens"] == body["usage"]["total_tokens"] > 0
    texts = ["first passage about revenue", "second passage about leave", ""]
    status, body = post(server, {"model": "bge", "input": texts, "dimensions": 768})
    assert [item["index"] for item in body["data"]] == [0, 1, 2]
    assert [item["embedding"] for item in body["data"]] == [embed(text, 768) for text in texts]


def test_the_default_size_and_model(mock_server):
    running = mock_server(model="horus-mock")
    status, body = post(running, {"input": "revenue"})
    assert status == 200
    assert len(body["data"][0]["embedding"]) == DEFAULT_DIMENSIONS
    assert body["model"] == "horus-mock"


@pytest.mark.parametrize("body", [
    ["revenue"],
    {"input": []},
    {"model": "m"},
    {"input": ["text", 3]},
    {"input": [[1, 2, 3]]},
    {"input": "text", "dimensions": 0},
    {"input": "text", "dimensions": "384"},
    {"input": "text", "dimensions": True},
    {"input": "text", "dimensions": 10_000},
    {"input": "text", "encoding_format": "base64"},
    {"input": ["x"] * 2049},
])
def test_a_request_the_api_cannot_serve_is_400(server, body):
    status, answer = post(server, body)
    assert status == 400
    assert answer["error"]["type"] == "invalid_request_error"


def test_the_error_scenario_fails_embeddings_too(mock_server):
    status, body = post(mock_server(scenario="error"), {"input": "revenue", "dimensions": 8})
    assert status == 500
    assert body["error"]["message"] == ERROR_TEXT


@pytest.mark.parametrize("scenario", ["slow", "invalid_json", "refuse"])
def test_latency_and_the_other_scenarios_leave_embeddings_alone(mock_server, scenario):
    running = mock_server(scenario=scenario, latency_ms=300)
    status, body = post(running, {"input": "revenue", "dimensions": 8})
    assert status == 200
    assert body["data"][0]["embedding"] == embed("revenue", 8)
    assert running.slept == []
