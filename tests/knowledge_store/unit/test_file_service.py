"""Unit tests for the file_service CRUD/query helpers.

``get_embedding`` and ``knowledge_collection`` are patched per-test so no
real embedding model runs and no real ChromaDB call is made — we assert on
the arguments the service forwards to the collection.
"""

from __future__ import annotations

from app.chroma_db.models import DocumentModel
from app.chroma_db.services import file_service


class TestStoreFile:
    async def test_store_file_minimal_metadata(self, monkeypatch):
        captured: dict = {}
        monkeypatch.setattr(file_service, "get_embedding", lambda *a, **k: [0.1, 0.2])
        monkeypatch.setattr(
            file_service.knowledge_collection, "add", lambda **kw: captured.update(kw)
        )

        await file_service.store_file(
            DocumentModel(id="1", title="t.txt", content="hello", size=5)
        )

        assert captured["ids"] == ["1"]
        assert captured["documents"] == ["hello"]
        assert captured["embeddings"] == [[0.1, 0.2]]
        md = captured["metadatas"][0]
        assert md["title"] == "t.txt"
        assert md["size"] == 5
        # No auto-analysis → none of the auto_* keys are present.
        assert "auto_category" not in md

    async def test_store_file_with_full_auto_analysis(self, monkeypatch):
        captured: dict = {}
        monkeypatch.setattr(file_service, "get_embedding", lambda *a, **k: [0.0])
        monkeypatch.setattr(
            file_service.knowledge_collection, "add", lambda **kw: captured.update(kw)
        )

        analysis = {
            "auto_category": "finance",
            "auto_type": "report",
            "auto_summary": "a summary",
            "confidence_score": 0.9,
            "entities": {
                "people": ["Alice"],
                "companies": ["Acme"],
                "amounts": ["$5"],
                "dates": ["2020"],
            },
            "topics": ["earnings"],
        }
        await file_service.store_file(
            DocumentModel(id="2", title="a", content="c", size=1),
            auto_analysis=analysis,
        )

        md = captured["metadatas"][0]
        assert md["auto_category"] == "finance"
        assert md["auto_type"] == "report"
        assert md["confidence_score"] == 0.9
        assert md["entities_people"] == '["Alice"]'
        assert md["entities_companies"] == '["Acme"]'
        assert md["entities_amounts"] == '["$5"]'
        assert md["entities_dates"] == '["2020"]'

    async def test_store_file_auto_analysis_without_entities(self, monkeypatch):
        captured: dict = {}
        monkeypatch.setattr(file_service, "get_embedding", lambda *a, **k: [0.0])
        monkeypatch.setattr(
            file_service.knowledge_collection, "add", lambda **kw: captured.update(kw)
        )

        # entities dict empty → entity_* keys are skipped but base auto_* set.
        await file_service.store_file(
            DocumentModel(id="3", title="b", content="d", size=2),
            auto_analysis={"auto_category": "general", "entities": {}},
        )
        md = captured["metadatas"][0]
        assert md["auto_category"] == "general"
        assert "entities_people" not in md


class TestQueriesAndDelete:
    async def test_query_knowledge_forwards_n_results(self, monkeypatch):
        monkeypatch.setattr(file_service, "get_embedding", lambda *a, **k: [0.0])
        monkeypatch.setattr(
            file_service.knowledge_collection, "query", lambda **kw: {"_kw": kw}
        )
        out = await file_service.query_knowledge("q", 3)
        assert out["_kw"]["n_results"] == 3
        assert out["_kw"]["query_embeddings"] == [[0.0]]

    async def test_query_with_filters_passes_where_clause(self, monkeypatch):
        monkeypatch.setattr(file_service, "get_embedding", lambda *a, **k: [0.0])
        monkeypatch.setattr(
            file_service.knowledge_collection, "query", lambda **kw: {"_kw": kw}
        )
        where = {"auto_category": {"$eq": "finance"}}
        out = await file_service.query_with_filters("q", where, 2)
        assert out["_kw"]["where"] == where
        assert out["_kw"]["n_results"] == 2

    async def test_delete_document(self, monkeypatch):
        calls: dict = {}
        monkeypatch.setattr(
            file_service.knowledge_collection, "delete", lambda **kw: calls.update(kw)
        )
        out = await file_service.delete_document("doc-1")
        assert out == {"status": "document deleted"}
        assert calls["ids"] == ["doc-1"]
