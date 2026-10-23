from __future__ import annotations

import json
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent_server import profiles
from ai_agents.decision_making_agent import (
    GROUNDED_SYSTEM_PROMPT,
    INSTRUCTION_SYSTEM_PROMPT,
    DecisionMakingAgent,
)
from ai_agents.rag_pipeline import RAGPipeline
from ai_agents.react_agent import ReactAgent

FINANCE = next(
    profile for profile in profiles.DEFAULT_PROFILES if profile.name == "Finance-Analyst"
)
HR = next(profile for profile in profiles.DEFAULT_PROFILES if profile.name == "HR-Assistant")

Q4_PASSAGE = {
    "chunk_id": "doc-q4:2",
    "doc_id": "doc-q4",
    "title": "1_Q4_2025_Financial_Report.md",
    "page": 2,
    "text": "Q4 2025 revenue was $4.2M.",
}
LEAVE_PASSAGE = {
    "chunk_id": "doc-hb:7",
    "doc_id": "doc-hb",
    "title": "2_Employee_Handbook.md",
    "page": None,
    "text": "Up to five unused vacation days carry over.",
}


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


class FakeLlamaServer:
    def __init__(self, replies: list[str], prompt_tokens: int = 412):
        self.replies = list(replies)
        self.prompt_tokens = prompt_tokens
        self.payloads: list[dict] = []
        self.purposes: list[str | None] = []
        self.streamed: list[bool] = []

    def _reply(self) -> str:
        return self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]

    def __call__(self, url, **kwargs):
        self.payloads.append(kwargs["json"])
        self.purposes.append((kwargs.get("headers") or {}).get("X-Horus-Purpose"))
        self.streamed.append(bool(kwargs.get("stream")))
        content = self._reply()
        usage = {"prompt_tokens": self.prompt_tokens, "completion_tokens": 12}
        response = MagicMock()
        if not kwargs.get("stream"):
            response.json.return_value = {
                "choices": [{"message": {"role": "assistant", "content": content}}],
                "usage": usage,
            }
            return response
        events = [
            {"choices": [{"index": 0, "delta": {"content": content}}]},
            {"choices": [], "usage": usage},
        ]
        response.iter_lines.return_value = [
            *(f"data: {json.dumps(event)}".encode() for event in events),
            b"data: [DONE]",
        ]
        streamed = MagicMock()
        streamed.__enter__.return_value = response
        streamed.__exit__.return_value = False
        return streamed

    def system_messages(self) -> list[str]:
        return [payload["messages"][0]["content"] for payload in self.payloads]

    def user_messages(self) -> list[str]:
        return [payload["messages"][1]["content"] for payload in self.payloads]


@pytest.fixture
def llama_server_env(monkeypatch):
    monkeypatch.setenv("LLM_BACKEND", "vllm")
    monkeypatch.setenv("LLM_VLLM_URL", "http://llm:8080/v1")
    monkeypatch.setenv("LLM_VLLM_MAX_MODEL_LEN", "8192")
    monkeypatch.delenv("AGENT_STREAM_TOKENS", raising=False)
    monkeypatch.delenv("AGENT_RESPONSE_CACHE", raising=False)
    return monkeypatch


@contextmanager
def identity(profile):
    persona = profiles.current_persona.set(profile.system_prompt)
    tools = profiles.current_tools.set(profile.tools)
    try:
        yield
    finally:
        profiles.current_tools.reset(tools)
        profiles.current_persona.reset(persona)


def _retrieval(*results: dict) -> MagicMock:
    retrieval = MagicMock()
    retrieval.fetch = AsyncMock(side_effect=list(results))
    return retrieval


ANSWER = json.dumps({"status": "ok", "answer": "Revenue was $4.2M.", "sources": ["S1"]})


