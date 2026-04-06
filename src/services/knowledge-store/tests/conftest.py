import os
import sys
import types
from unittest.mock import MagicMock

# GLOBAL ENVIRONMENT PATCHES
# Patch spacy to avoid Python 3.14/Pydantic V1 issues
# We must use a ModuleType with __spec__ to satisfy importlib/transformers checks
spacy_mock = types.ModuleType("spacy")
spacy_mock.__spec__ = types.SimpleNamespace(origin="mock", submodule_search_locations=[])

# Configure nlp mock to return a doc with sents for chunker
doc_mock = MagicMock()
sent_mock = MagicMock()
sent_mock.text = "This is a sentence."
doc_mock.sents = [sent_mock]
doc_mock.ents = []
doc_mock.noun_chunks = []
nlp_mock = MagicMock(return_value=doc_mock)

spacy_mock.load = MagicMock(return_value=nlp_mock)
sys.modules["spacy"] = spacy_mock
sys.modules["spacy.cli"] = MagicMock()

# Mock spacy.lang and submodules for content_analyzer
spacy_lang = types.ModuleType("spacy.lang")
sys.modules["spacy.lang"] = spacy_lang

spacy_lang_en = types.ModuleType("spacy.lang.en")
sys.modules["spacy.lang.en"] = spacy_lang_en

spacy_lang_en_stop_words = types.ModuleType("spacy.lang.en.stop_words")
spacy_lang_en_stop_words.STOP_WORDS = set(["a", "the", "is", "in"])
sys.modules["spacy.lang.en.stop_words"] = spacy_lang_en_stop_words


# Patch chromadb to avoid Pydantic V2/BaseSettings issues
# We need to ensure it looks like a package if finding spec
chromadb_mock = types.ModuleType("chromadb")
chromadb_mock.__spec__ = types.SimpleNamespace(origin="mock", submodule_search_locations=[])
chromadb_mock.PersistentClient = MagicMock()
# Configure default query response
chromadb_mock.PersistentClient.return_value.get_collection.return_value.query.return_value = {
    "ids": [["test_id"]],
    "documents": [["test content"]],
    "metadatas": [[{"title": "test", "size": 100, "date": "2023-01-01"}]]
}
chromadb_mock.PersistentClient.return_value.create_collection.return_value.query.return_value = {
    "ids": [["test_id"]],
    "documents": [["test content"]],
    "metadatas": [[{"title": "test", "size": 100, "date": "2023-01-01"}]]
}
sys.modules["chromadb"] = chromadb_mock

chromadb_config_mock = types.ModuleType("chromadb.config")
chromadb_config_mock.Settings = MagicMock()
sys.modules["chromadb.config"] = chromadb_config_mock

# Mock sentence_transformers to avoid model download
sentence_transformers_mock = types.ModuleType("sentence_transformers")
sentence_transformers_mock.SentenceTransformer = MagicMock()
sys.modules["sentence_transformers"] = sentence_transformers_mock

import time
import socket
import subprocess
import atexit
import pytest
from httpx import AsyncClient, ASGITransport

# Define port for Knowledge Store
PORT = 8080

def _is_port_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=1):
            return True
    except Exception:
        return False

@pytest.fixture(scope="session", autouse=False)
def ensure_server_running():
    """Ensure the local server is running for integration tests.

    If nothing listens on localhost:8080, this fixture will start the
    repository's `run_local.sh` script in a background process and wait for the port to be available.
    The process is terminated at the end of the test session.
    """
    host = os.getenv("TEST_HOST", "localhost")
    port = int(os.getenv("TEST_PORT", str(PORT)))

    if _is_port_open(host, port):
        # Server already running, nothing to do
        yield
        return

    # Try to load env file from repo infra
    tests_dir = os.path.dirname(__file__)
    repo_service_dir = os.path.abspath(os.path.join(tests_dir, ".."))
    infra_env = os.path.abspath(os.path.join(repo_service_dir, "..", "..", "infra", ".env"))

    env = os.environ.copy()
    if os.path.exists(infra_env):
        with open(infra_env, "r") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    k, v = line.split("=", 1)
                    env[k.strip()] = v.strip()

    # Disable auto-init of heavy resources if applicable
    env.setdefault("LLM_AUTOINIT", "0")

    # Start the run_local.sh script
    run_script = os.path.join(repo_service_dir, "run_local.sh")
    if not os.path.exists(run_script):
        pytest.skip("run_local.sh not found; cannot start local server for integration tests")

    # Use exec to replace shell with python process if run_local.sh just runs python?
    # No, run_local.sh sets env vars then runs uvicorn. Popen is fine.
    proc = subprocess.Popen(["bash", "run_local.sh"], cwd=repo_service_dir, env=env)

    def _cleanup():
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            proc.kill()

    atexit.register(_cleanup)

    # Wait for server port to become available
    for _ in range(60):
        if _is_port_open(host, port):
            break
        time.sleep(1)
    else:
        _cleanup()
        pytest.skip(f"Could not start server for integration tests (port {port} not open)")

    yield

    # Teardown: terminate process
    _cleanup()

@pytest.fixture
async def async_client():
    from app.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
