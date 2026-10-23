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
            store_mod._content_analyzer,
            "analyze",
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
        monkeypatch.setattr(
            store_mod, "query_knowledge", AsyncMock(return_value=_results(["chunk"]))
        )
        r = client.get("/", params={"query": "policy", "n_results": 2})
        assert r.status_code == 200

    def test_query_with_valid_filters(self, client, monkeypatch):
        qwf = AsyncMock(return_value=_results(["c"]))
        monkeypatch.setattr(store_mod, "query_with_filters", qwf)
        r = client.get(
            "/", params={"query": "x", "filters": '{"auto_category": {"$eq": "finance"}}'}
        )
        assert r.status_code == 200
        assert qwf.await_args.args[1] == {"auto_category": {"$eq": "finance"}}

    def test_query_invalid_filters_returns_400(self, client):
        r = client.get("/", params={"query": "x", "filters": "not-json"})
        assert r.status_code == 400

    def test_query_backend_error_returns_500(self, client, monkeypatch):
        monkeypatch.setattr(
            store_mod, "query_knowledge", AsyncMock(side_effect=RuntimeError("boom"))
        )
        r = client.get("/", params={"query": "x"})
        assert r.status_code == 500

    def test_query_no_results_returns_404(self, client, monkeypatch):
        monkeypatch.setattr(
            store_mod, "query_knowledge", AsyncMock(return_value={"documents": [[]]})
        )
        r = client.get("/", params={"query": "x"})
        assert r.status_code == 404


def _add_chunk(collection, doc_id: str, index: int, text: str, **metadata) -> None:
    collection.add(
        ids=[f"{doc_id}:{index}"],
        documents=[text],
        metadatas=[
            {
                "doc_id": doc_id,
                "chunk_index": index,
                "title": f"{doc_id}.md",
                "category": "general",
                **metadata,
            }
        ],
    )


class TestSmartSearchFull:
    def test_no_filters_success(self, client, fake_collection):
        _add_chunk(fake_collection, "doc-a", 0, "a")
        _add_chunk(fake_collection, "doc-b", 0, "b")
        r = client.post("/smart-search", json={"query": "x"})
        assert r.status_code == 200
        assert r.json()["total"] == 2

    def test_each_hit_carries_its_document_id_and_passage_id(self, client, fake_collection):
        _add_chunk(fake_collection, "doc-a", 0, "a", auto_summary="summary of a")
        _add_chunk(fake_collection, "doc-b", 0, "b")
        r = client.post("/smart-search", json={"query": "x"})
        assert r.status_code == 200
        body = r.json()["results"]
        assert body["ids"] == ["doc-a", "doc-b"]
        assert body["chunk_ids"] == ["doc-a:0", "doc-b:0"]
        assert body["documents"] == ["a", "b"]
        assert body["metadatas"][0]["auto_summary"] == "summary of a"

    def test_two_passages_of_one_document_give_one_hit(self, client, fake_collection):
        _add_chunk(fake_collection, "doc-a", 1, "second part of a")
        _add_chunk(fake_collection, "doc-a", 0, "first part of a", auto_summary="all of a")
        _add_chunk(fake_collection, "doc-b", 0, "b")
        r = client.post("/smart-search", json={"query": "x"})
        body = r.json()["results"]
        assert body["ids"] == ["doc-a", "doc-b"]
        assert body["chunk_ids"] == ["doc-a:1", "doc-b:0"]
        assert body["documents"][0] == "second part of a"
        assert body["metadatas"][0]["chunk_index"] == 1
        assert body["metadatas"][0]["auto_summary"] == "all of a"

    def test_n_results_counts_documents(self, client, fake_collection):
        for index in range(3):
            _add_chunk(fake_collection, "doc-a", index, f"a{index}")
        _add_chunk(fake_collection, "doc-b", 0, "b")
        _add_chunk(fake_collection, "doc-c", 0, "c")
        r = client.post("/smart-search", json={"query": "x", "n_results": 2})
        assert r.json()["results"]["ids"] == ["doc-a", "doc-b"]

    def test_with_filters_success(self, client, fake_collection):
        _add_chunk(fake_collection, "doc-a", 0, "a", category="finance")
        _add_chunk(fake_collection, "doc-b", 0, "b", category="hr")
        r = client.post("/smart-search", json={"query": "x", "categories": ["finance"]})
        assert r.status_code == 200
        assert r.json()["filters"] == {"category": {"$eq": "finance"}}
        assert r.json()["results"]["ids"] == ["doc-a"]

    def test_a_document_filter_applies_to_the_document_not_the_passage(
        self, client, fake_collection
    ):
        _add_chunk(fake_collection, "doc-a", 0, "a0", confidence_score=0.9)
        _add_chunk(fake_collection, "doc-a", 1, "a1")
        _add_chunk(fake_collection, "doc-b", 0, "b0", confidence_score=0.2)
        searched = []
        original = fake_collection.query

        def recording_query(**kwargs):
            searched.append(kwargs.get("where"))
            return original(**kwargs)

        fake_collection.query = recording_query
        r = client.post("/smart-search", json={"query": "x", "min_confidence": 0.5})
        assert r.status_code == 200
        assert searched == [{"doc_id": {"$in": ["doc-a"]}}]
        assert r.json()["results"]["ids"] == ["doc-a"]

    def test_no_results_404(self, client, fake_collection):
        r = client.post("/smart-search", json={"query": "x"})
        assert r.status_code == 404

    def test_backend_error_500(self, client, monkeypatch):
        monkeypatch.setattr(
            store_mod, "search_documents", AsyncMock(side_effect=RuntimeError("boom"))
        )
        r = client.post("/smart-search", json={"query": "x"})
        assert r.status_code == 500