class TestAnswerPrompt:
    async def test_one_identity_sends_a_byte_identical_system_message_for_every_question(
        self, llama_server_env
    ):
        server = FakeLlamaServer([ANSWER])
        pipeline = RAGPipeline(
            _retrieval({"passages": [Q4_PASSAGE]}, {"passages": [LEAVE_PASSAGE, Q4_PASSAGE]}),
            remote_agent(),
        )
        with identity(FINANCE), patch("requests.post", server):
            await pipeline.generate_response("What was Q4 2025 revenue?")
            await pipeline.generate_response("How many vacation days carry over?")

        first, second = (system.encode("utf-8") for system in server.system_messages())
        assert first == second
        assert server.system_messages()[0].startswith(FINANCE.system_prompt)
        assert "revenue was" not in server.system_messages()[0].lower()

    async def test_the_passages_come_first_and_the_question_last(self, llama_server_env):
        server = FakeLlamaServer([ANSWER])
        pipeline = RAGPipeline(_retrieval({"passages": [Q4_PASSAGE]}), remote_agent())
        with identity(FINANCE), patch("requests.post", server):
            await pipeline.generate_response("What was Q4 2025 revenue?")

        assert server.user_messages() == [
            "Passages:\n[S1] 1_Q4_2025_Financial_Report.md, page 2\nQ4 2025 revenue was $4.2M."
            "\n\nRequest: What was Q4 2025 revenue?"
        ]

    async def test_each_identity_keeps_its_own_system_message(self, llama_server_env):
        server = FakeLlamaServer([ANSWER])
        pipeline = RAGPipeline(
            _retrieval({"passages": [Q4_PASSAGE]}, {"passages": [LEAVE_PASSAGE]}), remote_agent()
        )
        with patch("requests.post", server):
            with identity(FINANCE):
                await pipeline.generate_response("What was Q4 2025 revenue?")
            with identity(HR):
                await pipeline.generate_response("How many vacation days carry over?")

        finance, hr = server.system_messages()
        assert finance.startswith(FINANCE.system_prompt)
        assert hr.startswith(HR.system_prompt)
        assert finance.split("\n\n---\n\n", 1)[1] == hr.split("\n\n---\n\n", 1)[1]


class TestDecidePrompt:
    def test_the_grounded_rules_are_fixed_and_the_task_closes_the_user_message(
        self, llama_server_env
    ):
        server = FakeLlamaServer(["Revenue was $4.2M."])
        agent = remote_agent()
        with patch("requests.post", server):
            agent.decide("What was Q4 revenue?", context="Q4 2025 revenue was $4.2M.")
            agent.decide("Who approves leave?", context="Your manager approves leave.")

        assert server.system_messages() == [GROUNDED_SYSTEM_PROMPT, GROUNDED_SYSTEM_PROMPT]
        assert server.user_messages()[0] == (
            "Retrieved Content:\nQ4 2025 revenue was $4.2M.\n\nTask: What was Q4 revenue?"
        )
        assert "RULES" in GROUNDED_SYSTEM_PROMPT

    def test_an_instruction_keeps_the_fixed_system_message(self, llama_server_env):
        server = FakeLlamaServer(["A report."])
        with patch("requests.post", server):
            remote_agent().decide("Write a report about Q4.")

        assert server.system_messages() == [INSTRUCTION_SYSTEM_PROMPT]
        assert server.user_messages() == ["Write a report about Q4."]


