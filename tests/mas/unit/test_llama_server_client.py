from __future__ import annotations

import json
import sys
import types
from unittest.mock import MagicMock, patch

import bootstrap_llm
import pytest

import core.llm_setup as llm_setup

LLAMA_SERVER_ENV = {
    "LLM_BACKEND": "vllm",
    "LLM_VLLM_URL": "http://llm:8080/v1",
    "LLM_VLLM_MODEL": "qwen3-4b",
    "LLM_VLLM_MAX_MODEL_LEN": "8192",
    "LLM_VLLM_TIMEOUT": "900",
}

ROUTING_REPLY = '{"route_type": "SINGLE_AGENT", "agent_name": "Finance-Analyst"}'


def llama_server_completion(content: str) -> dict:
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
        "system_fingerprint": "b11382-11fe0215",
        "object": "chat.completion",
        "usage": {
            "completion_tokens": 21,
            "prompt_tokens": 640,
            "total_tokens": 661,
            "prompt_tokens_details": {"cached_tokens": 512},
        },
        "id": "chatcmpl-Kf2u9wq0Lr",
        "timings": {
            "cache_n": 512,
            "prompt_n": 128,
            "prompt_ms": 1610.2,
            "prompt_per_token_ms": 12.6,
            "prompt_per_second": 79.5,
            "predicted_n": 21,
            "predicted_ms": 2504.8,
            "predicted_per_token_ms": 119.3,
            "predicted_per_second": 8.4,
        },
    }


class FakeUrlopen:
    def __init__(self, body: dict):
        self.body = body
        self.requests: list = []
        self.timeouts: list = []

    def __call__(self, request, timeout=None):
        self.requests.append(request)
        self.timeouts.append(timeout)
        response = MagicMock()
        response.read.return_value = json.dumps(self.body).encode("utf-8")
        response.__enter__.return_value = response
        return response

    def sent(self) -> dict:
        return json.loads(self.requests[-1].data.decode("utf-8"))


@pytest.fixture
def llama_server_env(monkeypatch):
    for key, value in LLAMA_SERVER_ENV.items():
        monkeypatch.setenv(key, value)
    return monkeypatch


def test_a_llama_server_completion_is_the_router_answer(llama_server_env):
    server = FakeUrlopen(llama_server_completion(f"  {ROUTING_REPLY}\n"))
    with patch("urllib.request.urlopen", server):
        answer = llm_setup.ask_llm([{"role": "user", "content": "Route this."}], 1024)
    assert answer == ROUTING_REPLY
    assert server.requests[-1].full_url == "http://llm:8080/v1/chat/completions"
    assert server.timeouts[-1] == 900.0


def test_the_request_names_the_llama_server_alias_and_does_not_stream(llama_server_env):
    server = FakeUrlopen(llama_server_completion(ROUTING_REPLY))
    with patch("urllib.request.urlopen", server):
        llm_setup.ask_llm([{"role": "user", "content": "Route this."}], 1024)
    sent = server.sent()
    assert sent["model"] == "qwen3-4b"
    assert sent["stream"] is False
    assert sent["temperature"] == 0.0
    assert sent["messages"] == [{"role": "user", "content": "Route this."}]


def test_a_long_prompt_leaves_the_answer_inside_the_llama_server_context(llama_server_env):
    server = FakeUrlopen(llama_server_completion("Summary."))
    history = [{"role": "user", "content": "x" * 18000}]
    with patch("urllib.request.urlopen", server):
        llm_setup.ask_llm(history, 3072)
    assert 18000 // 3 + server.sent()["max_tokens"] <= 8192


def test_mas_loads_no_router_model_with_the_llama_server_backend(llama_server_env):
    llama_server_env.setenv("TEST_MODE", "0")
    llama_server_env.setattr(llm_setup.settings, "llm_autoinit", 1)
    server = FakeUrlopen(llama_server_completion(ROUTING_REPLY))
    with patch.object(llm_setup, "get_llm") as load, patch("urllib.request.urlopen", server):
        llm_setup._ensure_llm_loaded()
        llm_setup.ask_llm([{"role": "user", "content": "Route this."}], 1024)
    load.assert_not_called()
    assert llm_setup.model is None


def test_the_entrypoint_bootstrap_downloads_no_router_model(llama_server_env, tmp_path):
    model_dir = tmp_path / "router-model"
    llama_server_env.setenv("LLM_MODEL_DIR", str(model_dir))
    llama_server_env.setenv("HF_HUB_OFFLINE", "0")
    hub = types.ModuleType("huggingface_hub")
    hub.snapshot_download = MagicMock()
    with patch.dict(sys.modules, {"huggingface_hub": hub}):
        assert bootstrap_llm.main() == 0
    hub.snapshot_download.assert_not_called()
    assert not model_dir.exists()


def test_the_in_process_backend_would_download_the_router_model(llama_server_env, tmp_path):
    llama_server_env.setenv("LLM_BACKEND", "transformers")
    llama_server_env.setenv("LLM_MODEL_DIR", str(tmp_path / "router-model"))
    llama_server_env.setenv("HF_HUB_OFFLINE", "0")
    hub = types.ModuleType("huggingface_hub")
    hub.snapshot_download = MagicMock()
    with patch.dict(sys.modules, {"huggingface_hub": hub}):
        assert bootstrap_llm.main() == 0
    hub.snapshot_download.assert_called_once()


ROUTE_SCHEMA = {
    "type": "object",
    "properties": {
        "route": {"type": "string", "enum": ["SINGLE_AGENT", "COMPLEX_TASK"]},
        "agent": {"type": "string", "enum": ["Finance-Analyst", "HR-Assistant"]},
    },
    "required": ["route", "agent"],
    "additionalProperties": False,
}


def test_the_constrained_router_call_sends_a_json_schema_and_a_32_token_budget(llama_server_env):
    server = FakeUrlopen(llama_server_completion(ROUTING_REPLY))
    with patch("urllib.request.urlopen", server):
        answer = llm_setup.ask_llm_with_json_schema(
            [{"role": "user", "content": "Route this."}], "task_route", ROUTE_SCHEMA, 32
        )
    sent = server.sent()
    assert answer == ROUTING_REPLY
    assert sent["max_tokens"] == 32
    assert sent["temperature"] == 0.0
    assert sent["stream"] is False
    assert sent["model"] == "qwen3-4b"
    assert sent["response_format"] == {
        "type": "json_schema",
        "json_schema": {"name": "task_route", "strict": True, "schema": ROUTE_SCHEMA},
    }
    assert server.requests[-1].full_url == "http://llm:8080/v1/chat/completions"
    assert server.timeouts[-1] == 900.0


def test_the_constrained_router_call_needs_the_server_backend(monkeypatch):
    monkeypatch.setenv("LLM_BACKEND", "transformers")
    server = FakeUrlopen(llama_server_completion(ROUTING_REPLY))
    with patch("urllib.request.urlopen", server), pytest.raises(RuntimeError, match="LLM_BACKEND=vllm"):
        llm_setup.ask_llm_with_json_schema([], "task_route", ROUTE_SCHEMA, 32)
    assert server.requests == []


def test_the_server_backend_is_recognised(llama_server_env):
    assert llm_setup.llm_server_backend() is True
    llama_server_env.setenv("LLM_BACKEND", "transformers")
    assert llm_setup.llm_server_backend() is False
