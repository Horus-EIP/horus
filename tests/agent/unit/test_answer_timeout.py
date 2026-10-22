from __future__ import annotations

import json
import threading
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import ai_agents.decision_making_agent as dma
from ai_agents.decision_making_agent import DecisionMakingAgent
from ai_agents.generation_stop import (
    GenerationStopped,
    GenerationTimedOut,
    current_generation_stop,
    generation_stop_event,
)
from ai_agents.rag_pipeline import RAGPipeline

LLAMA_SERVER_ENV = {
    "LLM_BACKEND": "vllm",
    "LLM_VLLM_URL": "http://llm:8080/v1",
    "LLM_VLLM_MODEL": "qwen3-4b",
    "LLM_VLLM_MAX_MODEL_LEN": "8192",
}


def _pipeline():
    retrieval = MagicMock()
    retrieval.fetch = AsyncMock(return_value={"data": "retrieved context"})
    decision = MagicMock()
    decision.device = "cpu"
    return RAGPipeline(retrieval, decision, tool_registry=MagicMock()), decision


def _contract(answer: str) -> str:
    return json.dumps({"status": "ok", "answer": answer, "sources": []})


def _remote_agent() -> DecisionMakingAgent:
    agent = DecisionMakingAgent.__new__(DecisionMakingAgent)
    agent.model_name = "Qwen/Qwen3-4B-Instruct-2507"
    agent.device = "cpu"
    agent.decision_model = None
    agent._causal_tokenizer = None
    agent._causal_model = None
    agent._last_gen_tokens = None
    agent._last_prompt_tokens = None
    return agent


def _stream_line(content: str) -> bytes:
    chunk = {"choices": [{"index": 0, "delta": {"content": content}, "finish_reason": None}]}
    return ("data: " + json.dumps(chunk)).encode("utf-8")


@pytest.fixture
def llama_server_env(monkeypatch):
    for key, value in LLAMA_SERVER_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("AGENT_STREAM_TOKENS", raising=False)
    return monkeypatch


@pytest.fixture
def stop_requested():
    stop = threading.Event()
    binding = current_generation_stop.set(stop)
    yield stop
    current_generation_stop.reset(binding)


async def test_a_timed_out_answer_fails_instead_of_passing_for_an_answer(monkeypatch):
    monkeypatch.setenv("REACT_TIMEOUT_SECONDS", "0.05")
    release = threading.Event()
    pipeline, decision = _pipeline()
    decision.complete.side_effect = lambda *_args, **_kwargs: (
        release.wait(5) and _contract("late answer")
    )

    try:
        with pytest.raises(TimeoutError):
            await pipeline.generate_response("What was Q4 revenue?")
    finally:
        release.set()


async def test_the_timeout_asks_the_running_generation_to_stop(monkeypatch):
    monkeypatch.setenv("REACT_TIMEOUT_SECONDS", "0.05")
    pipeline, decision = _pipeline()
    seen: dict = {}
    stopped = threading.Event()

    def generate(*_args, **_kwargs):
        stop = generation_stop_event()
        seen["stop"] = stop
        if stop.wait(5):
            stopped.set()
        return _contract("late answer")

    decision.complete.side_effect = generate

    with pytest.raises(GenerationTimedOut) as raised:
        await pipeline.generate_response("What was Q4 revenue?")

    assert stopped.wait(5)
    assert raised.value.seconds == 0.05
    assert "REACT_TIMEOUT_SECONDS" in str(raised.value)
    assert generation_stop_event() is None


def test_the_timeout_message_keeps_the_phrase_the_eval_runner_detects():
    message = str(GenerationTimedOut(900))

    assert "took too long to respond" in message.lower()
    assert "within 900s" in message


async def test_an_answer_in_time_leaves_no_stop_request_behind():
    pipeline, decision = _pipeline()
    decision.complete.side_effect = lambda *_args, **_kwargs: _contract(
        "on time" if not generation_stop_event().is_set() else "stopped"
    )

    answer = await pipeline.generate_response("What was Q4 revenue?")

    assert answer.answer == "on time"
    assert generation_stop_event() is None


