from __future__ import annotations

import importlib.util
import runpy
import sys
from pathlib import Path

import numpy as np
import pytest

from app.chroma_db import setup

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "perf" / "retrieval-quality.py"
QUESTION = "What was Q4 revenue?"


class FastEmbedLikeModel:
    def __init__(self):
        self.embedded: list[str] = []

    def embed(self, texts):
        self.embedded.extend(texts)
        return [np.array([float(len(text)), 1.0]) for text in texts]


class RecordingCollection:
    def __init__(self):
        self.queries: list[dict] = []

    def query(self, query_embeddings, n_results, include):
        self.queries.append(
            {"query_embeddings": query_embeddings, "n_results": n_results, "include": include}
        )
        return {
            "ids": [["q4:0", "handbook:3"][:n_results]],
            "documents": [["Revenue was 4.2M in Q4.", "Travel needs approval."][:n_results]],
            "distances": [[0.25, 0.75][:n_results]],
        }


@pytest.fixture
def knowledge_store(monkeypatch):
    model, collection = FastEmbedLikeModel(), RecordingCollection()
    monkeypatch.setattr(setup, "model", model)
    monkeypatch.setattr(setup, "knowledge_collection", collection)
    return model, collection


def run_script(monkeypatch, *args: str) -> None:
    monkeypatch.setattr(sys, "argv", [str(SCRIPT), *args])
    with pytest.raises(SystemExit) as finished:
        runpy.run_path(str(SCRIPT), run_name="__main__")
    assert finished.value.code == 0


def load_script():
    spec = importlib.util.spec_from_file_location("retrieval_quality_script", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_queries_are_embedded_by_the_knowledge_store_with_the_bge_prefix_once(
    monkeypatch, capsys, knowledge_store
):
    model, collection = knowledge_store

    run_script(monkeypatch, QUESTION)

    assert model.embedded == [setup.BGE_QUERY_PREFIX + QUESTION]
    (query,) = collection.queries
    assert query["query_embeddings"] == [[float(len(setup.BGE_QUERY_PREFIX + QUESTION)), 1.0]]
    assert "documents" in query["include"] and "distances" in query["include"]
    output = capsys.readouterr().out
    assert setup.EMBED_MODEL in output
    assert f"Query: {QUESTION}" in output
    assert "(Score: 0.7500) q4:0 Revenue was 4.2M in Q4." in output
    assert "(Score: 0.2500) handbook:3 Travel needs approval." in output


def test_the_default_queries_run_when_none_is_given(monkeypatch, capsys, knowledge_store):
    model, collection = knowledge_store

    run_script(monkeypatch, "--top", "1")

    script = load_script()
    assert model.embedded == [setup.BGE_QUERY_PREFIX + query for query in script.DEFAULT_QUERIES]
    assert {query["n_results"] for query in collection.queries} == {1}
    assert "handbook:3" not in capsys.readouterr().out


def test_ranked_passages_turn_distances_into_scores():
    script = load_script()
    embedded: list[tuple[str, bool]] = []

    def embed(text: str, is_query: bool = False) -> list[float]:
        embedded.append((text, is_query))
        return [1.0, 0.0]

    ranked = script.ranked_passages(QUESTION, RecordingCollection(), embed, top=2)

    assert embedded == [(QUESTION, True)]
    assert ranked == [
        (0.75, "q4:0", "Revenue was 4.2M in Q4."),
        (0.25, "handbook:3", "Travel needs approval."),
    ]
