from __future__ import annotations

import json
import logging
from unittest.mock import MagicMock, patch

import pytest

from core import ai_mode

SERVER_ENV = {"LLM_BACKEND": "vllm", "LLM_VLLM_URL": "http://llm-mock:8080/v1/"}


def served(owner: str, model: str = "horus-mock") -> MagicMock:
    body = {"object": "list", "data": [{"id": model, "object": "model", "owned_by": owner}]}
    response = MagicMock()
    response.read.return_value = json.dumps(body).encode("utf-8")
    response.__enter__.return_value = response
    return response


@pytest.fixture(autouse=True)
def fresh_mode(monkeypatch):
    for key, value in SERVER_ENV.items():
        monkeypatch.setenv(key, value)
    ai_mode.reset()
    yield
    ai_mode.reset()


def test_a_server_owned_by_horus_mock_means_mock_mode():
    with patch("urllib.request.urlopen", return_value=served("horus-mock")) as urlopen:
        mode = ai_mode.probe()
    assert mode == ai_mode.AiMode("mock", "horus-mock", "horus-mock")
    assert mode.as_dict() == {"mode": "mock", "model": "horus-mock", "server": "horus-mock",
                              "simulated": True}
    assert urlopen.call_args[0][0] == "http://llm-mock:8080/v1/models"


@pytest.mark.parametrize("owner", ["llamacpp", "vllm", "", None])
def test_any_other_server_is_a_local_model(owner):
    with patch("urllib.request.urlopen", return_value=served(owner, "qwen3-4b")):
        mode = ai_mode.probe()
    assert mode.mode == "local"
    assert mode.model == "qwen3-4b"
    assert mode.provider == "local"
    assert mode.as_dict()["simulated"] is False


@pytest.mark.parametrize("failure", [OSError("refused"), ValueError("not json")])
def test_a_server_that_cannot_be_asked_is_unknown(failure):
    with patch("urllib.request.urlopen", side_effect=failure):
        mode = ai_mode.probe()
    assert mode == ai_mode.AiMode("unknown", None, None)
    assert mode.provider is None


def test_an_empty_model_list_is_unknown():
    response = MagicMock()
    response.read.return_value = b'{"data": []}'
    response.__enter__.return_value = response
    with patch("urllib.request.urlopen", return_value=response):
        assert ai_mode.probe().mode == "unknown"


def test_the_in_process_backend_is_local_without_asking(monkeypatch):
    monkeypatch.setenv("LLM_BACKEND", "transformers")
    monkeypatch.setenv("LLM_MODEL_ID", "Qwen/Qwen2.5-1.5B-Instruct")
    with patch("urllib.request.urlopen") as urlopen:
        assert ai_mode.probe() == ai_mode.AiMode("local", "Qwen/Qwen2.5-1.5B-Instruct", "in-process")
    urlopen.assert_not_called()


def test_the_mode_is_asked_once_and_asked_again_while_unknown():
    replies = [OSError("not up yet"), served("horus-mock"), served("llamacpp")]
    with patch("urllib.request.urlopen", side_effect=replies) as urlopen:
        assert ai_mode.current().mode == "unknown"
        assert ai_mode.current().mode == "mock"
        assert ai_mode.provider() == "mock"
    assert urlopen.call_count == 2


def test_mock_mode_is_logged_once_as_a_warning(caplog):
    with caplog.at_level(logging.WARNING), \
            patch("urllib.request.urlopen", return_value=served("horus-mock")):
        ai_mode.current()
        ai_mode.current()
    warnings = [r for r in caplog.records if "Mock AI mode" in r.getMessage()]
    assert len(warnings) == 1
    assert warnings[0].levelno == logging.WARNING


def test_the_probe_runs_in_a_daemon_thread():
    with patch("urllib.request.urlopen", return_value=served("horus-mock")):
        thread = ai_mode.start_probe_background_thread()
        thread.join(5)
    assert thread.daemon
    assert ai_mode.current().mode == "mock"
