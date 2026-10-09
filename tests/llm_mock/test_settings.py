import logging
import runpy
import signal
from unittest import mock

import pytest

from llm_mock import server as server_module
from llm_mock.settings import Settings
from llm_mock.words import stem, words


def test_the_defaults_match_the_design():
    assert Settings.from_env({}) == Settings(scenario="normal", latency_ms=300, min_score=0.2,
                                             model="horus-mock")


def test_every_setting_is_read_from_the_environment():
    settings = Settings.from_env({
        "HORUS_MOCK_SCENARIO": " Invalid_JSON ",
        "HORUS_MOCK_LATENCY_MS": "0",
        "HORUS_MOCK_MIN_SCORE": "0.35",
        "LLM_VLLM_MODEL": "horus-mock-2",
    })
    assert settings == Settings(scenario="invalid_json", latency_ms=0, min_score=0.35,
                                model="horus-mock-2")


@pytest.mark.parametrize("name, value", [
    ("HORUS_MOCK_SCENARIO", "chaos"),
    ("HORUS_MOCK_LATENCY_MS", "fast"),
    ("HORUS_MOCK_LATENCY_MS", "-5"),
    ("HORUS_MOCK_LATENCY_MS", "inf"),
    ("HORUS_MOCK_MIN_SCORE", "nan"),
])
def test_a_bad_value_falls_back_to_the_default_with_a_warning(caplog, name, value):
    with caplog.at_level(logging.WARNING, logger="llm_mock"):
        assert Settings.from_env({name: value}) == Settings()
    assert name in caplog.text


@pytest.mark.parametrize("word, expected", [
    ("revenues", "revenue"), ("policies", "policy"), ("capped", "cap"), ("hotels", "hotel"),
    ("boxes", "box"), ("status", "status"), ("analysis", "analysis"), ("allowed", "allow"),
    ("spending", "spend"), ("q4", "q4"), ("cap", "cap"), ("glasses", "glass"), ("called", "call"),
])
def test_words_are_stemmed_for_matching(word, expected):
    assert stem(word) == expected


def test_words_keep_figures_and_drop_stopwords():
    assert words("What was our Q4 2025 revenue of $4.2M, up 12%?") == [
        "q4", "2025", "revenue", "4.2m", "12"]


def test_serve_logs_one_warning_and_closes_the_server(caplog):
    with mock.patch.object(server_module.MockServer, "serve_forever", side_effect=KeyboardInterrupt), \
            mock.patch.object(server_module.signal, "signal") as handler, \
            caplog.at_level(logging.WARNING, logger="llm_mock"):
        server_module.serve(Settings(), host="127.0.0.1", port=0)
    warnings = [record for record in caplog.records if record.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "Mock AI mode" in warnings[0].getMessage()
    assert "computes embeddings from the words of each text" in warnings[0].getMessage()
    assert "No AI model runs" in warnings[0].getMessage()
    assert handler.call_args[0][0] == signal.SIGTERM
    with pytest.raises(SystemExit):
        handler.call_args[0][1](signal.SIGTERM, None)


def test_running_the_package_serves_with_the_environment(monkeypatch):
    monkeypatch.setenv("HORUS_MOCK_SCENARIO", "refuse")
    with mock.patch.object(server_module, "serve") as serve, \
            mock.patch.object(server_module.logging, "basicConfig"):
        runpy.run_module("llm_mock", run_name="__main__")
    assert serve.call_args[0][0].scenario == "refuse"
