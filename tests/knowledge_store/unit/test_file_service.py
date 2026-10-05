"""Unit tests for the file_service CRUD/query helpers.

``get_embedding`` and ``knowledge_collection`` are patched per-test so no
real embedding model runs and no real ChromaDB call is made — we assert on
the arguments the service forwards to the collection.
"""

from __future__ import annotations

import pytest

from app.chroma_db.models import DocumentModel
from app.chroma_db.services import deleted_sources, file_service


class TestStoreFile:
    async def test_store_file_minimal_metadata(self, monkeypatch):
        captured: dict = {}
        monkeypatch.setattr(file_service, "get_embeddings", lambda texts: [[0.1, 0.2]] * len(texts))
        monkeypatch.setattr(
            file_service.knowledge_collection, "add", lambda **kw: captured.update(kw)
        )

        await file_service.store_file(
            DocumentModel(id="1", title="t.txt", content="hello", size=5)
        )

        assert captured["ids"] == ["1:0"]
        assert captured["documents"] == ["hello"]
        assert captured["embeddings"] == [[0.1, 0.2]]
        md = captured["metadatas"][0]
        assert md["title"] == "t.txt"
        assert md["size"] == 5
        assert md["doc_id"] == "1"
        assert md["chunk_index"] == 0
        assert (md["char_start"], md["char_end"]) == (0, 5)
        assert md["category"] == "general"
        assert md["source_path"] == ""
        assert md["embed_model"] == file_service.EMBED_MODEL
        assert "page" not in md
        # No auto-analysis → none of the auto_* keys are present.
        assert "auto_category" not in md

    async def test_store_file_with_full_auto_analysis(self, monkeypatch):
        captured: dict = {}
        monkeypatch.setattr(file_service, "get_embeddings", lambda texts: [[0.0]] * len(texts))
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
        monkeypatch.setattr(file_service, "get_embeddings", lambda texts: [[0.0]] * len(texts))
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

    async def test_delete_document(self, fake_collection):
        fake_collection.add(ids=["doc-1"], documents=["d"], metadatas=[{"title": "t"}])

        out = await file_service.delete_document("doc-1")

        assert out == {"deleted_ids": ["doc-1"], "removed_files": []}
        assert fake_collection.rows == {}


def _upload(collection, doc_id: str, title: str, **metadata) -> None:
    collection.add(ids=[doc_id], documents=["body"], metadatas=[{"title": title, **metadata}])


def _stored_file(documents_root, relative: str):
    path = documents_root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("body", encoding="utf-8")
    return path


class TestDeleteDocument:
    async def test_an_unknown_id_raises_not_found(self, fake_collection):
        _upload(fake_collection, "doc-a", "a.txt")

        with pytest.raises(file_service.DocumentNotFoundError):
            await file_service.delete_document("ghost")

        assert list(fake_collection.rows) == ["doc-a"]

    async def test_a_file_another_entry_still_uses_is_kept_until_the_last_one_goes(
        self, fake_collection, documents_root
    ):
        stored = _stored_file(documents_root, "txt/a.txt")
        _upload(fake_collection, "doc-1", "a.txt", stored_path="documents/txt/a.txt")
        _upload(fake_collection, "doc-2", "a.txt", stored_path="documents/txt/a.txt")

        first = await file_service.delete_document("doc-1")
        assert first["removed_files"] == []
        assert stored.exists()

        second = await file_service.delete_document("doc-2")
        assert second["removed_files"] == ["txt/a.txt"]
        assert not stored.exists()

    async def test_an_upload_from_before_stored_path_is_found_by_its_title(
        self, fake_collection, documents_root
    ):
        stored = _stored_file(documents_root, "pdf/Report.PDF")
        _upload(fake_collection, "doc-1", "Report.PDF")

        out = await file_service.delete_document("doc-1")

        assert out["removed_files"] == ["pdf/Report.PDF"]
        assert not stored.exists()

    async def test_a_stored_path_outside_documents_is_never_removed(
        self, fake_collection, documents_root, tmp_path
    ):
        outside = tmp_path / "outside.txt"
        outside.write_text("keep me", encoding="utf-8")
        _upload(fake_collection, "doc-1", "outside.txt", stored_path="documents/../outside.txt")

        out = await file_service.delete_document("doc-1")

        assert out["removed_files"] == []
        assert outside.exists()

    async def test_a_corpus_entry_leaves_the_documents_folder_alone(
        self, fake_collection, documents_root, deleted_sources_file
    ):
        unrelated = _stored_file(documents_root, "md/q4.md")
        _upload(
            fake_collection, "corpus-aaa", "q4.md",
            source_path="reports/q4.md", content_sha256="aaa", source="corpus",
        )

        out = await file_service.delete_document("corpus-aaa")

        assert out == {"deleted_ids": ["corpus-aaa"], "removed_files": []}
        assert unrelated.exists()

    async def test_a_corpus_entry_is_remembered_as_deleted(
        self, fake_collection, deleted_sources_file
    ):
        _upload(
            fake_collection, "corpus-aaa", "q4.md",
            source_path="reports/q4.md", content_sha256="aaa", source="corpus",
        )

        await file_service.delete_document("corpus-aaa")

        assert deleted_sources.was_deleted("reports/q4.md", "aaa")

    async def test_an_upload_is_not_put_on_the_deleted_list(
        self, fake_collection, documents_root, deleted_sources_file
    ):
        _upload(fake_collection, "doc-1", "a.txt", stored_path="documents/txt/a.txt")

        await file_service.delete_document("doc-1")

        assert not deleted_sources_file.exists()