class TestOpenAICompatibleBackend:
    def test_a_stop_request_closes_the_stream_to_the_llm_server(
        self, llama_server_env, stop_requested
    ):
        llama_server_env.setenv("AGENT_STREAM_TOKENS", "1")
        read: list[bytes] = []

        def lines():
            for content in ("Q4 ", "revenue ", "was ", "$4.2M."):
                line = _stream_line(content)
                read.append(line)
                if len(read) == 2:
                    stop_requested.set()
                yield line

        response = MagicMock()
        response.iter_lines.return_value = lines()
        post = MagicMock()
        post.return_value.__enter__.return_value = response

        with (
            patch("requests.post", post),
            patch("ai_agents.step_emitter.emit_step", MagicMock()),
            pytest.raises(GenerationStopped),
        ):
            _remote_agent()._generate_vllm("What was Q4 revenue?", "Answer briefly.")

        assert len(read) == 2
        post.return_value.__exit__.assert_called_once()

    def test_a_stoppable_call_streams_even_with_token_streaming_off(
        self, llama_server_env, stop_requested
    ):
        response = MagicMock()
        response.iter_lines.return_value = [_stream_line("ok"), b"data: [DONE]"]
        post = MagicMock()
        post.return_value.__enter__.return_value = response
        emit = MagicMock()

        with patch("requests.post", post), patch("ai_agents.step_emitter.emit_step", emit):
            text = _remote_agent()._generate_vllm("q", "s")

        assert text == "ok"
        assert post.call_args.kwargs["json"]["stream"] is True
        emit.assert_not_called()

    def test_a_stopped_generation_is_not_reported_as_a_failed_reasoning(self, llama_server_env):
        agent = _remote_agent()
        emit = MagicMock()
        with (
            patch.object(
                DecisionMakingAgent,
                "_generate_vllm",
                side_effect=GenerationStopped("Generation stopped by its caller"),
            ),
            patch("ai_agents.step_emitter.emit_step", emit),
            pytest.raises(GenerationStopped),
        ):
            agent.decide("What was Q4 revenue?", context="Q4 2025 revenue was $4.2M.")

        step_types = [call.args[0] for call in emit.call_args_list]
        assert step_types == ["reasoning.start"]


def _local_agent(generate) -> DecisionMakingAgent:
    agent = _remote_agent()
    ids = MagicMock(name="input_ids")
    ids.to.return_value = ids
    ids.size.return_value = 3
    encoded = {"input_ids": ids}
    tokenizer = MagicMock(name="tokenizer")
    tokenizer.apply_chat_template.return_value = "prompt"
    tokenizer.side_effect = lambda *_args, **kwargs: (
        MagicMock(input_ids=[]) if kwargs.get("add_special_tokens") is False else encoded
    )
    model = MagicMock(name="model")
    model.generate.side_effect = generate
    agent._causal_tokenizer = tokenizer
    agent._causal_model = model
    return agent


class TestTransformersBackend:
    def test_the_stop_flag_ends_generation_at_the_next_token(self):
        stop = threading.Event()
        criteria = dma._StopRequestedCriteria(stop)

        before = criteria(None, None)
        stop.set()

        assert before is False
        assert criteria(None, None) is True

    def test_a_generation_stopped_by_its_caller_is_not_returned_as_an_answer(
        self, monkeypatch, stop_requested
    ):
        monkeypatch.setattr(dma, "_early_stop_enabled", lambda: False)
        monkeypatch.setattr(dma, "_stream_tokens_enabled", lambda: False)
        monkeypatch.setattr(dma, "_model_device", lambda _model: "cpu")
        monkeypatch.setattr(dma, "StoppingCriteriaList", list)
        seen: dict = {}

        def generate(**kwargs):
            stop_requested.set()
            seen["stopped"] = [criterion(None, None) for criterion in kwargs["stopping_criteria"]]
            return MagicMock(name="partial_output")

        agent = _local_agent(generate)

        with pytest.raises(GenerationStopped):
            agent._generate_causal("What was Q4 revenue?", "Answer briefly.")

        assert seen["stopped"] == [True]
