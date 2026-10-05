"""Coverage-focused contract tests for store.py route handlers.

Complements test_store_routes.py with the success paths and every error
branch (400 / 404 / 500), driving the handlers end-to-end with mocked
service-layer functions.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes import store as store_mod


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(store_mod.router)
    return TestClient(app)


def _results(docs: list[str]) -> dict:
    n = len(docs)
    return {
        "documents": [docs],
        "metadatas": [[{"title": f"t{i}"} for i in range(n)]],
        "distances": [[0.1 * (i + 1) for i in range(n)]],
    }


class TestAddText:
    def test_add_text_success(self, client, monkeypatch):
        monkeypatch.setattr(
            store_mod._content_analyzer, "analyze",
            MagicMock(return_value={"auto_category": "general"}),
        )
        monkeypatch.setattr(store_mod, "store_file", AsyncMock())
        r = client.post("/", json={"id": "1", "title": "t", "content": "hello", "size": 5})
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "document added"
        assert body["id"] == "1"
        assert body["auto_analysis"] == {"auto_category": "general"}


class TestQuery:
    def test_query_no_filters_success(self, client, monkeypatch):
        monkeypatch.setattr(store_mod, "query_knowledge", AsyncMock(return_value=_results(["chunk"])))
        r = client.get("/", params={"query": "policy", "n_results": 2})
        assert r.status_code == 200

    def test_query_with_valid_filters(self, client, monkeypatch):
        qwf = AsyncMock(return_value=_results(["c"]))
        monkeypatch.setattr(store_mod, "query_with_filters", qwf)
        r = client.get("/", params={"query": "x", "filters": '{"auto_category": {"$eq": "finance"}}'})
        assert r.status_code == 200
        assert qwf.await_args.args[1] == {"auto_category": {"$eq": "finance"}}

    def test_query_invalid_filters_returns_400(self, client):
        r = client.get("/", params={"query": "x", "filters": "not-json"})
        assert r.status_code == 400

    def test_query_backend_error_returns_500(self, client, monkeypatch):
        monkeypatch.setattr(store_mod, "query_knowledge", AsyncMock(side_effect=RuntimeError("boom")))
        r = client.get("/", params={"query": "x"})
        assert r.status_code == 500

    def test_query_no_results_returns_404(self, client, monkeypatch):
        monkeypatch.setattr(store_mod, "query_knowledge", AsyncMock(return_value={"documents": [[]]}))
        r = client.get("/", params={"query": "x"})
        assert r.status_code == 404


class TestSmartSearchFull:
    def test_no_filters_success(self, client, monkeypatch):
        monkeypatch.setattr(store_mod, "query_knowledge", AsyncMock(return_value=_results(["a", "b"])))
        r = client.post("/smart-search", json={"query": "x"})
        assert r.status_code == 200
        assert r.json()["total"] == 2

    def test_each_hit_carries_its_document_id(self, client, monkeypatch):
        results = {**_results(["a", "b"]), "ids": [["doc-a", "doc-b"]]}
        monkeypatch.setattr(store_mod, "query_knowledge", AsyncMock(return_value=results))
        r = client.post("/smart-search", json={"query": "x"})
        assert r.status_code == 200
        body = r.json()["results"]
        assert body["ids"] == ["doc-a", "doc-b"]
        assert body["documents"] == ["a", "b"]

    def test_hits_without_ids_are_still_returned(self, client, monkeypatch):
        monkeypatch.setattr(store_mod, "query_knowledge", AsyncMock(return_value=_results(["a"])))
        r = client.post("/smart-search", json={"query": "x"})
        assert r.status_code == 200
        body = r.json()["results"]
        assert body["ids"] == []
        assert body["documents"] == ["a"]

    def test_with_filters_success(self, client, monkeypatch):
        monkeypatch.setattr(store_mod, "query_with_filters", AsyncMock(return_value=_results(["a"])))
        r = client.post("/smart-search", json={"query": "x", "categories": ["finance"]})
        assert r.status_code == 200
        assert r.json()["filters"] is not None

    def test_no_results_404(self, client, monkeypatch):
        monkeypatch.setattr(
            store_mod, "query_knowledge",
            AsyncMock(return_value={"documents": [[]], "metadatas": [[]], "distances": [[]]}),
        )
        r = client.post("/smart-search", json={"query": "x"})
        assert r.status_code == 404

    def test_backend_error_500(self, client, monkeypatch):
        monkeypatch.setattr(store_mod, "query_knowledge", AsyncMock(side_effect=RuntimeError("boom")))
        r = client.post("/smart-search", json={"query": "x"})
        assert r.status_code == 500

    def test_documents_without_parallel_arrays_404(self, client, monkeypatch):
        # documents present but metadatas/distances empty → zip yields nothing,
        # exercising the "No results found within distance threshold" branch.
        monkeypatch.setattr(
            store_mod, "query_knowledge",
            AsyncMock(return_value={"documents": [["a"]], "metadatas": [[]], "distances": [[]]}),
        )
        r = client.post("/smart-search", json={"query": "x"})
        assert r.status_code == 404


class TestSearchByEntityFull:
    def test_success(self, client, monkeypatch):
        monkeypatch.setattr(store_mod, "query_with_filters", AsyncMock(return_value=_results(["a"])))
        r = client.get("/search-by-entity", params={"entity": "Alice", "entity_type": "people"})
        assert r.status_code == 200
        assert r.json()["entity"] == "Alice"

    def test_no_results_404(self, client, monkeypatch):
        monkeypatch.setattr(store_mod, "query_with_filters", AsyncMock(return_value={"documents": [[]]}))
        r = client.get("/search-by-entity", params={"entity": "X", "entity_type": "companies"})
        assert r.status_code == 404

    def test_backend_error_500(self, client, monkeypatch):
        monkeypatch.setattr(store_mod, "query_with_filters", AsyncMock(side_effect=RuntimeError("boom")))
        r = client.get("/search-by-entity", params={"entity": "X", "entity_type": "dates"})
        assert r.status_code == 500


class TestCategoriesFull:
    def test_with_data_sorted_by_count(self, client, monkeypatch):
        getter = MagicMock(return_value={"metadatas": [
            {"auto_category": "finance"}, {"auto_category": "finance"}, {"auto_category": ""},
        ]})
        monkeypatch.setattr(store_mod.knowledge_collection, "get", getter)
        r = client.get("/categories")
        assert r.status_code == 200
        body = r.json()
        assert body["total_documents"] == 3
        assert body["categories"][0] == {"category": "finance", "count": 2}

    def test_empty(self, client, monkeypatch):
        monkeypatch.setattr(store_mod.knowledge_collection, "get", MagicMock(return_value={"metadatas": []}))
        r = client.get("/categories")
        assert r.status_code == 200
        assert r.json() == {"total_documents": 0, "categories": []}

    def test_error_500(self, client, monkeypatch):
        monkeypatch.setattr(store_mod.knowledge_collection, "get", MagicMock(side_effect=RuntimeError("boom")))
        r = client.get("/categories")
        assert r.status_code == 500


class TestUploadAndChunk:
    def test_upload_pdf_success(self, client, monkeypatch):
        monkeypatch.setattr(store_mod, "save_file", AsyncMock(return_value="/tmp/x.pdf"))
        monkeypatch.setattr(store_mod, "pdf_to_text", AsyncMock(return_value="hello world " * 50))
        monkeypatch.setattr(store_mod._content_analyzer, "analyze", MagicMock(return_value={"topics": ["t"]}))
        r = client.post("/upload", files={"file": ("x.pdf", b"%PDF", "application/pdf")})
        assert r.status_code == 200
        body = r.json()
        assert body["filename"] == "x.pdf"
        assert body["total_chunks"] == len(body["chunks"])

    def test_upload_error_returns_400(self, client, monkeypatch):
        monkeypatch.setattr(store_mod, "save_file", AsyncMock(side_effect=OSError("disk full")))
        r = client.post("/upload", files={"file": ("x.pdf", b"%PDF", "application/pdf")})
        assert r.status_code == 400

    def test_upload_docx_branch(self, client, monkeypatch):
        monkeypatch.setattr(store_mod, "save_file", AsyncMock(return_value="/tmp/x.docx"))
        monkeypatch.setattr(store_mod, "docx_to_text", AsyncMock(return_value="hello world " * 50))
        monkeypatch.setattr(store_mod._content_analyzer, "analyze", MagicMock(return_value={}))
        r = client.post("/upload", files={"file": ("x.docx", b"PK", "application/octet-stream")})
        assert r.status_code == 200

    def test_upload_txt_branch(self, client, monkeypatch, tmp_path):
        p = tmp_path / "x.txt"
        p.write_text("hello world " * 50)
        monkeypatch.setattr(store_mod, "save_file", AsyncMock(return_value=str(p)))
        monkeypatch.setattr(store_mod._content_analyzer, "analyze", MagicMock(return_value={}))
        r = client.post("/upload", files={"file": ("x.txt", b"hello", "text/plain")})
        assert r.status_code == 200

    def test_upload_unknown_extension_branch(self, client, monkeypatch, tmp_path):
        p = tmp_path / "x.bin"
        p.write_text("hello world " * 50)
        monkeypatch.setattr(store_mod, "save_file", AsyncMock(return_value=str(p)))
        monkeypatch.setattr(store_mod._content_analyzer, "analyze", MagicMock(return_value={}))
        r = client.post("/upload", files={"file": ("x.bin", b"x", "application/octet-stream")})
        assert r.status_code == 200
