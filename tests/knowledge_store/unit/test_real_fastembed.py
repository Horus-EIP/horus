from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from importlib import metadata
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
SERVICE = REPO / "src" / "services" / "knowledge-store"
DEMO = REPO / "demo_assets"
ANSWERED_BY = {
    "What was our Q4 2025 revenue?": "1_Q4_2025_Financial_Report.md",
    "How many vacation days can be carried over?": "2_Employee_Handbook.md",
    "How often must passwords be changed?": "5_IT_Security_Policy.md",
}
REQUIRED = os.environ.get("HORUS_REQUIRE_MODEL_TESTS") == "1"

SEARCH = r"""
import json, sys, types

class Collections:
    def __init__(self, *args, **kwargs):
        pass

    def get_collection(self, name):
        raise ValueError(name)

    def create_collection(self, name, metadata=None):
        return types.SimpleNamespace(name=name, metadata=metadata)

chromadb = types.ModuleType("chromadb")
chromadb.PersistentClient = Collections
config = types.ModuleType("chromadb.config")
config.Settings = lambda **kwargs: kwargs
sys.modules.update({"chromadb": chromadb, "chromadb.config": config})

from app.chroma_db import setup
from app.services.document_chunker import DocumentChunker

documents, questions = json.loads(sys.stdin.read())
passages = [(title, chunk.text) for title, text in documents.items()
            for chunk in DocumentChunker().split(text)]
vectors = setup.get_embeddings([text for _, text in passages])
closest = {}
for question in questions:
    asked = setup.get_embedding(question, is_query=True)
    scores = [sum(a * b for a, b in zip(asked, vector)) for vector in vectors]
    closest[question] = passages[scores.index(max(scores))][0]
print(json.dumps({
    "embed_model": setup.EMBED_MODEL,
    "embedder": type(setup.model).__module__,
    "sizes": sorted({len(vector) for vector in vectors}),
    "closest": closest,
}))
"""


def model_cache() -> Path:
    return Path(
        os.environ.get("FASTEMBED_CACHE_PATH") or Path(tempfile.gettempdir()) / "fastembed_cache"
    )


def missing() -> str | None:
    try:
        metadata.version("fastembed")
    except metadata.PackageNotFoundError:
        return "fastembed is not installed"
    if not any(model_cache().glob("*bge-base-en-v1.5*")):
        return f"BAAI/bge-base-en-v1.5 is not in the FastEmbed cache at {model_cache()}"
    return None


@pytest.mark.requires_model
def test_real_fastembed_finds_the_passage_that_answers_each_question():
    reason = missing()
    if reason and REQUIRED:
        pytest.fail(f"HORUS_REQUIRE_MODEL_TESTS=1, but {reason}")
    if reason:
        pytest.skip(reason)
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in ("KNOWLEDGE_STORE_EMBED_URL", "KNOWLEDGE_STORE_EMBED_MODEL")
    }
    env.update(PYTHONPATH=str(SERVICE), HF_HUB_OFFLINE="1", KNOWLEDGE_STORE_EMBED_DEVICE="cpu")
    documents = {
        title: (DEMO / title).read_text(encoding="utf-8")
        for title in sorted(set(ANSWERED_BY.values()))
    }
    done = subprocess.run(
        [sys.executable, "-c", SEARCH],
        input=json.dumps([documents, list(ANSWERED_BY)]),
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        cwd=SERVICE,
        timeout=600,
        check=False,
    )
    assert done.returncode == 0, done.stderr[-3000:]
    found = json.loads(done.stdout.strip().splitlines()[-1])
    assert (
        found["embed_model"] == f"fastembed-{metadata.version('fastembed')}:BAAI/bge-base-en-v1.5"
    )
    assert found["embedder"].startswith("fastembed")
    assert found["sizes"] == [768]
    assert found["closest"] == ANSWERED_BY
