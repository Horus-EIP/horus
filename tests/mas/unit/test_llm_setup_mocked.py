import json
import os
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import torch
from prometheus_client import REGISTRY

from core.llm_setup import _bnb4bit, ask_llm, get_llm, is_model_dir_exists


def test_is_model_dir_exists_false():
    with patch("os.path.exists", return_value=False):
        assert is_model_dir_exists() is False


def test_is_model_dir_exists_missing_files():
    with patch("os.path.exists", side_effect=lambda p: str(p) == "./models/Qwen3_instruct_4B"):
        # MODEL_DIR exists, but files inside don't
        assert is_model_dir_exists() is False


def test_is_model_dir_exists_true():
    with patch("os.path.exists", return_value=True):
        with patch("pathlib.Path.exists", return_value=True):
            assert is_model_dir_exists() is True


def test_bnb4bit():
    config = _bnb4bit()
    assert config.load_in_4bit is True
    assert config.bnb_4bit_quant_type == "nf4"


def test_get_llm_mocked_cpu_path():
    mock_tokenizer = MagicMock()
    mock_model = MagicMock()
    with patch("torch.cuda.is_available", return_value=False):
        with patch("core.llm_setup.AutoTokenizer.from_pretrained", return_value=mock_tokenizer):
            with patch(
                "core.llm_setup.AutoModelForCausalLM.from_pretrained",
                return_value=mock_model,
            ):
                with patch("core.llm_setup.is_model_dir_exists", return_value=False):
                    tokenizer, model = get_llm()
                    assert tokenizer == mock_tokenizer
                    assert model == mock_model
                    mock_model.eval.assert_called_once()


def test_get_llm_mocked_with_gpu():
    mock_tokenizer = MagicMock()
    mock_model = MagicMock()

    with patch("core.llm_setup.AutoTokenizer.from_pretrained", return_value=mock_tokenizer):
        with patch(
            "core.llm_setup.AutoModelForCausalLM.from_pretrained",
            return_value=mock_model,
        ):
            with patch("torch.cuda.is_available", return_value=True):
                with patch(
                    "core.llm_setup.is_model_dir_exists", return_value=False
                ):  # Force download path
                    tokenizer, model = get_llm()
                    assert tokenizer == mock_tokenizer
                    assert model == mock_model
                    mock_model.eval.assert_called_once()


def test_ask_llm_mocked():
    mock_tokenizer = MagicMock()
    mock_model = MagicMock()
    mock_param = MagicMock()
    mock_param.device = torch.device("cpu")
    mock_model.parameters = MagicMock(return_value=iter([mock_param]))

    # Mock tokenizer behavior
    mock_tokenizer.apply_chat_template.return_value = "prompt"
    mock_tokenizer.return_value = {
        "input_ids": MagicMock(),
        "attention_mask": MagicMock(),
    }
    mock_tokenizer.decode.return_value = "response"
    mock_tokenizer.eos_token_id = 1

    # Mock model generation
    mock_out = MagicMock()
    mock_out.sequences = [MagicMock()]
    mock_model.generate.return_value = mock_out

    # We need to patch the module-level tokenizer and model variables in core.llm_setup
    with patch("core.llm_setup.tokenizer", mock_tokenizer):
        with patch("core.llm_setup.model", mock_model):
            response = ask_llm([{"role": "user", "content": "hello"}])
            assert response == "response"


def _fake_router_llm(generate):
    tokenizer = MagicMock()
    tokenizer.apply_chat_template.return_value = "prompt"
    tokenizer.return_value = {"input_ids": MagicMock(), "attention_mask": MagicMock()}
    tokenizer.decode.return_value = "routed"
    tokenizer.eos_token_id = 1
    model = MagicMock()
    param = MagicMock()
    param.device = "cpu"
    model.parameters = MagicMock(side_effect=lambda: iter([param]))
    model.generate.side_effect = generate
    return tokenizer, model


class _ConcurrencyProbe:
    def __init__(self, hold_seconds: float, result=None):
        self.hold_seconds = hold_seconds
        self.result = result
        self.active = 0
        self.peak = 0
        self._lock = threading.Lock()

    def __call__(self, *args, **kwargs):
        with self._lock:
            self.active += 1
            self.peak = max(self.peak, self.active)
        time.sleep(self.hold_seconds)
        with self._lock:
            self.active -= 1
        return self.result


def _ask_from_threads(count: int) -> list:
    answers: list = []
    threads = [
        threading.Thread(
            target=lambda: answers.append(ask_llm([{"role": "user", "content": "route me"}]))
        )
        for _ in range(count)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    return answers


def test_in_process_router_generates_one_request_at_a_time(monkeypatch):
    monkeypatch.setenv("LLM_BACKEND", "transformers")
    out = MagicMock()
    out.sequences = [MagicMock()]
    probe = _ConcurrencyProbe(0.2, out)
    tokenizer, model = _fake_router_llm(probe)

    with patch("core.llm_setup.tokenizer", tokenizer), patch("core.llm_setup.model", model):
        answers = _ask_from_threads(3)

    assert answers == ["routed", "routed", "routed"]
    assert model.generate.call_count == 3
    assert probe.peak == 1


def test_openai_compatible_backend_leaves_scheduling_to_the_server(monkeypatch):
    monkeypatch.setenv("LLM_BACKEND", "vllm")
    response = MagicMock()
    response.read.return_value = json.dumps(
        {"choices": [{"message": {"content": "routed"}}]}
    ).encode("utf-8")
    response.__enter__.return_value = response
    probe = _ConcurrencyProbe(0.2, response)

    with patch("urllib.request.urlopen", probe):
        answers = _ask_from_threads(2)

    assert answers == ["routed", "routed"]
    assert probe.peak == 2


class _PromptIds:
    def __init__(self, length: int):
        self.length = length

    def to(self, _device):
        return self

    def size(self, _dimension: int) -> int:
        return self.length


def test_the_in_process_router_records_the_tokenizer_count_of_its_prompt(monkeypatch):
    monkeypatch.setenv("LLM_BACKEND", "transformers")
    out = MagicMock()
    out.sequences = [list(range(60))]
    tokenizer, model = _fake_router_llm(lambda **_kwargs: out)
    tokenizer.return_value = {"input_ids": _PromptIds(57)}
    labels = {"call": "intent", "source": "tokenizer"}
    sum_before = REGISTRY.get_sample_value("mas_llm_prompt_tokens_sum", labels) or 0.0

    with patch("core.llm_setup.tokenizer", tokenizer), patch("core.llm_setup.model", model):
        assert ask_llm([{"role": "user", "content": "route me"}], 16, call="intent") == "routed"

    assert REGISTRY.get_sample_value("mas_llm_prompt_tokens_sum", labels) == sum_before + 57
    assert tokenizer.decode.call_args.args[0] == [57, 58, 59]
