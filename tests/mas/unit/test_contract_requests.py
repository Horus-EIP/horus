from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

import core.llm_setup as llm_setup
from tasks import prompts
from tasks.decomposition import INTENT_CALL, PLAN_CALL, REVIEW_CALL
from tasks.router import RosterAgent, RouterSettings, llm_decision

REQUESTS = Path(__file__).resolve().parents[2] / "contract" / "requests" / "mas.json"
UPDATE = os.environ.get("HORUS_UPDATE_CONTRACT_REQUESTS") == "1"
SERVER_ENV = {
    "LLM_BACKEND": "vllm",
    "LLM_VLLM_URL": "http://llm:8080/v1",
    "LLM_VLLM_MODEL": "qwen3-4b",
    "LLM_VLLM_MAX_MODEL_LEN": "8192",
}
AGENTS = (
    ("General-Assistant", "General-purpose RAG assistant. Default fallback when no specialised "
                          "agent matches the demand.", "general"),
    ("Finance-Analyst", "Financial analysis specialist. Grounded in the Q4 2025 Financial Report "
                        "and the Expense Policy.", "analyst"),
    ("Compliance-Officer", "Policy and compliance reviewer. Grounded in the Compliance Guidelines "
                           "and the IT Security Policy.", "analyst"),
    ("HR-Assistant", "HR specialist. Grounded in the Employee Handbook and the Expense Policy.",
     "general"),
    ("Researcher", "Multi-source researcher. Pulls and synthesises information across the "
                   "knowledge store.", "researcher"),
)
FACTUAL = (
    "What was our Q4 2025 revenue?",
    "What is the capital of Peru?",
    "How many vacation days can be carried over?",
)
COMPARISON = ("Compare our Q4 spend against what the expense policy allows and flag anything "
              "out of policy.")


def captured(build) -> list[tuple[dict, str]]:
    calls = []

    def post(body, call):
        calls.append((body, call))
        return '{"route": "SINGLE_AGENT", "agent": "General-Assistant"}'

    with patch.dict(os.environ, SERVER_ENV), patch.object(llm_setup, "_post_chat_completion", post):
        build()
    return calls


def requests_mas_sends() -> list[dict]:
    roster = [RosterAgent(f"id-{n}", name, description, kind)
              for n, (name, description, kind) in enumerate(AGENTS)]
    rows = [(agent.agent_id, agent.name, agent.description, agent.agent_type) for agent in roster]
    entries = []

    def add(name: str, question: str, build) -> None:
        ((body, call),) = captured(build)
        entries.append({"name": name, "purpose": call, "question": question, "body": body})

    settings = RouterSettings.from_env()
    for question in (*FACTUAL, COMPARISON):
        add("route", question, lambda q=question: llm_decision(q, roster, settings))
        add("intent", question,
            lambda q=question: llm_setup.ask_llm(prompts.get_prompt(q, rows), 1024, call=INTENT_CALL))
    add("plan", COMPARISON, lambda: llm_setup.ask_llm(
        prompts.get_decomposition_prompt(COMPARISON, rows), 2048, call=PLAN_CALL))
    transcript = ("=== Chain transcript (in order) ===\n\n[Step 1 — Finance-Analyst (analyst)]\n"
                  "Action: From the Finance-Analyst documents: Q4 spend\nResult:\nQ4 spend was "
                  "$3.1M. [Source: 1_Q4_2025_Financial_Report.md]\n\n=== End chain transcript ===")
    for remaining in ([], [{"agent_type": "general", "description": "From the HR-Assistant "
                                                                    "documents: the hotel cap"}]):
        add("review", COMPARISON, lambda r=remaining: llm_setup.ask_llm(
            prompts.get_manager_review_prompt(COMPARISON, transcript, r, ["researcher", "analyst"]),
            384, call=REVIEW_CALL))
    return entries


def test_the_contract_tests_send_what_mas_sends():
    built = requests_mas_sends()
    if UPDATE:
        REQUESTS.parent.mkdir(parents=True, exist_ok=True)
        REQUESTS.write_text(json.dumps(built, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    recorded = json.loads(REQUESTS.read_text(encoding="utf-8"))
    assert recorded == built, (
        "MAS's model requests changed. Run HORUS_UPDATE_CONTRACT_REQUESTS=1 pytest "
        "tests/mas/unit/test_contract_requests.py, then the contract tests (tests/contract).")


@pytest.mark.parametrize("name, purpose", [("route", "task_route"), ("intent", "intent"),
                                           ("plan", "plan"), ("review", "review")])
def test_each_request_names_its_purpose(name, purpose):
    assert {entry["purpose"] for entry in requests_mas_sends() if entry["name"] == name} == {purpose}
