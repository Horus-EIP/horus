import importlib.util
import json
import math

import jsonschema
import pytest
from conftest import SERVICE_MODELS
from model_server import EMBEDDING_REQUESTS, MAS_PROMPTS, SERVICES, recorded

MAS = recorded("mas.json")
AGENT = recorded("agent.json")
EMBEDDED = [(service, entry) for service, entries in EMBEDDING_REQUESTS.items() for entry in entries]
ANSWERED_BY = {
    "What was our Q4 2025 revenue?": "1_Q4_2025_Financial_Report.md",
    "How many vacation days can be carried over?": "2_Employee_Handbook.md",
}
SAME_VECTOR = 0.999
FACTUAL = (
    "What was our Q4 2025 revenue?",
    "What is the capital of Peru?",
    "How many vacation days can be carried over?",
)
REVIEW_DECISIONS = {"CONTINUE", "INSERT", "DONE"}


def mas_prompts():
    spec = importlib.util.spec_from_file_location("mas_prompts", MAS_PROMPTS)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CLEAN_JSON = mas_prompts().clean_json_output


def entries(source: list[dict], *names: str) -> list[dict]:
    return [entry for entry in source if entry["name"] in names]


def named(entry: dict) -> str:
    return f"{entry['name']}: {entry['question'][:40]}"


def agent_entry(name: str) -> dict:
    return next(entry for entry in AGENT if entry["name"] == name)


def schema_of(entry: dict) -> dict:
    return entry["body"]["response_format"]["json_schema"]["schema"]


@pytest.mark.parametrize("entry", entries(MAS, "route") + AGENT, ids=named)
def test_every_structured_reply_is_valid_against_its_schema(server, entry):
    jsonschema.validate(json.loads(server.content(entry)), schema_of(entry))


@pytest.mark.parametrize("entry", entries(MAS, "intent", "plan", "review"), ids=named)
def test_every_json_text_reply_is_one_mas_can_read(server, entry):
    reply = json.loads(CLEAN_JSON(server.content(entry)))
    assert isinstance(reply, dict)
    if entry["name"] == "plan":
        assert reply["sub_tasks"]
        assert all(step["agent_type"] and step["description"] for step in reply["sub_tasks"])
    if entry["name"] == "review":
        assert str(reply.get("decision") or "CONTINUE").upper() in REVIEW_DECISIONS


@pytest.mark.parametrize(
    "entry", [entry for entry in entries(MAS, "intent") if entry["question"] in FACTUAL], ids=named
)
def test_no_factual_question_is_answered_directly(server, entry):
    reply = json.loads(CLEAN_JSON(server.content(entry)))
    assert reply.get("classification") != "DIRECT_ANSWER", reply


def test_an_answer_cites_the_passages_it_uses(server):
    entry = agent_entry("in_corpus")
    reply = json.loads(server.content(entry))
    assert reply["status"] == "ok", reply
    assert reply["sources"], reply
    assert set(reply["sources"]) <= set(schema_of(entry)["properties"]["sources"]["items"]["enum"])


@pytest.mark.parametrize("name", ["out_of_corpus", "no_passages"])
def test_a_question_the_documents_do_not_answer_is_refused(server, name):
    reply = json.loads(server.content(agent_entry(name)))
    assert reply["status"] == "not_found", reply
    assert "lima" not in reply["answer"].lower()


def cosine(first: list[float], second: list[float]) -> float:
    dot = sum(a * b for a, b in zip(first, second, strict=True))
    return dot / math.sqrt(sum(a * a for a in first) * sum(b * b for b in second))


def embedded(pair: tuple[str, dict]) -> str:
    service, entry = pair
    about = entry.get("question") or entry.get("document") or f"{len(entry['body']['input'])} texts"
    return f"{service} {entry['name']}: {about[:40]}"


@pytest.mark.parametrize("pair", EMBEDDED, ids=embedded)
def test_every_text_gets_one_vector_of_the_size_its_service_needs(embeddings, pair):
    service, entry = pair
    vectors = embeddings(service).vectors(entry)
    assert len(vectors) == len(entry["body"]["input"])
    for vector in vectors:
        assert len(vector) == entry["size"]
        assert all(isinstance(value, int | float) and math.isfinite(value) for value in vector)
        assert any(vector)


@pytest.mark.parametrize("service", EMBEDDING_REQUESTS)
def test_the_same_texts_get_the_same_vectors(embeddings, service):
    entry = EMBEDDING_REQUESTS[service][-1]
    first, again = (embeddings(service).vectors(entry) for _ in range(2))
    assert all(cosine(a, b) >= SAME_VECTOR for a, b in zip(first, again, strict=True))


@pytest.mark.parametrize("question, document", ANSWERED_BY.items())
def test_a_question_is_closest_to_a_passage_of_the_document_that_answers_it(embeddings, question, document):
    server = embeddings("knowledge_store")
    entries = EMBEDDING_REQUESTS["knowledge_store"]
    passages = [(entry["document"], vector) for entry in entries if entry["name"] == "passages"
                for vector in server.vectors(entry)]
    (asked,) = server.vectors(next(entry for entry in entries if entry.get("question") == question))
    closest = max(passages, key=lambda passage: cosine(asked, passage[1]))
    assert closest[0] == document


@pytest.mark.parametrize("service", EMBEDDING_REQUESTS)
def test_the_recorded_requests_ask_for_a_size_only_when_llm_mock_needs_it(mock_embeddings, service):
    asked = {"dimensions" in entry["body"] for entry in EMBEDDING_REQUESTS[service]}
    assert asked == {mock_embeddings(service).client.send_dimensions}


@pytest.mark.parametrize("service, setup", [
    ("mas", "mas/core/embedding_setup.py"),
    ("knowledge_store", "knowledge-store/app/chroma_db/setup.py"),
])
def test_a_real_server_is_asked_for_the_model_the_service_asks_for_by_default(service, setup):
    assert f'"{SERVICE_MODELS[service]}"' in (SERVICES / setup).read_text(encoding="utf-8")
