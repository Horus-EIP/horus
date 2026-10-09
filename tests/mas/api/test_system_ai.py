from __future__ import annotations

from unittest.mock import patch

from core import ai_mode
from system.routes import router


def test_anyone_can_ask_which_ai_answers(make_client):
    mode = ai_mode.AiMode("mock", "horus-mock", "horus-mock")
    with patch.object(ai_mode, "current", return_value=mode):
        response = make_client(router).get("/system/ai")
    assert response.status_code == 200
    assert response.json() == {"mode": "mock", "model": "horus-mock", "server": "horus-mock",
                               "simulated": True}


def test_an_unreachable_model_server_is_reported_unknown(make_client):
    with patch.object(ai_mode, "current", return_value=ai_mode.AiMode("unknown", None, None)):
        body = make_client(router).get("/system/ai").json()
    assert body == {"mode": "unknown", "model": None, "server": None, "simulated": False}


def test_the_answer_carries_no_address_or_secret(make_client, monkeypatch):
    monkeypatch.setenv("LLM_VLLM_URL", "http://llm:8080/v1")
    mode = ai_mode.AiMode("local", "qwen3-4b", "llamacpp")
    with patch.object(ai_mode, "current", return_value=mode):
        text = make_client(router).get("/system/ai").text
    assert "llm:8080" not in text
    assert set(make_client(router).app.openapi()["paths"]["/system/ai"]["get"]) >= {"summary"}
