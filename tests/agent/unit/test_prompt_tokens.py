from __future__ import annotations

import json
import logging
from unittest.mock import MagicMock, patch

import pytest
from prometheus_client import REGISTRY

from ai_agents import prompt_tokens
from ai_agents.decision_making_agent import GROUNDED_SYSTEM_PROMPT, DecisionMakingAgent
from ai_agents.prompt_tokens import TokenSource, estimate_tokens, record_prompt_tokens

HISTOGRAM = "agent_llm_prompt_tokens"
OVER_BUDGET = "agent_llm_prompts_over_budget_total"


def histogram(suffix: str, call: str, source: str) -> float:
    return (
        REGISTRY.get_sample_value(f"{HISTOGRAM}_{suffix}", {"call": call, "source": source}) or 0.0
    )


def over_budget(call: str) -> float:
    return REGISTRY.get_sample_value(OVER_BUDGET, {"call": call}) or 0.0


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


def completion(content: str, usage: dict | None) -> MagicMock:
    body = {"choices": [{"message": {"role": "assistant", "content": content}}]}
    if usage is not None:
        body["usage"] = usage
    response = MagicMock()
    response.json.return_value = body
    return response


def streamed(content: str, prompt_tokens: int) -> MagicMock:
    events = [
        {"choices": [{"index": 0, "delta": {"content": content}}]},
        {"choices": [], "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": 3}},
    ]
    response = MagicMock()
    response.iter_lines.return_value = [
        *(f"data: {json.dumps(event)}".encode() for event in events),
        b"data: [DONE]",
    ]
    post = MagicMock()
    post.return_value.__enter__.return_value = response
    return post


@pytest.fixture
def llama_server_env(monkeypatch):
    monkeypatch.setenv("LLM_BACKEND", "vllm")
    monkeypatch.setenv("LLM_VLLM_URL", "http://llm:8080/v1")
    monkeypatch.delenv("AGENT_STREAM_TOKENS", raising=False)
    monkeypatch.delenv("AGENT_PROMPT_TOKEN_BUDGET", raising=False)
    return monkeypatch


class TestPromptTokensPerCall:
    def test_the_usage_block_of_a_llama_server_answer_is_recorded_under_the_call(
        self, llama_server_env
    ):
        count, total = histogram("count", "answer", "usage"), histogram("sum", "answer", "usage")
        usage = {"prompt_tokens": 1880, "completion_tokens": 96}
        with patch("requests.post", return_value=completion("{}", usage)):
            remote_agent().complete("q", "Passages:\n...\n\nRequest: q", "rules")

        assert histogram("count", "answer", "usage") == count + 1
        assert histogram("sum", "answer", "usage") == total + 1880

    def test_the_usage_chunk_of_a_stream_is_recorded(self, llama_server_env):
        llama_server_env.setenv("AGENT_STREAM_TOKENS", "1")
        total = histogram("sum", "answer", "usage")
        with (
            patch("requests.post", streamed("{}", 733)),
            patch("ai_agents.step_emitter.emit_step", MagicMock()),
        ):
            remote_agent().complete("q", "user", "rules")

        assert histogram("sum", "answer", "usage") == total + 733

    def test_an_answer_without_usage_records_an_estimate_of_the_prompt(self, llama_server_env):
        total = histogram("sum", "grounded", "estimate")
        with patch("requests.post", return_value=completion("ok", None)):
            remote_agent().decide("q", context="ctx")

        expected = estimate_tokens(
            f"{GROUNDED_SYSTEM_PROMPT}\n\nRetrieved Content:\nctx\n\nTask: q"
        )
        assert histogram("sum", "grounded", "estimate") == total + expected

    def test_an_injected_model_given_its_own_prompt_records_an_estimate_of_that_prompt(self):
        total = histogram("sum", "grounded", "estimate")
        model = MagicMock(return_value="ok")
        agent = DecisionMakingAgent(decision_model=model, device="cpu")

        agent.decide("What was revenue?", context="Revenue was $5M.")

        sent = model.call_args.args[0]
        assert sent.startswith(
            "You are a helpful assistant. Answer using ONLY the provided context."
        )
        assert histogram("sum", "grounded", "estimate") == total + estimate_tokens(sent)

    def test_an_injected_model_records_an_estimate_of_the_prompt_it_was_given(self):
        total = histogram("sum", "instruction", "estimate")
        model = MagicMock(return_value="A report.")
        agent = DecisionMakingAgent(decision_model=model, device="cpu")

        agent.decide("Write a report.")

        assert histogram("sum", "instruction", "estimate") == total + estimate_tokens(
            model.call_args.args[0]
        )

    def test_the_in_process_backend_counts_the_tokenized_prompt(self, monkeypatch):
        monkeypatch.setenv("LLM_BACKEND", "transformers")
        agent = remote_agent()
        agent._last_prompt_tokens = 321

        assert agent._prompt_token_count("ignored") == (321, TokenSource.TOKENIZER)

    def test_a_failed_call_records_nothing(self, llama_server_env):
        count = histogram("count", "answer", "usage")
        with patch("requests.post", side_effect=OSError("down")), pytest.raises(OSError):
            remote_agent().complete("q", "user", "rules")

        assert histogram("count", "answer", "usage") == count


class TestPromptTokenBudget:
    def test_a_prompt_over_the_budget_is_counted_and_logged(self, llama_server_env, caplog):
        llama_server_env.setenv("AGENT_PROMPT_TOKEN_BUDGET", "1000")
        before = over_budget("answer")
        usage = {"prompt_tokens": 1880, "completion_tokens": 96}
        with (
            caplog.at_level(logging.WARNING, logger=prompt_tokens.__name__),
            patch("requests.post", return_value=completion("{}", usage)),
        ):
            remote_agent().complete("q", "user", "rules")

        assert over_budget("answer") == before + 1
        assert "call=answer prompt_tokens=1880 budget=1000" in caplog.text

    def test_a_prompt_at_the_budget_is_not_counted(self, monkeypatch):
        monkeypatch.delenv("AGENT_PROMPT_TOKEN_BUDGET", raising=False)
        before = over_budget("react_step")

        assert record_prompt_tokens("react_step", 4096, TokenSource.USAGE) is False

        assert over_budget("react_step") == before

    @pytest.mark.parametrize("raw", ["", "abc", "0", "-5"])
    def test_an_unusable_budget_falls_back_to_the_default(self, monkeypatch, raw):
        monkeypatch.setenv("AGENT_PROMPT_TOKEN_BUDGET", raw)

        assert (
            prompt_tokens.prompt_token_budget() == prompt_tokens.DEFAULT_PROMPT_TOKEN_BUDGET == 4096
        )

    def test_every_call_is_logged_with_its_count_and_source(self, monkeypatch, caplog):
        monkeypatch.delenv("AGENT_PROMPT_TOKEN_BUDGET", raising=False)
        with caplog.at_level(logging.INFO, logger=prompt_tokens.__name__):
            record_prompt_tokens("grounded", 512, TokenSource.ESTIMATE)

        assert "call=grounded prompt_tokens=512 source=estimate budget=4096" in caplog.text

    def test_the_budget_is_checked_when_the_metrics_cannot_be_imported(self, monkeypatch):
        monkeypatch.delenv("AGENT_PROMPT_TOKEN_BUDGET", raising=False)
        with patch.dict("sys.modules", {"core.metrics": None}):
            assert record_prompt_tokens("answer", 9000, TokenSource.USAGE) is True
