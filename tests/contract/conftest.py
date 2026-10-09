import os

import pytest
from model_server import ModelServer, RunningMock


@pytest.fixture(scope="session")
def mock_server():
    running = RunningMock()
    yield ModelServer(running.url)
    running.stop()


@pytest.fixture(scope="session")
def real_server():
    url = os.environ.get("HORUS_CONTRACT_LLM_URL", "").strip()
    if not url:
        pytest.skip("set HORUS_CONTRACT_LLM_URL to the OpenAI-compatible URL of a real model server")
    return ModelServer(url, os.environ.get("HORUS_CONTRACT_LLM_MODEL", "").strip() or None)


@pytest.fixture(params=[
    pytest.param("mock"),
    pytest.param("real", marks=pytest.mark.real_llm),
])
def server(request):
    return request.getfixturevalue(f"{request.param}_server")
