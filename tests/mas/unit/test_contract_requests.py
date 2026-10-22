from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

import core.llm_setup as llm_setup
from core import embedding_setup, skill_cache
from core.embeddings_client import EmbeddingsClient
from tasks import prompts
from tasks.decomposition import INTENT_CALL, PLAN_CALL, REVIEW_CALL
from tasks.router import (
    ExampleIndex,
    RosterAgent,
    RouterSettings,
    embedding_decision,
    llm_decision,
    load_router_examples,
)

REQUESTS = Path(__file__).resolve().parents[2] / "contract" / "requests" / "mas.json"
EMBEDDING_REQUESTS = REQUESTS.with_name("mas_embeddings.json")
MOCK_EMBED_URL = "http://llm-mock:8080/v1"
MOCK_EMBED_MODEL = "horus-mock"
LLM_MOCK_SIZE = 768
FINANCE_SKILLS = [
    "financial_analysis",
    "quarterly_report_qa",
    "revenue_breakdown",
    "expense_review",
    "budget_summary",
    "knowledge_retrieval",
]
SKILL_DEMAND = "Summarise the Q4 2025 revenue by segment"
UPDATE = os.environ.get("HORUS_UPDATE_CONTRACT_REQUESTS") == "1"
SERVER_ENV = {
    "LLM_BACKEND": "vllm",
    "LLM_VLLM_URL": "http://llm:8080/v1",
    "LLM_VLLM_MODEL": "qwen3-4b",
    "LLM_VLLM_MAX_MODEL_LEN": "8192",
}
AGENTS = (
    (
        "General-Assistant",
        "General-purpose RAG assistant. Default fallback when no specialised "
        "agent matches the demand.",
        "general",
    ),
    (
        "Finance-Analyst",
        "Financial analysis specialist. Grounded in the Q4 2025 Financial Report "
        "and the Expense Policy.",
        "analyst",
    ),
    (
        "Compliance-Officer",
        "Policy and compliance reviewer. Grounded in the Compliance Guidelines "
        "and the IT Security Policy.",
        "analyst",
    ),
    (
        "HR-Assistant",
        "HR specialist. Grounded in the Employee Handbook and the Expense Policy.",
        "general",
    ),
    (
        "Researcher",
        "Multi-source researcher. Pulls and synthesises information across the knowledge store.",
        "researcher",
    ),
)
FACTUAL = (
    "What was our Q4 2025 revenue?",
    "What is the capital of Peru?",
    "How many vacation days can be carried over?",
)
COMPARISON = (
    "Compare our Q4 spend against what the expense policy allows and flag anything out of policy."
)


def captured(build) -> list[tuple[dict, str]]:
    calls = []

    def post(body, call):
        calls.append((body, call))
        return '{"route": "SINGLE_AGENT", "agent": "General-Assistant"}'

    with patch.dict(os.environ, SERVER_ENV), patch.object(llm_setup, "_post_chat_completion", post):
        build()
    return calls


def requests_mas_sends() -> list[dict]:
    roster = [
        RosterAgent(f"id-{n}", name, description, kind)
        for n, (name, description, kind) in enumerate(AGENTS)
    ]
    rows = [(agent.agent_id, agent.name, agent.description, agent.agent_type) for agent in roster]
    entries = []

    def add(name: str, question: str, build) -> None:
        ((body, call),) = captured(build)
        entries.append({"name": name, "purpose": call, "question": question, "body": body})

    settings = RouterSettings.from_env()
    for question in (*FACTUAL, COMPARISON):
        add("route", question, lambda q=question: llm_decision(q, roster, settings))
        add(
            "intent",
            question,
            lambda q=question: llm_setup.ask_llm(
                prompts.get_prompt(q, rows), 1024, call=INTENT_CALL
            ),
        )
    add(
        "plan",
        COMPARISON,
        lambda: llm_setup.ask_llm(
            prompts.get_decomposition_prompt(COMPARISON, rows), 2048, call=PLAN_CALL
        ),
    )
    transcript = (
        "=== Chain transcript (in order) ===\n\n[Step 1 — Finance-Analyst (analyst)]\n"
        "Action: From the Finance-Analyst documents: Q4 spend\nResult:\nQ4 spend was "
        "$3.1M. [Source: 1_Q4_2025_Financial_Report.md]\n\n=== End chain transcript ==="
    )
    for remaining in (
        [],
        [
            {
                "agent_type": "general",
                "description": "From the HR-Assistant documents: the hotel cap",
            }
        ],
    ):
        add(
            "review",
            COMPARISON,
            lambda r=remaining: llm_setup.ask_llm(
                prompts.get_manager_review_prompt(
                    COMPARISON, transcript, r, ["researcher", "analyst"]
                ),
                384,
                call=REVIEW_CALL,
            ),
        )
    return entries


