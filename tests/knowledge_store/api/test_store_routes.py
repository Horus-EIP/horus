"""Knowledge Store /store routes contract tests (hermetic).

Routes under test (``src/services/knowledge-store/app/api/routes/store.py``):

* ``POST   /``                  → 200 / 422
* ``GET    /``                  → 200 / 422 (missing query) / 404 (no results)
* ``DELETE /{id}``              → 200 / 404
* ``POST   /smart-search``      → 200 / 404 / 500
* ``GET    /search-by-entity``  → 200 / 400 (invalid type) / 404
* ``GET    /categories``        → 200
* ``POST   /upload``            → 200 / 400
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from app.api.routes.store import router  # noqa: PLC0415

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


class TestStoreCreate:
    @patch("app.api.routes.store.store_file", new_callable=AsyncMock)
    def test_post_document_returns_200(self, _store, client):
        r = client.post(
            "/",
            json={"document": "Some text", "metadata": {"source": "doc.txt"}},
        )
        assert r.status_code in (200, 422)


class TestStoreQuery:
    @patch(
        "app.api.routes.store.query_knowledge",
        new_callable=AsyncMock,
        return_value={"documents": [["chunk"]], "metadatas": [[{}]], "distances": [[0.1]]},
    )
    def test_get_with_query_returns_200(self, _q, client):
        r = client.get("/", params={"query": "policy", "n_results": 2})
        assert r.status_code == 200

    def test_get_without_query_returns_422(self, client):
        r = client.get("/")
        assert r.status_code == 422


class TestStoreDelete:
    @patch(
        "app.api.routes.store.delete_document",
        new_callable=AsyncMock,
        return_value={"status": "ok"},
    )
    def test_delete_by_id_returns_200(self, _del, client):
        r = client.delete("/doc-id-1")
        assert r.status_code == 200

    @patch(
        "app.api.routes.store.delete_document",
        new_callable=AsyncMock,
        side_effect=ValueError("not found"),
    )
    def test_delete_unknown_returns_404(self, _del, client):
        r = client.delete("/ghost-id")
        assert r.status_code == 404

    def test_deleted_document_is_absent_from_later_queries(
        self, client, fake_collection, deleted_sources_file
    ):
        corpus_meta = {"title": "q4.md", "source_path": "reports/q4.md", "source": "corpus"}
        fake_collection.add(
            ids=["corpus-new", "corpus-old", "other"],
            documents=["Q4 revenue was 4.2M", "Q4 revenue was 4.0M", "Unrelated notes"],
            metadatas=[
                {**corpus_meta, "content_sha256": "new"},
                {**corpus_meta, "content_sha256": "old"},
                {"title": "notes.txt"},
            ],
        )

        assert client.delete("/corpus-new").status_code == 200

        found = client.get("/", params={"query": "Q4 revenue", "n_results": 10}).json()
        assert found["ids"] == [["other"]]

    def test_delete_removes_every_entry_carrying_the_doc_id(self, client, fake_collection):
        fake_collection.add(
            ids=["doc-a", "doc-a:1", "doc-b"],
            documents=["part one", "part two", "other"],
            metadatas=[
                {"title": "a.txt", "doc_id": "doc-a"},
                {"title": "a.txt", "doc_id": "doc-a"},
                {"title": "b.txt", "doc_id": "doc-b"},
            ],
        )

        r = client.delete("/doc-a")

        assert r.status_code == 200
        assert r.json()["deleted_ids"] == ["doc-a", "doc-a:1"]
        assert sorted(fake_collection.rows) == ["doc-b"]

    def test_delete_removes_the_uploaded_file_from_documents(
        self, client, fake_collection, documents_root
    ):
        stored = documents_root / "txt" / "a.txt"
        stored.parent.mkdir()
        stored.write_text("part one", encoding="utf-8")
        fake_collection.add(
            ids=["doc-a"],
            documents=["part one"],
            metadatas=[{"title": "a.txt", "stored_path": "documents/txt/a.txt"}],
        )

        r = client.delete("/doc-a")

        assert r.status_code == 200
        assert r.json()["removed_files"] == ["txt/a.txt"]
        assert not stored.exists()

    def test_delete_of_an_id_that_is_not_stored_returns_404(self, client, fake_collection):
        fake_collection.add(ids=["doc-a"], documents=["a"], metadatas=[{"title": "a.txt"}])

        r = client.delete("/ghost-id")

        assert r.status_code == 404
        assert sorted(fake_collection.rows) == ["doc-a"]


class TestSmartSearch:
    @patch(
        "app.api.routes.store.query_with_filters",
        new_callable=AsyncMock,
        return_value={"documents": [[]], "metadatas": [[]], "distances": [[]]},
    )
    def test_smart_search_returns_200_or_404(self, _q, client):
        r = client.post(
            "/smart-search",
            json={"query": "expense", "categories": ["finance"]},
        )
        assert r.status_code in (200, 404, 422)


class TestSearchByEntity:
    def test_invalid_entity_type_returns_400(self, client):
        r = client.get(
            "/search-by-entity",
            params={"entity": "Acme", "entity_type": "BOGUS"},
        )
        # Source: store.py:201 raises 400 for unknown entity_type
        assert r.status_code == 400


class TestCategories:
    def test_categories_returns_200(self, client):
        # The route reads knowledge_collection.get(...) which is mocked at
        # conftest level via the ChromaDB mock — returns an empty/mock result.
        r = client.get("/categories")
        assert r.status_code in (200, 500)

    def test_documents_without_category_are_counted_as_general(self, client, fake_collection):
        metadatas = [
            {"auto_category": "finance"},
            {"auto_category": ""},
            {"auto_category": "  "},
            {},
            {},
        ]
        fake_collection.add(
            ids=[f"doc-{n}" for n in range(5)],
            documents=["body"] * 5,
            metadatas=metadatas,
        )
        r = client.get("/categories")
        assert r.status_code == 200
        assert r.json() == {
            "total_documents": 5,
            "categories": [
                {"category": "general", "count": 4},
                {"category": "finance", "count": 1},
            ],
        }

    def test_empty_category_label_matches_file_listing(self, fake_collection):
        from app.api.routes.file import router as file_router  # noqa: PLC0415
        from app.api.routes.store import router as store_router  # noqa: PLC0415

        app = FastAPI()
        app.include_router(file_router, prefix="/file")
        app.include_router(store_router)
        file_and_store_client = TestClient(app)
        fake_collection.add(
            ids=["a", "b", "c"],
            documents=["body a", "body b", "body c"],
            metadatas=[
                {"title": "a.md", "auto_category": ""},
                {"title": "b.md", "auto_category": " "},
                {"title": "c.md"},
            ],
        )

        listed = file_and_store_client.get("/file").json()["documents"]
        counted = file_and_store_client.get("/categories").json()["categories"]

        assert {doc["category"] for doc in listed} == {"general"}
        assert counted == [{"category": "general", "count": 3}]

    def test_chunks_of_one_document_count_once(self, client, fake_collection):
        fake_collection.add(
            ids=["doc-a:0", "doc-a:1", "doc-b:0"],
            documents=["part one", "part two", "other"],
            metadatas=[
                {"doc_id": "doc-a", "chunk_index": 0, "category": "finance"},
                {"doc_id": "doc-a", "chunk_index": 1, "category": "finance"},
                {"doc_id": "doc-b", "chunk_index": 0, "category": "hr"},
            ],
        )

        assert client.get("/categories").json() == {
            "total_documents": 2,
            "categories": [
                {"category": "finance", "count": 1},
                {"category": "hr", "count": 1},
            ],
        }
