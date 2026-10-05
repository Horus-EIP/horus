from __future__ import annotations

import json
import sys
import types
from unittest.mock import MagicMock, patch

import bootstrap_llm
import pytest

import ai_agents.decision_making_agent as dma
from ai_agents.decision_making_agent import DecisionMakingAgent

LLAMA_SERVER_ENV = {
    "LLM_BACKEND": "vllm",
    "LLM_VLLM_URL": "http://llm:8080/v1",
    "LLM_VLLM_MODEL": "qwen3-4b",
    "LLM_VLLM_MAX_MODEL_LEN": "8192",
    "LLM_VLLM_TIMEOUT": "900",
}

FINGERPRINT = "b11382-11fe0215"

COMPLETION_ID = "chatcmpl-Xq4MzdF1V0cR"


def timings(prompt_n: int, predicted_n: int) -> dict:
    return {
        "cache_n": 0,
        "prompt_n": prompt_n,
        "prompt_ms": 5120.4,
        "prompt_per_token_ms": 12.4,
        "prompt_per_second": 80.5,
        "predicted_n": predicted_n,
        "predicted_ms": 4410.2,
        "predicted_per_token_ms": 119.2,
        "predicted_per_second": 8.4,
    }


def usage(prompt_tokens: int, completion_tokens: int) -> dict:
    return {
        "completion_tokens": completion_tokens,
        "prompt_tokens": prompt_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
        "prompt_tokens_details": {"cached_tokens": 0},
    }


def chat_completion(content: str, prompt_tokens: int = 412, completion_tokens: int = 37) -> dict:
    return {
        "choices": [
            {
                "finish_reason": "stop",
                "index": 0,
                "message": {"role": "assistant", "content": content},
            }
        ],
        "created": 1791200000,
        "model": "qwen3-4b",
        "system_fingerprint": FINGERPRINT,
        "object": "chat.completion",
        "usage": usage(prompt_tokens, completion_tokens),
        "id": COMPLETION_ID,
        "timings": timings(prompt_tokens, completion_tokens),
    }


def chunk(delta: dict, finish_reason: str | None = None) -> dict:
    return {
        "choices": [{"finish_reason": finish_reason, "index": 0, "delta": delta}],
        "created": 1791200000,
        "id": COMPLETION_ID,
        "model": "qwen3-4b",
        "system_fingerprint": FINGERPRINT,
        "object": "chat.completion.chunk",
    }


def usage_chunk(prompt_tokens: int, completion_tokens: int) -> dict:
    return {
        "choices": [],
        "created": 1791200000,
        "id": COMPLETION_ID,
        "model": "qwen3-4b",
        "system_fingerprint": FINGERPRINT,
        "object": "chat.completion.chunk",
        "usage": usage(prompt_tokens, completion_tokens),
        "timings": timings(prompt_tokens, completion_tokens),
    }


def sse(*events: dict | str) -> list[bytes]:
    lines: list[bytes] = []
    for event in events:
        if isinstance(event, str):
            lines.append(event.encode("utf-8"))
        else:
            lines.append(("data: " + json.dumps(event)).encode("utf-8"))
        lines.append(b"")
    return lines


def llama_server_stream(*pieces: str, prompt_tokens: int = 412) -> list[bytes]:
    return sse(
        chunk({"role": "assistant", "content": None}),
        ":",
        *(chunk({"content": piece}) for piece in pieces),
        chunk({}, finish_reason="stop"),
        usage_chunk(prompt_tokens, len(pieces)),
        "data: [DONE]",
    )


def streaming_post(lines: list[bytes]) -> MagicMock:
    response = MagicMock()
    response.iter_lines.return_value = lines
    post = MagicMock()
    post.return_value.__enter__.return_value = response
    return post


def capture_deltas():
    chunks: list[str] = []

    def fake_emit(step_type, title, detail="", **metadata):
        if step_type == "reasoning.delta":
            chunks.append(metadata["chunk"])

    return chunks, fake_emit


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


@pytest.fixture
def llama_server_env(monkeypatch):
    for key, value in LLAMA_SERVER_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("AGENT_STREAM_TOKENS", raising=False)
    return monkeypatch


class TestBlockingAnswer:
    def test_a_llama_server_completion_is_read_with_its_token_counts(self, llama_server_env):
        response = MagicMock()
        response.json.return_value = chat_completion("  Q4 2025 revenue was **$4.2M**.  ")
        with patch("requests.post", return_value=response) as post:
            text = remote_agent()._generate_vllm("What was Q4 revenue?", "Answer briefly.")
        assert text == "Q4 2025 revenue was **$4.2M**."
        assert post.call_args.args[0] == "http://llm:8080/v1/chat/completions"
        assert post.call_args.kwargs["timeout"] == 900.0
        assert post.call_args.kwargs["json"]["model"] == "qwen3-4b"
        assert post.call_args.kwargs["json"]["stream"] is False

    def test_the_answer_budget_stays_inside_the_llama_server_context(self, llama_server_env):
        response = MagicMock()
        response.json.return_value = chat_completion("ok")
        system, user = "S" * 3000, "U" * 15000
        with patch("requests.post", return_value=response) as post:
            remote_agent()._generate_vllm(user, system)
        payload = post.call_args.kwargs["json"]
        sent_chars = sum(len(message["content"]) for message in payload["messages"])
        assert sent_chars // 3 + payload["max_tokens"] <= 8192

    def test_the_token_counts_come_from_the_usage_block(self, llama_server_env):
        response = MagicMock()
        response.json.return_value = chat_completion("ok", prompt_tokens=1880, completion_tokens=96)
        agent = remote_agent()
        with patch("requests.post", return_value=response):
            agent._generate_vllm("q", "s")
        assert (agent._last_prompt_tokens, agent._last_gen_tokens) == (1880, 96)


