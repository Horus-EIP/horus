import pytest
from unittest.mock import patch

from core.llm_setup import ask_llm


def test_ask_llm_raises_when_not_initialized():
    """When the LLM was not loaded, ask_llm must fail loudly (no fake router JSON)."""
    with patch("core.llm_setup.tokenizer", None), patch("core.llm_setup.model", None):
        with pytest.raises(RuntimeError, match="LLM is not loaded"):
            ask_llm([{"role": "user", "content": "Hello"}])


def test_ask_llm_raises_when_not_initialized_empty_messages():
    with patch("core.llm_setup.tokenizer", None), patch("core.llm_setup.model", None):
        with pytest.raises(RuntimeError, match="LLM is not loaded"):
            ask_llm([])
