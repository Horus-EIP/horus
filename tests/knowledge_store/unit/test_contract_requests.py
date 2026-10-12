from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
from unittest.mock import MagicMock

from app.chroma_db import setup
from app.chroma_db.embeddings_client import EmbeddingsClient
from app.chroma_db.services import file_service

REPO = Path(__file__).resolve().parents[3]
REQUESTS = REPO / "tests" / "contract" / "requests" / "knowledge_store.json"
DEMO = REPO / "demo_assets"
UPDATE = os.environ.get("HORUS_UPDATE_CONTRACT_REQUESTS") == "1"
MOCK_EMBED_URL = "http://llm-mock:8080/v1"
MOCK_EMBED_MODEL = "horus-mock"
LLM_MOCK_SIZE = 768
DOCUMENTS = ("1_Q4_2025_Financial_Report.md", "2_Employee_Handbook.md")
QUESTIONS = ("What was our Q4 2025 revenue?", "How many vacation days can be carried over?")


def embeddings_requests_the_knowledge_store_sends(monkeypatch) -> list[dict]:
    sent = []

    def post(self, body, timeout=None):
        sent.append(body)
        size = body.get("dimensions", LLM_MOCK_SIZE)
        return {"data": [{"index": index, "embedding": [1.0] + [0.0] * (size - 1)}
                         for index in range(len(body["input"]))]}

    monkeypatch.setenv("KNOWLEDGE_STORE_EMBED_URL", MOCK_EMBED_URL)
    monkeypatch.setenv("KNOWLEDGE_STORE_EMBED_MODEL", MOCK_EMBED_MODEL)
    monkeypatch.setattr(EmbeddingsClient, "post", post)
    spec = importlib.util.spec_from_file_location("setup_for_the_contract", Path(setup.__file__))
    served = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(served)
    monkeypatch.setattr(file_service, "knowledge_collection", MagicMock())
    monkeypatch.setattr(file_service, "entries_of", lambda doc_id: [])
    monkeypatch.setattr(file_service, "get_embeddings", served.get_embeddings)
    entries = []

    def add(name: str, build, **about) -> None:
        sent.clear()
        build()
        entries.extend({"name": name, **about, "size": served.EMBED_DIMENSIONS, "body": body} for body in sent)

    for title in DOCUMENTS:
        text = (DEMO / title).read_text(encoding="utf-8")
        add("passages", lambda t=text, d=title: file_service._replace_document(d, t, {}, {}, ()),
            document=title)
    for question in QUESTIONS:
        add("query", lambda q=question: served.get_embedding(q, is_query=True), question=question)
    return entries


def test_the_contract_tests_send_what_the_knowledge_store_embeds(monkeypatch):
    built = embeddings_requests_the_knowledge_store_sends(monkeypatch)
    if UPDATE:
        REQUESTS.write_text(json.dumps(built, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    recorded = json.loads(REQUESTS.read_text(encoding="utf-8"))
    assert recorded == built, (
        "The knowledge store's embeddings requests changed. Run HORUS_UPDATE_CONTRACT_REQUESTS=1 "
        "pytest tests/knowledge_store/unit/test_contract_requests.py, then the contract tests "
        "(tests/contract).")


def test_passages_and_questions_go_to_llm_mock_at_its_own_size_without_the_bge_prefix(monkeypatch):
    built = embeddings_requests_the_knowledge_store_sends(monkeypatch)
    assert [entry["name"] for entry in built].count("query") == len(QUESTIONS)
    assert {entry["document"] for entry in built if entry["name"] == "passages"} == set(DOCUMENTS)
    assert not any("dimensions" in entry["body"] for entry in built)
    assert not any(setup.BGE_QUERY_PREFIX in text for entry in built for text in entry["body"]["input"])
