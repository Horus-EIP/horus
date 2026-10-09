import importlib.util
import json

import jsonschema
import pytest
from model_server import MAS_PROMPTS, recorded

MAS = recorded("mas.json")
AGENT = recorded("agent.json")
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