def test_the_contract_tests_send_what_mas_sends():
    built = requests_mas_sends()
    if UPDATE:
        REQUESTS.parent.mkdir(parents=True, exist_ok=True)
        REQUESTS.write_text(
            json.dumps(built, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    recorded = json.loads(REQUESTS.read_text(encoding="utf-8"))
    assert recorded == built, (
        "MAS's model requests changed. Run HORUS_UPDATE_CONTRACT_REQUESTS=1 pytest "
        "tests/mas/unit/test_contract_requests.py, then the contract tests (tests/contract)."
    )


@pytest.mark.parametrize(
    "name, purpose",
    [("route", "task_route"), ("intent", "intent"), ("plan", "plan"), ("review", "review")],
)
def test_each_request_names_its_purpose(name, purpose):
    assert {entry["purpose"] for entry in requests_mas_sends() if entry["name"] == name} == {
        purpose
    }


def sized_like_llm_mock(self, body, timeout=None):
    size = body.get("dimensions", LLM_MOCK_SIZE)
    return {
        "data": [
            {"index": index, "embedding": [1.0] + [0.0] * (size - 1)}
            for index in range(len(body["input"]))
        ]
    }


def embeddings_requests_mas_sends(monkeypatch) -> list[dict]:
    sent = []

    def post(self, body, timeout=None):
        sent.append(body)
        return sized_like_llm_mock(self, body, timeout)

    monkeypatch.setenv(embedding_setup.EMBED_MODEL_ENV, MOCK_EMBED_MODEL)
    monkeypatch.setattr(EmbeddingsClient, "post", post)
    client = embedding_setup._connect_to_embeddings_server(MOCK_EMBED_URL)
    monkeypatch.setattr(embedding_setup, "_embedder", client)
    monkeypatch.setattr(skill_cache, "_rows", [])
    entries = []

    def add(name: str, build, **about) -> None:
        sent.clear()
        build()
        entries.extend(
            {"name": name, **about, "size": embedding_setup.SERVER_DIMENSIONS, "body": body}
            for body in sent
        )

    index = ExampleIndex(load_router_examples())
    roster = [
        RosterAgent(f"id-{n}", name, description, kind)
        for n, (name, description, kind) in enumerate(AGENTS)
    ]
    add("router_examples", index.warm)
    for question in (*FACTUAL, COMPARISON):
        add(
            "route",
            lambda q=question: embedding_decision(q, roster, index, RouterSettings.from_env()),
            question=question,
        )
    finance = next(agent for agent in roster if agent.name == "Finance-Analyst")
    add(
        "skills",
        lambda: skill_cache._rows.extend(
            skill_cache._build_rows_for_agent(
                finance.agent_id, finance.name, FINANCE_SKILLS, finance.description
            )
        ),
    )
    add("skill_demand", lambda: skill_cache.rank_skills(SKILL_DEMAND), question=SKILL_DEMAND)
    return entries


def test_the_contract_tests_send_what_mas_embeds(monkeypatch):
    built = embeddings_requests_mas_sends(monkeypatch)
    if UPDATE:
        EMBEDDING_REQUESTS.write_text(
            json.dumps(built, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    recorded = json.loads(EMBEDDING_REQUESTS.read_text(encoding="utf-8"))
    assert recorded == built, (
        "MAS's embeddings requests changed. Run HORUS_UPDATE_CONTRACT_REQUESTS=1 pytest "
        "tests/mas/unit/test_contract_requests.py, then the contract tests (tests/contract)."
    )


def test_mas_asks_llm_mock_for_its_size_and_embeds_every_kind_of_text(monkeypatch):
    built = embeddings_requests_mas_sends(monkeypatch)
    assert {entry["name"] for entry in built} == {
        "router_examples",
        "route",
        "skills",
        "skill_demand",
    }
    assert all(entry["body"]["dimensions"] == 384 for entry in built)
    assert all(entry["body"]["model"] == MOCK_EMBED_MODEL for entry in built)
