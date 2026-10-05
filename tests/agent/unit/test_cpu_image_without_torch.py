from unittest.mock import MagicMock, patch

import pytest

import ai_agents.decision_making_agent as dma
from ai_agents.decision_making_agent import DecisionMakingAgent


@pytest.fixture
def cpu_image(monkeypatch):
    monkeypatch.setattr(dma, "_TRANSFORMERS_AVAILABLE", False)
    monkeypatch.setattr(dma, "_TORCH_AVAILABLE", False)
    for missing in ("torch", "AutoModelForCausalLM", "AutoTokenizer", "BitsAndBytesConfig"):
        monkeypatch.setattr(dma, missing, None)
    monkeypatch.setenv("AGENT_STREAM_TOKENS", "0")


def _server_reply(content: str) -> MagicMock:
    response = MagicMock()
    response.json.return_value = {
        "choices": [{"message": {"content": content}}],
        "usage": {"prompt_tokens": 12, "completion_tokens": 3},
    }
    return response


def test_the_agent_starts_on_the_llm_server_without_torch(cpu_image, monkeypatch):
    monkeypatch.setenv("LLM_BACKEND", "vllm")
    monkeypatch.setenv("AGENT_LAZY_DECISION_MODEL", "0")

    with patch.object(DecisionMakingAgent, "_load_causal_model") as load:
        agent = DecisionMakingAgent(device="cpu")

    load.assert_not_called()
    assert agent._causal_model is None


def test_the_agent_answers_through_the_llm_server_without_torch(cpu_image, monkeypatch):
    monkeypatch.setenv("LLM_BACKEND", "vllm")
    agent = DecisionMakingAgent(device="cpu")

    with patch("requests.post", return_value=_server_reply("Q4 revenue was $4.2M.")):
        answer = agent.decide("What was Q4 revenue?", context="Q4 revenue: $4.2M")

    assert answer == "Q4 revenue was $4.2M."


def test_the_in_process_model_names_what_the_image_lacks(cpu_image, monkeypatch):
    monkeypatch.setenv("LLM_BACKEND", "transformers")

    with pytest.raises(RuntimeError, match="LLM_BACKEND=vllm"):
        DecisionMakingAgent(device="cpu")
