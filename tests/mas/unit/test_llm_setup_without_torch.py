import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

LLM_SETUP = Path(__file__).resolve().parents[3] / "src" / "services" / "mas" / "core" / "llm_setup.py"


@pytest.fixture
def cpu_image_llm_setup(monkeypatch):
    for missing in ("torch", "transformers"):
        monkeypatch.setitem(sys.modules, missing, None)
    spec = importlib.util.spec_from_file_location("llm_setup_in_a_cpu_image", LLM_SETUP)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _server_reply(content: str) -> MagicMock:
    response = MagicMock()
    response.read.return_value = json.dumps(
        {"choices": [{"message": {"content": content}}]}
    ).encode("utf-8")
    response.__enter__.return_value = response
    return response


def test_the_module_imports_without_torch_or_transformers(cpu_image_llm_setup):
    assert cpu_image_llm_setup.torch is None
    assert cpu_image_llm_setup.AutoModelForCausalLM is None


def test_the_llm_server_answers_without_torch(cpu_image_llm_setup, monkeypatch):
    monkeypatch.setenv("LLM_BACKEND", "vllm")

    with patch("urllib.request.urlopen", return_value=_server_reply("routed")):
        answer = cpu_image_llm_setup.ask_llm([{"role": "user", "content": "route me"}])

    assert answer == "routed"


def test_the_in_process_router_names_what_the_image_lacks(cpu_image_llm_setup, monkeypatch):
    monkeypatch.setenv("LLM_BACKEND", "transformers")

    with pytest.raises(RuntimeError, match="LLM_BACKEND=vllm"):
        cpu_image_llm_setup.ask_llm([{"role": "user", "content": "route me"}])


def test_loading_the_in_process_router_names_what_the_image_lacks(cpu_image_llm_setup):
    with pytest.raises(RuntimeError, match="torch and transformers"):
        cpu_image_llm_setup.get_llm()
