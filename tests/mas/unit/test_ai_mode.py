from __future__ import annotations

import json
import logging
from unittest.mock import MagicMock, patch

import pytest

from core import ai_mode, embedding_setup

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
    for key in (
        "MAS_EMBED_URL",
        "MAS_EMBED_MODEL",
        "HORUS_SPACY",
        "HORUS_MONITORING",
        "OTEL_SDK_DISABLED",
    ):
        monkeypatch.delenv(key, raising=False)
    ai_mode.reset()
    yield
    ai_mode.reset()


def test_a_server_owned_by_horus_mock_means_mock_mode():
    with patch("urllib.request.urlopen", return_value=served("horus-mock")) as urlopen:
        mode = ai_mode.probe()
    assert mode == ai_mode.AiMode("mock", "horus-mock", "horus-mock")
    assert mode.as_dict() == {
        "mode": "mock",
        "model": "horus-mock",
        "server": "horus-mock",
        "simulated": True,
    }
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
        assert ai_mode.probe() == ai_mode.AiMode(
            "local", "Qwen/Qwen2.5-1.5B-Instruct", "in-process"
        )
    urlopen.assert_not_called()


def test_the_mode_is_asked_once_and_asked_again_while_unknown():
    replies = [OSError("not up yet"), served("horus-mock"), served("llamacpp")]
    with patch("urllib.request.urlopen", side_effect=replies) as urlopen:
        assert ai_mode.current().mode == "unknown"
        assert ai_mode.current().mode == "mock"
        assert ai_mode.provider() == "mock"
    assert urlopen.call_count == 2


def test_mock_mode_is_logged_once_as_a_warning(caplog):
    with (
        caplog.at_level(logging.WARNING),
        patch("urllib.request.urlopen", return_value=served("horus-mock")),
    ):
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


def test_without_an_embeddings_server_mas_names_its_own_model():
    with patch("urllib.request.urlopen") as urlopen:
        assert ai_mode.embeddings() == "sentence-transformers/all-MiniLM-L6-v2"
    urlopen.assert_not_called()


def test_embeddings_from_llm_mock_are_mock_and_asked_once(monkeypatch):
    monkeypatch.setenv("MAS_EMBED_URL", "http://llm-mock:8080/v1")
    with patch("urllib.request.urlopen", return_value=served("horus-mock")) as urlopen:
        assert ai_mode.embeddings() == "mock"
        assert ai_mode.embeddings() == "mock"
    assert urlopen.call_count == 1
    assert urlopen.call_args[0][0] == "http://llm-mock:8080/v1/models"


def test_embeddings_from_a_real_server_name_the_model_mas_asks_it_for(monkeypatch):
    monkeypatch.setenv("MAS_EMBED_URL", "http://embeddings:8080/v1")
    with patch("urllib.request.urlopen", return_value=served("vllm", "llama-3")):
        assert ai_mode.embeddings() == "sentence-transformers/all-MiniLM-L6-v2"
    ai_mode.reset()
    monkeypatch.setenv("MAS_EMBED_MODEL", "minilm")
    with patch("urllib.request.urlopen", return_value=served("vllm", "llama-3")):
        assert ai_mode.embeddings() == "minilm"
    assert embedding_setup.server_model() == "minilm"


def test_an_embeddings_server_that_cannot_be_asked_is_asked_again(monkeypatch):
    monkeypatch.setenv("MAS_EMBED_URL", "http://llm-mock:8080/v1")
    with patch("urllib.request.urlopen", side_effect=[OSError("not up"), served("horus-mock")]):
        assert ai_mode.embeddings() is None
        assert ai_mode.embeddings() == "mock"


@pytest.mark.parametrize(
    ("value", "state"),
    [
        (None, "on"),
        ("", "on"),
        ("on", "on"),
        ("off", "off"),
        ("OFF", "off"),
        ("0", "off"),
        ("false", "off"),
        ("no", "off"),
        ('"off"', "off"),
        ("off # mock mode", "off"),
    ],
)
def test_spacy_and_monitoring_follow_their_settings(monkeypatch, value, state):
    for name in ("HORUS_SPACY", "HORUS_MONITORING"):
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)
    in_use = ai_mode.models_in_use()
    assert (in_use["spacy"], in_use["monitoring"]) == (state, state)


def test_the_mock_warning_says_what_is_faked_and_what_is_off(monkeypatch, caplog):
    monkeypatch.setenv("MAS_EMBED_URL", "http://llm-mock:8080/v1")
    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")
    with (
        caplog.at_level(logging.WARNING),
        patch("urllib.request.urlopen", return_value=served("horus-mock")),
    ):
        ai_mode.current()
    warnings = [r.getMessage() for r in caplog.records if "Mock AI mode" in r.getMessage()]
    assert len(warnings) == 1
    assert "llm-mock answers MAS's model calls and computes its embeddings" in warnings[0]
    assert "MAS exports no trace" in warnings[0]
