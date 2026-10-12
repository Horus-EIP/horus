"""
Pytest configuration for async tests.
"""
import os
import sys
from unittest.mock import MagicMock

import pytest

os.environ.pop("HORUS_SPACY", None)

# --- Robust Environment Mocking ---
# Prevent langchain imports from hanging or failing in restricted environments
if "langchain" not in sys.modules:
    mock_lc = MagicMock()
    sys.modules["langchain"] = mock_lc

    # Mock langchain.tools
    mock_tools = MagicMock()
    sys.modules["langchain.tools"] = mock_tools

    class MockBaseTool:
        name: str = "mock_tool"
        description: str = "mock"
        def __init__(self, *args, **kwargs): pass
        def _run(self, *args, **kwargs): return "Mock Result"
        def _arun(self, *args, **kwargs): raise NotImplementedError
        def run(self, *args, **kwargs):
            # args[0] is usually the input.
            # If input is dict and tool expects string, normally BaseTool handles it.
            # But for mock we just pass to _run
            if args and isinstance(args[0], dict) and not kwargs:
                return self._run(**args[0])
            return self._run(*args, **kwargs)

    # Assign BaseTool to the module
    mock_tools.BaseTool = MockBaseTool
    # Also ensure "from langchain.tools import BaseTool" works by setting attribute on the module mock
    # (MagicMock handles attributes, but explicit assignment ensures class vs instance behavior if needed)

# This file ensures pytest-asyncio is loaded as a plugin
pytest_plugins = ('pytest_asyncio',)

@pytest.fixture(autouse=True)
def mock_transformers_pipeline(monkeypatch):
    """
    Mock transformers.pipeline (summarizer, etc.) and causal LM loading for DecisionMakingAgent
    to prevent accidental Hugging Face downloads in tests.
    """
    mock_pipe = MagicMock()

    try:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        inp = torch.tensor([[1, 2, 3]])
        attn = torch.tensor([[1, 1, 1]])

        mock_tok = MagicMock()
        mock_tok.apply_chat_template.return_value = "formatted"
        mock_tok.return_value = {"input_ids": inp, "attention_mask": attn}
        mock_tok.eos_token_id = 0
        mock_tok.decode.return_value = "stub answer"

        out_seq = torch.cat([inp, torch.tensor([[9]])], dim=-1)
        mock_gen_ret = MagicMock()
        mock_gen_ret.sequences = [out_seq]

        mock_mdl = MagicMock()
        mock_mdl.generate.return_value = mock_gen_ret
        mock_mdl.parameters.return_value = iter(
            [torch.nn.Parameter(torch.tensor([1.0], dtype=torch.float32))]
        )

        monkeypatch.setattr(
            AutoTokenizer, "from_pretrained", MagicMock(return_value=mock_tok)
        )
        monkeypatch.setattr(
            AutoModelForCausalLM, "from_pretrained", MagicMock(return_value=mock_mdl)
        )
    except (ImportError, AttributeError):
        pass

    try:
        import transformers

        monkeypatch.setattr(transformers, "pipeline", mock_pipe)
    except (ImportError, AttributeError):
        pass

    return mock_pipe



# Mock transformers to prevent model loading
import sys


class StoppingCriteria:
    pass


if "transformers" not in sys.modules:
    mock_tf = MagicMock()
    mock_tf.StoppingCriteria = StoppingCriteria
    mock_tf.StoppingCriteriaList = list
    sys.modules["transformers"] = mock_tf
    mock_tf.pipeline.return_value = MagicMock()

if "torch" not in sys.modules:
    sys.modules["torch"] = MagicMock()
