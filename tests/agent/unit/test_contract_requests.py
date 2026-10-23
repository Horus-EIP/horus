from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from agent_server import profiles
from ai_agents.decision_making_agent import DecisionMakingAgent
from ai_agents.rag_pipeline import RAGPipeline

REPO = Path(__file__).resolve().parents[3]
REQUESTS = REPO / "tests" / "contract" / "requests" / "agent.json"
DEMO = REPO / "demo_assets"
UPDATE = os.environ.get("HORUS_UPDATE_CONTRACT_REQUESTS") == "1"
CHUNK_CHARS = 1000
SERVER_ENV = {
    "LLM_BACKEND": "vllm",
    "LLM_VLLM_URL": "http://llm:8080/v1",
    "LLM_VLLM_MODEL": "qwen3-4b",
    "LLM_VLLM_MAX_MODEL_LEN": "8192",
}
UNSET = (
    "AGENT_STREAM_TOKENS",
    "AGENT_RESPONSE_CACHE",
    "AGENT_MAX_NEW_TOKENS",
    "AGENT_MAX_CONTEXT_CHARS",
)
FINANCE = next(p for p in profiles.DEFAULT_PROFILES if p.name == "Finance-Analyst")
QUESTIONS = (
    ("in_corpus", "What was our Q4 2025 revenue?", ("1_Q4_2025_Financial_Report.md",)),
    (
        "out_of_corpus",
        "What is the capital of Peru?",
        ("1_Q4_2025_Financial_Report.md", "2_Employee_Handbook.md"),
    ),
    ("no_passages", "What was our Q4 2025 revenue?", ()),
)


def demo_passages(titles) -> list[dict]:
    passages = []
    for title in titles:
        lines, size, part = [], 0, 0
        for line in (DEMO / title).read_text(encoding="utf-8").splitlines() + [None]:
            if line is None or (lines and size + len(line) > CHUNK_CHARS):
                passages.append(
                    {
                        "chunk_id": f"{title}:{part}",
                        "doc_id": title,
                        "title": title,
                        "page": None,
                        "text": "\n".join(lines),
                    }
                )
                lines, size, part = [], 0, part + 1
            if line is not None:
                lines.append(line)
                size += len(line) + 1
    return passages


def remote_agent() -> DecisionMakingAgent:
    agent = DecisionMakingAgent.__new__(DecisionMakingAgent)
    agent.model_name = "Qwen/Qwen3-4B-Instruct-2507"
    agent.device = "cpu"
    agent.decision_model = None
    agent._causal_tokenizer = None
    agent._causal_model = None
    agent._last_gen_tokens = None
    agent._last_prompt_tokens = None
    return agent


def streamed_reply() -> MagicMock:
    response = MagicMock()
    response.iter_lines.return_value = [
        b'data: {"choices": [{"index": 0, "delta": {"content": "{\\"status\\": \\"not_found\\", '
        b'\\"answer\\": \\"No.\\", \\"sources\\": []}"}}]}',
        b"data: [DONE]",
    ]
    streamed = MagicMock()
    streamed.__enter__.return_value = response
    return streamed


async def requests_the_agent_sends() -> list[dict]:
    entries = []
    for name, question, titles in QUESTIONS:
        sent = []

        def post(url, **kwargs):
            sent.append((kwargs["json"], kwargs["headers"]["X-Horus-Purpose"]))
            return streamed_reply()

        retrieval = MagicMock()
        retrieval.fetch = AsyncMock(return_value={"passages": demo_passages(titles)})
        env = {key: value for key, value in os.environ.items() if key not in UNSET}
        token = profiles.current_persona.set(FINANCE.system_prompt)
        try:
            with (
                patch.dict(os.environ, {**env, **SERVER_ENV}, clear=True),
                patch("requests.post", post),
            ):
                await RAGPipeline(retrieval, remote_agent()).generate_response(question)
        finally:
            profiles.current_persona.reset(token)
        ((body, purpose),) = sent
        entries.append({"name": name, "purpose": purpose, "question": question, "body": body})
    return entries


async def test_the_contract_tests_send_what_the_agent_sends():
    built = await requests_the_agent_sends()
    if UPDATE:
        REQUESTS.parent.mkdir(parents=True, exist_ok=True)
        REQUESTS.write_text(
            json.dumps(built, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    recorded = json.loads(REQUESTS.read_text(encoding="utf-8"))
    assert recorded == built, (
        "The agent's answer requests changed. Run HORUS_UPDATE_CONTRACT_REQUESTS=1 pytest "
        "tests/agent/unit/test_contract_requests.py, then the contract tests (tests/contract)."
    )


async def test_every_answer_request_is_the_structured_answer_call():
    for entry in await requests_the_agent_sends():
        assert entry["purpose"] == "answer"
        assert entry["body"]["response_format"]["json_schema"]["name"] == "agent_answer"
        assert entry["body"]["stream"] is True
