"""Service-level fixtures for Knowledge Store tests.

Hermetic — no real ChromaDB, no real spaCy model download, no live KS
server. Heavy ML / NLP libraries are replaced with ``MagicMock``\\ s so the
import graph stays light.

The live-server launcher that used to live here (subprocess +
run-knowledge-store.sh) moved to ``scripts/integration-checks/`` and only
runs when you invoke pytest with ``-m requires_stack``.
"""

from __future__ import annotations

import os
import sys
import types
from unittest.mock import MagicMock

os.environ.setdefault("TEST_MODE", "1")

# --------------------------------------------------------------------------- #
# spaCy — replace with a mock module that returns a doc with one sentence.
# --------------------------------------------------------------------------- #

_spacy = types.ModuleType("spacy")
_spacy.__spec__ = types.SimpleNamespace(origin="mock", submodule_search_locations=[])

_doc = MagicMock()
_sentence = MagicMock()
_sentence.text = "This is a sentence."
_doc.sents = [_sentence]
_doc.ents = []
_doc.noun_chunks = []
_nlp = MagicMock(return_value=_doc)

_spacy.load = MagicMock(return_value=_nlp)
sys.modules["spacy"] = _spacy
sys.modules["spacy.cli"] = MagicMock()
sys.modules["spacy.lang"] = types.ModuleType("spacy.lang")
sys.modules["spacy.lang.en"] = types.ModuleType("spacy.lang.en")

_stop_words = types.ModuleType("spacy.lang.en.stop_words")
_stop_words.STOP_WORDS = {"a", "the", "is", "in"}
sys.modules["spacy.lang.en.stop_words"] = _stop_words

# --------------------------------------------------------------------------- #
# ChromaDB — replace PersistentClient with a configurable mock.
# --------------------------------------------------------------------------- #

_chromadb = types.ModuleType("chromadb")
_chromadb.__spec__ = types.SimpleNamespace(origin="mock", submodule_search_locations=[])
_chromadb.PersistentClient = MagicMock()

_query_result = {
    "ids": [["test_id"]],
    "documents": [["test content"]],
    "metadatas": [[{"title": "test", "size": 100, "date": "2023-01-01"}]],
}
_chromadb.PersistentClient.return_value.get_collection.return_value.query.return_value = _query_result
_chromadb.PersistentClient.return_value.create_collection.return_value.query.return_value = _query_result
sys.modules["chromadb"] = _chromadb

_chromadb_config = types.ModuleType("chromadb.config")
_chromadb_config.Settings = MagicMock()
sys.modules["chromadb.config"] = _chromadb_config

# --------------------------------------------------------------------------- #
# SentenceTransformers — replace so no model is downloaded at import time.
# --------------------------------------------------------------------------- #

_st = types.ModuleType("sentence_transformers")
_st.SentenceTransformer = MagicMock()
sys.modules["sentence_transformers"] = _st

# --------------------------------------------------------------------------- #
# Lightweight client fixture for ``api/`` tests.
# --------------------------------------------------------------------------- #

import pytest  # noqa: E402


@pytest.fixture
async def async_client():
    """In-process httpx client over the KS ASGI app — no network, no server."""
    from httpx import ASGITransport, AsyncClient  # noqa: PLC0415

    from app.main import app  # noqa: PLC0415

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


def _metadata_matches(metadata: dict, where: dict | None) -> bool:
    if not where:
        return True
    for key, condition in where.items():
        if key == "$and":
            if not all(_metadata_matches(metadata, part) for part in condition):
                return False
            continue
        if key == "$or":
            if not any(_metadata_matches(metadata, part) for part in condition):
                return False
            continue
        operator, expected = (
            next(iter(condition.items())) if isinstance(condition, dict) else ("$eq", condition)
        )
        value = metadata.get(key)
        if operator == "$eq" and value != expected:
            return False
        if operator == "$ne" and value == expected:
            return False
        if operator == "$in" and value not in expected:
            return False
    return True


class FakeChromaCollection:
    def __init__(self):
        self.rows: dict[str, tuple[str, dict]] = {}

    def add(self, ids, documents, metadatas, embeddings=None):
        for entry_id, document, metadata in zip(ids, documents, metadatas, strict=True):
            self.rows[entry_id] = (document, dict(metadata))

    def _select(self, ids=None, where=None) -> list[str]:
        return [
            entry_id for entry_id, (_document, metadata) in self.rows.items()
            if (ids is None or entry_id in ids) and _metadata_matches(metadata, where)
        ]

    def get(self, ids=None, where=None, include=None):
        selected = self._select(ids, where)
        return {
            "ids": selected,
            "documents": [self.rows[i][0] for i in selected],
            "metadatas": [dict(self.rows[i][1]) for i in selected],
        }

    def query(self, query_embeddings, n_results, include=None, where=None):
        selected = self._select(where=where)[:n_results]
        return {
            "ids": [selected],
            "documents": [[self.rows[i][0] for i in selected]],
            "metadatas": [[dict(self.rows[i][1]) for i in selected]],
            "distances": [[0.0 for _ in selected]],
        }

    def delete(self, ids):
        if not ids:
            raise ValueError("Expected IDs to be a non-empty list, got 0 IDs in delete.")
        for entry_id in ids:
            self.rows.pop(entry_id, None)


@pytest.fixture
def fake_collection(monkeypatch, tmp_path):
    from app.api.routes import corpus, file, store  # noqa: PLC0415
    from app.chroma_db.services import file_service  # noqa: PLC0415

    collection = FakeChromaCollection()
    for module in (file_service, store, file, corpus):
        monkeypatch.setattr(module, "knowledge_collection", collection)
    monkeypatch.chdir(tmp_path)
    return collection


@pytest.fixture
def documents_root(fake_collection, tmp_path):
    root = tmp_path / "documents"
    root.mkdir()
    return root


@pytest.fixture
def deleted_sources_file(monkeypatch, tmp_path):
    from app.chroma_db.services import deleted_sources  # noqa: PLC0415

    path = tmp_path / "chroma_data" / "deleted_sources.json"
    monkeypatch.setattr(deleted_sources, "DELETED_SOURCES_FILE", path)
    return path
