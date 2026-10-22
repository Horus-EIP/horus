from __future__ import annotations

from unittest.mock import MagicMock

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from prometheus_client import REGISTRY

from app.chroma_db import setup
from app.chroma_db.models import DocumentModel
from app.chroma_db.services import file_service

QUERIES = "knowledge_store_queries_total"
QUERY_LATENCY_COUNT = "knowledge_store_query_duration_seconds_count"
QUERY_RESULTS_SUM = "knowledge_store_query_results_count_sum"
EMBEDDINGS = "knowledge_store_embeddings_total"
EMBEDDING_LATENCY_COUNT = "knowledge_store_embedding_duration_seconds_count"

SUCCESS = {"status": "success"}
ERROR = {"status": "error"}

WATCHED = (
    (QUERIES, SUCCESS),
    (QUERIES, ERROR),
    (QUERY_LATENCY_COUNT, {}),
    (QUERY_RESULTS_SUM, {}),
    (EMBEDDINGS, SUCCESS),
    (EMBEDDINGS, ERROR),
    (EMBEDDING_LATENCY_COUNT, {}),
)


def _key(name: str, labels: dict) -> str:
    return name + "".join(f"{{{key}={value}}}" for key, value in labels.items())


class Recorded:
    def __init__(self):
        self.before = self._read()

    @staticmethod
    def _read() -> dict[str, float]:
        return {
            _key(name, labels): REGISTRY.get_sample_value(name, labels) or 0.0
            for name, labels in WATCHED
        }

    def since(self, name: str, labels: dict | None = None) -> float:
        key = _key(name, labels or {})
        return self._read()[key] - self.before[key]


VECTOR = [0.1, 0.2, 0.3]


def _embedded(texts):
    return [np.array(VECTOR) for _ in texts]


@pytest.fixture
def embedder(monkeypatch):
    model = MagicMock()
    model.embed.side_effect = _embedded
    monkeypatch.setattr(setup, "model", model)
    return model


@pytest.fixture
def client(fake_collection, embedder):
    from app.api.routes.store import router  # noqa: PLC0415

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


@pytest.fixture
def stored(fake_collection):
    fake_collection.add(
        ids=["q4", "budget", "policy"],
        documents=["Q4 revenue was 4.2M", "The 2026 budget", "Expense policy"],
        metadatas=[
            {"doc_id": "q4", "title": "q4.md", "category": "finance"},
            {"doc_id": "budget", "title": "budget.md", "category": "finance"},
            {"doc_id": "policy", "title": "policy.md", "category": "hr"},
        ],
    )
    return fake_collection


class TestQueryLatency:
    def test_a_query_records_its_latency_and_how_many_documents_it_returned(self, client, stored):
        recorded = Recorded()

        response = client.get("/", params={"query": "revenue", "n_results": 2})

        assert response.status_code == 200
        assert recorded.since(QUERIES, SUCCESS) == 1
        assert recorded.since(QUERY_LATENCY_COUNT) == 1
        assert recorded.since(QUERY_RESULTS_SUM) == 2

    @pytest.mark.parametrize(
        "search",
        [
            {"query": "revenue", "n_results": 3},
            {"query": "revenue", "n_results": 3, "categories": ["finance"]},
        ],
        ids=["without filters", "with a category filter"],
    )
    def test_a_smart_search_records_its_latency(self, client, stored, search):
        recorded = Recorded()

        response = client.post("/smart-search", json=search)

        assert response.status_code == 200
        assert recorded.since(QUERIES, SUCCESS) == 1
        assert recorded.since(QUERY_LATENCY_COUNT) == 1
        assert recorded.since(QUERY_RESULTS_SUM) == response.json()["total"]

    def test_a_query_that_finds_nothing_is_still_timed(self, client, fake_collection):
        recorded = Recorded()

        response = client.get("/", params={"query": "revenue"})

        assert response.status_code == 404
        assert recorded.since(QUERIES, SUCCESS) == 1
        assert recorded.since(QUERY_LATENCY_COUNT) == 1
        assert recorded.since(QUERY_RESULTS_SUM) == 0

    def test_a_failed_query_is_recorded_as_an_error(self, client, stored, monkeypatch):
        monkeypatch.setattr(stored, "query", MagicMock(side_effect=RuntimeError("chroma down")))
        recorded = Recorded()

        response = client.get("/", params={"query": "revenue"})

        assert response.status_code == 500
        assert recorded.since(QUERIES, ERROR) == 1
        assert recorded.since(QUERIES, SUCCESS) == 0
        assert recorded.since(QUERY_LATENCY_COUNT) == 1

    async def test_the_query_helpers_still_return_the_collection_results(self, stored, embedder):
        results = await file_service.query_with_filters("revenue", {"category": {"$eq": "hr"}}, 5)

        assert results["ids"] == [["policy"]]


class TestEmbeddingLatency:
    def test_a_query_times_the_embedding_of_its_question(self, client, stored, embedder):
        recorded = Recorded()

        client.get("/", params={"query": "revenue"})

        assert recorded.since(EMBEDDINGS, SUCCESS) == 1
        assert recorded.since(EMBEDDING_LATENCY_COUNT) == 1
        embedder.embed.assert_called_once_with([setup.BGE_QUERY_PREFIX + "revenue"])

    async def test_storing_a_document_times_its_embedding(self, fake_collection, embedder):
        recorded = Recorded()

        await file_service.store_file(
            DocumentModel(id="notes", title="notes.txt", content="Q4 planning", size=11)
        )

        assert recorded.since(EMBEDDINGS, SUCCESS) == 1
        assert recorded.since(EMBEDDING_LATENCY_COUNT) == 1
        assert [metadata["doc_id"] for _, metadata in fake_collection.rows.values()] == ["notes"]

    def test_a_failed_embedding_is_recorded_as_an_error_and_raised(self, embedder):
        embedder.embed.side_effect = RuntimeError("model unavailable")
        recorded = Recorded()

        with pytest.raises(RuntimeError, match="model unavailable"):
            setup.get_embedding("revenue", is_query=True)

        assert recorded.since(EMBEDDINGS, ERROR) == 1
        assert recorded.since(EMBEDDINGS, SUCCESS) == 0
        assert recorded.since(EMBEDDING_LATENCY_COUNT) == 1

    def test_the_embedding_is_returned_unchanged(self, embedder):
        assert setup.get_embedding("revenue") == [0.1, 0.2, 0.3]


class TestScrapedByPrometheus:
    def test_the_metrics_endpoint_exposes_the_query_and_embedding_latency(
        self, fake_collection, embedder
    ):
        from app.main import app  # noqa: PLC0415

        with TestClient(app) as service:
            service.get("/", params={"query": "revenue"})
            exposition = service.get("/metrics/").text

        for histogram in (
            "knowledge_store_query_duration_seconds",
            "knowledge_store_embedding_duration_seconds",
        ):
            count = next(
                line for line in exposition.splitlines() if line.startswith(f"{histogram}_count ")
            )
            assert float(count.split()[1]) >= 1, count