class TestStreamedAnswer:
    @pytest.fixture(autouse=True)
    def stream_tokens(self, llama_server_env):
        llama_server_env.setenv("AGENT_STREAM_TOKENS", "1")

    def test_a_llama_server_stream_is_read_past_its_role_ping_and_finish_chunks(self):
        post = streaming_post(llama_server_stream("Q4 2025 ", "revenue was ", "$4.2M."))
        chunks, fake_emit = capture_deltas()
        agent = remote_agent()
        with patch("requests.post", post), patch("ai_agents.step_emitter.emit_step", fake_emit):
            text = agent._generate_vllm("What was Q4 revenue?", "Answer briefly.")
        assert text == "Q4 2025 revenue was $4.2M."
        assert "".join(chunks) == "Q4 2025 revenue was $4.2M."
        assert (agent._last_prompt_tokens, agent._last_gen_tokens) == (412, 3)

    def test_the_stream_asks_llama_server_for_the_usage_chunk(self):
        post = streaming_post(llama_server_stream("ok"))
        with patch("requests.post", post), patch("ai_agents.step_emitter.emit_step", MagicMock()):
            remote_agent()._generate_vllm("q", "s")
        payload = post.call_args.kwargs["json"]
        assert payload["stream"] is True
        assert payload["stream_options"] == {"include_usage": True}
        assert post.call_args.args[0] == "http://llm:8080/v1/chat/completions"
        assert post.call_args.kwargs["timeout"] == 900.0

    def test_an_error_event_in_the_middle_of_a_llama_server_stream_raises(self):
        lines = sse(
            chunk({"role": "assistant", "content": None}),
            chunk({"content": "Q4 2025 revenue"}),
            {"error": {"code": 500, "message": "failed to decode the batch", "type": "server_error"}},
        )
        with patch("requests.post", streaming_post(lines)), patch(
            "ai_agents.step_emitter.emit_step", MagicMock()
        ), pytest.raises(RuntimeError, match="failed to decode the batch"):
            remote_agent()._generate_vllm("What was Q4 revenue?", "Answer briefly.")


class TestNoLocalModel:
    def test_the_agent_loads_no_decision_model_at_startup(self, llama_server_env):
        llama_server_env.setenv("AGENT_LAZY_DECISION_MODEL", "0")
        with patch.object(DecisionMakingAgent, "_load_causal_model") as load:
            agent = DecisionMakingAgent(device="cpu")
        load.assert_not_called()
        assert agent._causal_model is None

    def test_answering_a_question_loads_no_decision_model(self, llama_server_env):
        llama_server_env.setenv("AGENT_LAZY_DECISION_MODEL", "1")
        agent = DecisionMakingAgent(device="cpu")
        with patch.object(DecisionMakingAgent, "_load_causal_model") as load, patch.object(
            DecisionMakingAgent, "_generate_vllm", return_value="served"
        ) as served:
            answer = agent.decide("What was Q4 revenue?", context="Q4 2025 revenue was $4.2M.")
        load.assert_not_called()
        served.assert_called_once()
        assert answer == "served"

    def test_the_entrypoint_bootstrap_downloads_nothing(self, llama_server_env, tmp_path):
        model_dir = tmp_path / "agent-model"
        llama_server_env.setenv("MODEL_DIR", str(model_dir))
        llama_server_env.setenv("HF_HUB_OFFLINE", "0")
        hub = types.ModuleType("huggingface_hub")
        hub.snapshot_download = MagicMock()
        with patch.dict(sys.modules, {"huggingface_hub": hub}):
            assert bootstrap_llm.main() == 0
        hub.snapshot_download.assert_not_called()
        assert not model_dir.exists()

    def test_the_in_process_backend_would_download_the_model(self, llama_server_env, tmp_path):
        llama_server_env.setenv("LLM_BACKEND", "transformers")
        llama_server_env.setenv("MODEL_DIR", str(tmp_path / "agent-model"))
        llama_server_env.setenv("HF_HUB_OFFLINE", "0")
        hub = types.ModuleType("huggingface_hub")
        hub.snapshot_download = MagicMock()
        with patch.dict(sys.modules, {"huggingface_hub": hub}):
            assert bootstrap_llm.main() == 0
        hub.snapshot_download.assert_called_once()
        assert dma._llm_backend() == "transformers"