class TestReactPrompt:
    def _agent(self, retrieval=None) -> ReactAgent:
        return ReactAgent(
            remote_agent(),
            retrieval or _retrieval({"data": "Q4 2025 revenue was $4.2M."}),
            MagicMock(),
            max_steps=3,
        )

    async def test_every_step_sends_the_same_system_message_with_the_identity_tools(
        self, llama_server_env
    ):
        server = FakeLlamaServer(
            [
                "THOUGHT: search.\nACTION: search_knowledge(Q4 revenue)",
                "THOUGHT: done.\nFINAL_ANSWER: Revenue was $4.2M.",
            ]
        )
        with identity(FINANCE), patch("requests.post", server):
            await self._agent().run("What was Q4 2025 revenue?")

        first, second = server.system_messages()
        assert first.encode("utf-8") == second.encode("utf-8")
        assert first.startswith(FINANCE.system_prompt)
        assert "analyze_payments(query)" in first
        assert "extract_data(" not in first
        assert "Q4 2025 revenue" not in first

    async def test_a_later_step_extends_the_earlier_reasoning(self, llama_server_env):
        server = FakeLlamaServer(
            [
                "THOUGHT: search.\nACTION: search_knowledge(Q4 revenue)",
                "THOUGHT: compute.\nACTION: calc(4.2 * 2)",
                "THOUGHT: done.\nFINAL_ANSWER: Twice the revenue is $8.4M.",
            ]
        )
        with identity(FINANCE), patch("requests.post", server):
            await self._agent().run("What is twice the Q4 2025 revenue?")

        step_one, step_two, step_three = server.user_messages()
        assert step_one.startswith("User query: What is twice the Q4 2025 revenue?")
        assert step_three.startswith(step_two.rsplit("\n\nStep ", 1)[0])
        assert step_three.count("Q4 2025 revenue was $4.2M.") == 1

    async def test_a_tool_outside_the_identity_is_refused(self, llama_server_env):
        server = FakeLlamaServer(
            [
                "THOUGHT: parse.\nACTION: extract_data(report.csv, csv)",
                "THOUGHT: done.\nFINAL_ANSWER: I could not parse it.",
            ]
        )
        agent = self._agent()
        with identity(HR), patch("requests.post", server):
            result = await agent.run("Parse report.csv")

        observation = next(
            step for step in result["history"]["steps"] if step["type"] == "OBSERVATION"
        )
        assert observation["content"] == (
            "[Error] Unknown tool 'extract_data'. Available: search_knowledge, calc, delegate"
        )
        agent.tool_registry.run.assert_not_called()

    def test_without_an_identity_every_tool_is_offered(self):
        assert self._agent().tool_names() == (
            "search_knowledge",
            "extract_data",
            "analyze_payments",
            "calc",
            "delegate",
        )


class TestPurposeHeader:
    async def test_the_answer_names_its_purpose_while_it_streams(self, llama_server_env):
        server = FakeLlamaServer([ANSWER])
        pipeline = RAGPipeline(_retrieval({"passages": [Q4_PASSAGE]}), remote_agent())
        with identity(FINANCE), patch("requests.post", server):
            await pipeline.generate_response("What was Q4 2025 revenue?")

        assert server.purposes == ["answer"]
        assert server.streamed == [True]

    @pytest.mark.parametrize("stream_tokens", ["0", "1"])
    def test_grounded_and_instruction_calls_name_theirs(self, llama_server_env, stream_tokens):
        llama_server_env.setenv("AGENT_STREAM_TOKENS", stream_tokens)
        server = FakeLlamaServer(["Revenue was $4.2M."])
        agent = remote_agent()
        with patch("requests.post", server):
            agent.decide("What was Q4 revenue?", context="Q4 2025 revenue was $4.2M.")
            agent.decide("Write a report about Q4.")

        assert server.purposes == ["grounded", "instruction"]
        assert server.streamed == [stream_tokens == "1"] * 2

    async def test_each_react_step_names_its_purpose(self, llama_server_env):
        server = FakeLlamaServer(
            [
                "THOUGHT: search.\nACTION: search_knowledge(Q4 revenue)",
                "THOUGHT: done.\nFINAL_ANSWER: Revenue was $4.2M.",
            ]
        )
        agent = ReactAgent(
            remote_agent(),
            _retrieval({"data": "Q4 2025 revenue was $4.2M."}),
            MagicMock(),
            max_steps=3,
        )
        with identity(FINANCE), patch("requests.post", server):
            await agent.run("What was Q4 2025 revenue?")

        assert server.purposes == ["react_step", "react_step"]
