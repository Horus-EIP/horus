from __future__ import annotations

import pytest

from app.chroma_db.models import DocumentModel
from app.chroma_db.services import file_service

LONG_TEXT = " ".join(f"Sentence {n} talks about the quarterly plan in detail." for n in range(120))


@pytest.fixture
def embedded(monkeypatch):
    calls: list[list[str]] = []

    def embed(texts):
        calls.append(list(texts))
        return [[float(len(text))] for text in texts]

    monkeypatch.setattr(file_service, "get_embeddings", embed)
    return calls


async def _store(text: str = LONG_TEXT, doc_id: str = "doc-1", **kwargs) -> int:
    return await file_service.store_file(
        DocumentModel(id=doc_id, title="plan.txt", content=text, size=len(text)), **kwargs
    )


def _chunks(collection, doc_id: str = "doc-1") -> list[tuple[str, str, dict]]:
    rows = [
        (entry_id, text, metadata) for entry_id, (text, metadata) in collection.rows.items()
        if metadata.get("doc_id") == doc_id
    ]
    return sorted(rows, key=lambda row: row[2]["chunk_index"])


class TestStoreChunks:
    async def test_a_long_document_is_stored_as_numbered_chunks(self, fake_collection, embedded):
        count = await _store()

        chunks = _chunks(fake_collection)
        assert count == len(chunks) > 1
        assert [entry_id for entry_id, _text, _meta in chunks] == [
            f"doc-1:{n}" for n in range(count)
        ]
        assert all(
            LONG_TEXT[meta["char_start"]:meta["char_end"]] == text for _id, text, meta in chunks
        )

    async def test_the_head_chunk_is_written_last(self, fake_collection, embedded, monkeypatch):
        monkeypatch.setattr(file_service, "WRITE_BATCH_SIZE", 2)
        written: list[str] = []
        add = fake_collection.add

        def recording_add(**kwargs):
            written.extend(kwargs["ids"])
            add(**kwargs)

        monkeypatch.setattr(fake_collection, "add", recording_add)

        await _store()

        assert written[-1] == "doc-1:0"
        assert sorted(written) == sorted(fake_collection.rows)

    async def test_chunks_are_embedded_in_batches(self, fake_collection, embedded, monkeypatch):
        monkeypatch.setattr(file_service, "WRITE_BATCH_SIZE", 3)

        count = await _store()

        assert sum(len(batch) for batch in embedded) == count
        assert max(len(batch) for batch in embedded) == 3

    async def test_a_failed_write_leaves_no_partial_document(
        self, fake_collection, embedded, monkeypatch
    ):
        monkeypatch.setattr(file_service, "WRITE_BATCH_SIZE", 2)
        add = fake_collection.add
        batches = {"seen": 0}

        def failing_add(**kwargs):
            batches["seen"] += 1
            if batches["seen"] == 3:
                raise RuntimeError("disk full")
            add(**kwargs)

        monkeypatch.setattr(fake_collection, "add", failing_add)

        with pytest.raises(RuntimeError):
            await _store()

        assert fake_collection.rows == {}

    async def test_storing_a_document_id_again_replaces_its_chunks(self, fake_collection, embedded):
        await _store()

        await _store("A much shorter replacement.")

        assert [text for _id, text, _meta in _chunks(fake_collection)] == [
            "A much shorter replacement."
        ]

    async def test_an_empty_document_is_still_stored_once(self, fake_collection, embedded):
        assert await _store("") == 1

        assert [(entry_id, text) for entry_id, text, _ in _chunks(fake_collection)] == [
            ("doc-1:0", "")
        ]

    async def test_pages_are_recorded_when_the_page_starts_are_known(
        self, fake_collection, embedded
    ):
        half = len(LONG_TEXT) // 2

        await _store(page_starts=(0, half))

        pages = {meta["chunk_index"]: meta["page"] for _id, _text, meta in _chunks(fake_collection)}
        assert pages[0] == 1
        assert pages[max(pages)] == 2

    async def test_source_and_stored_paths_go_on_every_chunk(self, fake_collection, embedded):
        await _store(extra_metadata={
            "source_path": "reports/plan.txt", "content_sha256": "abc", "source": "corpus",
        })

        chunks = _chunks(fake_collection)
        assert all(meta["source_path"] == "reports/plan.txt" for _id, _text, meta in chunks)
        assert chunks[0][2]["content_sha256"] == "abc"
        assert all("content_sha256" not in meta for _id, _text, meta in chunks[1:])


class TestDocumentTexts:
    async def test_the_full_text_is_rebuilt_from_overlapping_chunks(self, fake_collection, embedded):
        await _store()

        rebuilt = file_service.document_texts(["doc-1"])["doc-1"]

        assert rebuilt.text == LONG_TEXT
        assert rebuilt.chunk_count == len(_chunks(fake_collection))

    def test_a_gap_between_chunks_is_kept_as_a_line_break(self, fake_collection):
        fake_collection.add(
            ids=["d:0", "d:1"],
            documents=["first", "second"],
            metadatas=[
                {"doc_id": "d", "chunk_index": 0, "char_start": 0, "char_end": 5, "title": "d"},
                {"doc_id": "d", "chunk_index": 1, "char_start": 7, "char_end": 13, "title": "d"},
            ],
        )

        assert file_service.document_texts(["d"])["d"].text == "first\nsecond"

    def test_a_whole_file_entry_from_before_chunking_is_its_own_text(self, fake_collection):
        fake_collection.add(ids=["old"], documents=["whole body"], metadatas=[{"title": "o.md"}])

        found = file_service.document_texts(["old"])["old"]

        assert (found.title, found.text, found.chunk_count) == ("o.md", "whole body", 1)

    def test_unknown_documents_are_left_out(self, fake_collection):
        assert file_service.document_texts(["ghost"]) == {}
