import os

import pytest
from model_server import EmbeddingsServers, ModelServer, RunningMock


@pytest.fixture(scope="session")
def running_mock():
    running = RunningMock()
    yield running
    running.stop()


@pytest.fixture(scope="session")
def mock_server(running_mock):
    return ModelServer(running_mock.url)


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


SERVICE_MODELS = {
    "mas": "sentence-transformers/all-MiniLM-L6-v2",
    "knowledge_store": "BAAI/bge-base-en-v1.5",
}


def real_embeddings_server(service: str) -> tuple[str, str]:
    setting = f"HORUS_CONTRACT_{service.upper()}_EMBED"
    url = os.environ.get(f"{setting}_URL", "").strip()
    if not url:
        pytest.skip(f"set {setting}_URL to the OpenAI-compatible URL of a real embeddings server, "
                    f"as you would set {service.upper()}_EMBED_URL")
    return url, os.environ.get(f"{setting}_MODEL", "").strip() or SERVICE_MODELS[service]


@pytest.fixture(scope="session")
def mock_embeddings(running_mock):
    return EmbeddingsServers(lambda service: (running_mock.url, None))


@pytest.fixture(scope="session")
def real_embeddings():
    return EmbeddingsServers(real_embeddings_server)


@pytest.fixture(params=[
    pytest.param("mock"),
    pytest.param("real", marks=pytest.mark.real_embeddings),
])
def embeddings(request):
    return request.getfixturevalue(f"{request.param}_embeddings")
