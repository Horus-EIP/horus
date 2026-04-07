"""
Pytest configuration for async tests.
"""
import sys
import pytest
from unittest.mock import MagicMock

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
    Globally mock transformers.pipeline to prevent accidental model downloads.
    """
    mock_pipe = MagicMock()
    
    # Patch the real source of the pipeline
    # Be careful if transformers is not installed, but here we assume it might be.
    # We use string path for sys.modules check or just try/except.
    
    # 1. Patch 'transformers.pipeline' directly if transformers is importable
    try:
        import transformers
        monkeypatch.setattr(transformers, "pipeline", mock_pipe)
    except (ImportError, AttributeError):
        pass

    # 2. Patch any existing module-level imports that might have occurred
    for module in ["ai_agents.decision_making_agent", "ai_agents.summarizer_tool"]:
        try:
            monkeypatch.setattr(f"{module}.pipeline", mock_pipe)
        except (ImportError, AttributeError, KeyError):
            pass

    return mock_pipe



# Mock transformers to prevent model loading
import sys
if "transformers" not in sys.modules:
    mock_tf = MagicMock()
    sys.modules["transformers"] = mock_tf
    mock_tf.pipeline.return_value = MagicMock()

if "torch" not in sys.modules:
    sys.modules["torch"] = MagicMock()
