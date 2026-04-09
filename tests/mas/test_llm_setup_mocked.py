import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import torch

from core.llm_setup import _bnb4bit, ask_llm, get_llm, is_model_dir_exists


def test_is_model_dir_exists_false():
    with patch("os.path.exists", return_value=False):
        assert is_model_dir_exists() is False


def test_is_model_dir_exists_missing_files():
    with patch(
        "os.path.exists", side_effect=lambda p: str(p) == "./models/Qwen3_instruct_4B"
    ):
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
        with patch(
            "core.llm_setup.AutoTokenizer.from_pretrained", return_value=mock_tokenizer
        ):
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

    with patch(
        "core.llm_setup.AutoTokenizer.from_pretrained", return_value=mock_tokenizer
    ):
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
