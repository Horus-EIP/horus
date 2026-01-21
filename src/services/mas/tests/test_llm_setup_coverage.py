import os
from unittest.mock import MagicMock, patch

import pytest
import torch

# We need to patch before importing core.llm_setup because of the module-level execution
with patch.dict(os.environ, {"LLM_AUTOINIT": "0"}):
    import core.llm_setup
    from core.llm_setup import _bnb4bit, ask_llm, get_llm, is_model_dir_exists


class TestLLMSetupCoverage:

    @patch("core.llm_setup.os.path.exists")
    def test_is_model_dir_exists_false(self, mock_exists):
        mock_exists.return_value = False
        assert is_model_dir_exists() is False

    @patch("core.llm_setup.os.path.exists")
    @patch("pathlib.Path.exists")
    def test_is_model_dir_exists_missing_files(self, mock_path_exists, mock_os_exists):
        mock_os_exists.return_value = True
        # Simulate one file missing (False) among others (True)
        mock_path_exists.side_effect = [True, False, True, True]
        assert is_model_dir_exists() is False

    @patch("core.llm_setup.os.path.exists")
    @patch("pathlib.Path.exists")
    def test_is_model_dir_exists_true(self, mock_path_exists, mock_os_exists):
        mock_os_exists.return_value = True
        mock_path_exists.return_value = True
        assert is_model_dir_exists() is True

    @patch("core.llm_setup.BitsAndBytesConfig")
    @patch("core.llm_setup.torch.cuda.is_available")
    def test_bnb4bit_cuda(self, mock_cuda, mock_bnb):
        mock_cuda.return_value = True
        _bnb4bit()
        mock_bnb.assert_called_once()

    @patch("core.llm_setup.BitsAndBytesConfig")
    @patch("core.llm_setup.torch.cuda.is_available")
    @patch("core.llm_setup.torch.cuda.is_bf16_supported")
    def test_bnb4bit_cuda_bf16(self, mock_bf16, mock_cuda, mock_bnb):
        mock_cuda.return_value = True
        mock_bf16.return_value = True
        _bnb4bit()
        mock_bnb.assert_called_once()
        assert mock_bnb.call_args[1]["bnb_4bit_compute_dtype"] == torch.bfloat16

    @patch("core.llm_setup.BitsAndBytesConfig")
    @patch("core.llm_setup.torch.cuda.is_available")
    @patch("core.llm_setup.torch.cuda.is_bf16_supported")
    def test_bnb4bit_cuda_no_bf16(self, mock_bf16, mock_cuda, mock_bnb):
        mock_cuda.return_value = True
        mock_bf16.return_value = False
        _bnb4bit()
        mock_bnb.assert_called_once()
        assert mock_bnb.call_args[1]["bnb_4bit_compute_dtype"] == torch.float16

    @patch("core.llm_setup.BitsAndBytesConfig")
    @patch("core.llm_setup.torch.cuda.is_available")
    def test_bnb4bit_no_cuda(self, mock_cuda, mock_bnb):
        mock_cuda.return_value = False
        _bnb4bit()
        mock_bnb.assert_called_once()
        assert mock_bnb.call_args[1]["bnb_4bit_compute_dtype"] == torch.float16

    def test_ask_llm(self):
        # Manually inject mocks into the module
        mock_tokenizer = MagicMock()
        mock_model = MagicMock()

        core.llm_setup.tokenizer = mock_tokenizer
        core.llm_setup.model = mock_model

        # Setup mocks
        mock_tokenizer.apply_chat_template.return_value = "prompt"
        mock_tokenizer.return_value = {
            "input_ids": MagicMock(
                to=MagicMock(return_value=MagicMock(size=MagicMock(return_value=10)))
            ),
            "attention_mask": MagicMock(to=MagicMock()),
        }
        mock_tokenizer.eos_token_id = 1

        mock_out = MagicMock()
        mock_out.sequences = [MagicMock()]
        mock_model.generate.return_value = mock_out
        mock_model.device = "cpu"

        mock_tokenizer.decode.return_value = "response"

        response = ask_llm([{"role": "user", "content": "hi"}])

        assert response == "response"
        mock_model.generate.assert_called_once()

    def test_ask_llm_no_attention_mask(self):
        # Manually inject mocks into the module
        mock_tokenizer = MagicMock()
        mock_model = MagicMock()

        core.llm_setup.tokenizer = mock_tokenizer
        core.llm_setup.model = mock_model

        # Setup mocks
        mock_tokenizer.apply_chat_template.return_value = "prompt"
        # Return None for attention_mask
        mock_tokenizer.return_value = {
            "input_ids": MagicMock(
                to=MagicMock(return_value=MagicMock(size=MagicMock(return_value=10)))
            ),
            "attention_mask": None,
        }
        mock_tokenizer.eos_token_id = 1

        mock_out = MagicMock()
        mock_out.sequences = [MagicMock()]
        mock_model.generate.return_value = mock_out
        mock_model.device = "cpu"

        mock_tokenizer.decode.return_value = "response"

        response = ask_llm([{"role": "user", "content": "hi"}])

        assert response == "response"
        mock_model.generate.assert_called_once()
        # Verify attention_mask passed to generate is None
        assert mock_model.generate.call_args[1]["attention_mask"] is None