class TestSearchByEntityFull:
    def test_success(self, client, fake_collection):
        _add_chunk(fake_collection, "doc-a", 0, "Alice signed it", entities_people='["Alice"]')
        r = client.get("/search-by-entity", params={"entity": "Alice", "entity_type": "people"})
        assert r.status_code == 200
        body = r.json()
        assert body["entity"] == "Alice"
        assert body["filter"] == {"entities_people": {"$contains": "Alice"}}
        assert body["results"]["ids"] == [["doc-a"]]
        assert body["results"]["documents"] == [["Alice signed it"]]

    def test_no_results_404(self, client, fake_collection):
        r = client.get("/search-by-entity", params={"entity": "X", "entity_type": "companies"})
        assert r.status_code == 404

    def test_backend_error_500(self, client, monkeypatch):
        monkeypatch.setattr(
            store_mod, "search_documents", AsyncMock(side_effect=RuntimeError("boom"))
        )
        r = client.get("/search-by-entity", params={"entity": "X", "entity_type": "dates"})
        assert r.status_code == 500


class TestCategoriesFull:
    def test_with_data_sorted_by_count(self, client, fake_collection):
        fake_collection.add(
            ids=["a", "b", "c"],
            documents=["a", "b", "c"],
            metadatas=[
                {"auto_category": "finance"},
                {"auto_category": "finance"},
                {"auto_category": ""},
            ],
        )
        r = client.get("/categories")
        assert r.status_code == 200
        body = r.json()
        assert body["total_documents"] == 3
        assert body["categories"][0] == {"category": "finance", "count": 2}

    def test_empty(self, client, fake_collection):
        r = client.get("/categories")
        assert r.status_code == 200
        assert r.json() == {"total_documents": 0, "categories": []}

    def test_error_500(self, client, monkeypatch):
        monkeypatch.setattr(
            store_mod, "stored_documents", MagicMock(side_effect=RuntimeError("boom"))
        )
        r = client.get("/categories")
        assert r.status_code == 500


class TestUploadAndChunk:
    def test_upload_pdf_success(self, client, monkeypatch):
        monkeypatch.setattr(store_mod, "save_file", AsyncMock(return_value="/tmp/x.pdf"))
        monkeypatch.setattr(store_mod, "pdf_to_text", AsyncMock(return_value="hello world " * 50))
        monkeypatch.setattr(
            store_mod._content_analyzer, "analyze", MagicMock(return_value={"topics": ["t"]})
        )
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
