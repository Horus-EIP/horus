from __future__ import annotations

import json
import sys
import types
from unittest.mock import MagicMock, patch

import bootstrap_llm
import pytest
from prometheus_client import REGISTRY

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


def prompt_token_sample(suffix: str, labels: dict) -> float:
    return REGISTRY.get_sample_value(f"mas_llm_prompt_tokens_{suffix}", labels) or 0.0


def over_budget_count(call: str) -> float:
    return REGISTRY.get_sample_value("mas_llm_prompts_over_budget_total", {"call": call}) or 0.0


def test_the_prompt_tokens_llama_server_reports_are_recorded_under_the_call(llama_server_env):
    labels = {"call": "aggregate", "source": "usage"}
    count_before = prompt_token_sample("count", labels)
    sum_before = prompt_token_sample("sum", labels)
    server = FakeUrlopen(llama_server_completion("Summary."))
    with patch("urllib.request.urlopen", server):
        llm_setup.ask_llm([{"role": "user", "content": "Summarise."}], 512, call="aggregate")
    assert prompt_token_sample("count", labels) == count_before + 1
    assert prompt_token_sample("sum", labels) == sum_before + 640


def test_the_constrained_router_call_is_recorded_under_its_schema_name(llama_server_env):
    labels = {"call": "task_route", "source": "usage"}
    count_before = prompt_token_sample("count", labels)
    server = FakeUrlopen(llama_server_completion(ROUTING_REPLY))
    with patch("urllib.request.urlopen", server):
        llm_setup.ask_llm_with_json_schema(
            [{"role": "user", "content": "Route this."}], "task_route", ROUTE_SCHEMA, 32
        )
    assert prompt_token_sample("count", labels) == count_before + 1


def test_a_reply_without_usage_records_an_estimate_from_the_messages(llama_server_env):
    labels = {"call": "review", "source": "estimate"}
    sum_before = prompt_token_sample("sum", labels)
    body = llama_server_completion('{"decision": "DONE"}')
    del body["usage"]
    messages = [{"role": "system", "content": "s" * 30}, {"role": "user", "content": "u" * 31}]
    with patch("urllib.request.urlopen", FakeUrlopen(body)):
        llm_setup.ask_llm(messages, 384, call="review")
    assert prompt_token_sample("sum", labels) == sum_before + 21


def test_a_prompt_over_the_budget_is_counted(llama_server_env):
    llama_server_env.setenv("LLM_PROMPT_TOKEN_BUDGET", "600")
    before = over_budget_count("plan")
    with patch("urllib.request.urlopen", FakeUrlopen(llama_server_completion("{}"))):
        llm_setup.ask_llm([{"role": "user", "content": "Plan this."}], 2048, call="plan")
    assert over_budget_count("plan") == before + 1


def test_a_prompt_within_the_budget_is_not_counted(llama_server_env):
    before = over_budget_count("announce")
    with patch("urllib.request.urlopen", FakeUrlopen(llama_server_completion("I'll do it."))):
        llm_setup.ask_llm([{"role": "user", "content": "Announce."}], 256, call="announce")
    assert over_budget_count("announce") == before


@pytest.mark.parametrize("raw", ["", "abc", "0", "-3"])
def test_an_unusable_budget_falls_back_to_the_default(monkeypatch, raw):
    monkeypatch.setenv("LLM_PROMPT_TOKEN_BUDGET", raw)
    assert llm_setup.prompt_token_budget() == llm_setup.DEFAULT_PROMPT_TOKEN_BUDGET == 4096


def test_an_unlabelled_call_is_recorded_as_other(llama_server_env):
    labels = {"call": "other", "source": "usage"}
    count_before = prompt_token_sample("count", labels)
    with patch("urllib.request.urlopen", FakeUrlopen(llama_server_completion("ok"))):
        llm_setup.ask_llm([{"role": "user", "content": "Hi."}], 64)
    assert prompt_token_sample("count", labels) == count_before + 1
