from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.chroma_db.services import file_service

KEYWORDS = ("parking", "lunch", "meeting", "laptop", "holiday")
MODEL_READS_CHARS = 2000
CHUNK_METADATA_KEYS = {
    "doc_id",
    "title",
    "source_path",
    "chunk_index",
    "char_start",
    "char_end",
    "category",
    "embed_model",
}

HANDBOOK_TITLE = "Employee_Handbook.txt"
HANDBOOK = (
    "\n".join(
        f"Section {n}. New starters read the welcome pack and sign the onboarding checklist."
        for n in range(1, 60)
    )
    + "\nParking. Every employee gets a parking permit for the parking garage on level two."
)

MEMO_TITLE = "Team_Memo.txt"
MEMO = (
    "Team memo. Lunch is served after the Monday meeting. Bring your laptop. "
    "Parking is limited near the office."
)


def keyword_vector(text: str) -> list[float]:
    read = text[:MODEL_READS_CHARS].lower()
    return [float(read.count(keyword)) for keyword in KEYWORDS]


@pytest.fixture
def client(monkeypatch, fake_collection):
    from app.main import app  # noqa: PLC0415

    monkeypatch.setattr(
        file_service, "get_embedding", lambda text, is_query=False: keyword_vector(text)
    )
    monkeypatch.setattr(
        file_service,
        "get_embeddings",
        lambda texts: [keyword_vector(text) for text in texts],
        raising=False,
    )
    with TestClient(app) as test_client:
        yield test_client


def _upload(client: TestClient, title: str, body: str) -> str:
    response = client.post("/file", files=[("files", (title, body.encode(), "text/plain"))])
    assert response.status_code == 200
    return response.json()[0]["doc_id"]


def _ask(client: TestClient, question: str, n_results: int = 3) -> dict:
    response = client.get("/", params={"query": question, "n_results": n_results})
    assert response.status_code == 200
    return response.json()


class TestPassageRetrieval:
    def test_a_question_about_the_end_of_a_long_document_finds_it(self, client):
        handbook_id = _upload(client, HANDBOOK_TITLE, HANDBOOK)
        _upload(client, MEMO_TITLE, MEMO)

        found = _ask(client, "Where do I get a parking permit?")

        top_id = found["ids"][0][0]
        top_metadata = found["metadatas"][0][0]
        top_text = found["documents"][0][0]
        assert top_metadata["doc_id"] == handbook_id
        assert top_metadata["title"] == HANDBOOK_TITLE
        assert top_metadata["chunk_index"] > 0
        assert top_id == f"{handbook_id}:{top_metadata['chunk_index']}"
        assert "parking permit" in top_text
        assert HANDBOOK[top_metadata["char_start"] : top_metadata["char_end"]] == top_text

    def test_every_retrieved_passage_has_a_chunk_id_and_its_metadata(self, client):
        _upload(client, HANDBOOK_TITLE, HANDBOOK)
        _upload(client, MEMO_TITLE, MEMO)

        found = _ask(client, "parking lunch meeting", n_results=50)

        assert len(found["ids"][0]) > 2
        for chunk_id, metadata in zip(found["ids"][0], found["metadatas"][0], strict=True):
            assert CHUNK_METADATA_KEYS <= set(metadata)
            assert chunk_id == f"{metadata['doc_id']}:{metadata['chunk_index']}"

    def test_chunks_are_at_most_a_thousand_characters(self, client):
        _upload(client, HANDBOOK_TITLE, HANDBOOK)

        found = _ask(client, "parking", n_results=50)

        assert len(found["ids"][0]) >= 5
        assert all(len(text) <= 1000 for text in found["documents"][0])


class TestDocumentLevelRoutes:
    def test_the_file_listing_shows_one_entry_per_document(self, client):
        handbook_id = _upload(client, HANDBOOK_TITLE, HANDBOOK)
        memo_id = _upload(client, MEMO_TITLE, MEMO)

        listed = client.get("/file").json()["documents"]

        assert sorted(doc["id"] for doc in listed) == sorted([handbook_id, memo_id])
        handbook = next(doc for doc in listed if doc["id"] == handbook_id)
        assert handbook["excerpt"].startswith("Section 1. New starters")
        assert handbook["size"] == len(HANDBOOK.encode())

    def test_categories_count_documents_not_chunks(self, client):
        _upload(client, HANDBOOK_TITLE, HANDBOOK)
        _upload(client, MEMO_TITLE, MEMO)

        counted = client.get("/categories").json()

        assert counted["total_documents"] == 2
        assert sum(entry["count"] for entry in counted["categories"]) == 2

    def test_smart_search_returns_each_document_once_with_its_id(self, client):
        handbook_id = _upload(client, HANDBOOK_TITLE, HANDBOOK)
        memo_id = _upload(client, MEMO_TITLE, MEMO)

        response = client.post("/smart-search", json={"query": "parking", "n_results": 10})

        assert response.status_code == 200
        results = response.json()["results"]
        assert results["ids"] == [handbook_id, memo_id]
        assert "parking permit" in results["documents"][0]
        assert results["chunk_ids"][0].startswith(f"{handbook_id}:")
        assert response.json()["total"] == 2

    def test_a_delete_removes_every_chunk_of_the_document(self, client, fake_collection):
        handbook_id = _upload(client, HANDBOOK_TITLE, HANDBOOK)
        memo_id = _upload(client, MEMO_TITLE, MEMO)

        assert client.delete(f"/{handbook_id}").status_code == 200

        assert {metadata["doc_id"] for _text, metadata in fake_collection.rows.values()} == {
            memo_id
        }
        assert [doc["id"] for doc in client.get("/file").json()["documents"]] == [memo_id]

    def test_the_full_text_of_a_document_is_served_by_its_id(self, client):
        handbook_id = _upload(client, HANDBOOK_TITLE, HANDBOOK)

        response = client.get(f"/file/{handbook_id}/text")

        assert response.status_code == 200
        body = response.json()
        assert body["doc_id"] == handbook_id
        assert body["title"] == HANDBOOK_TITLE
        assert body["text"] == HANDBOOK
        assert body["chunk_count"] > 1

    def test_the_full_text_of_an_unknown_document_is_404(self, client):
        assert client.get("/file/not-stored/text").status_code == 404

    def test_resolve_by_filename_returns_the_whole_document_once(self, client):
        handbook_id = _upload(client, HANDBOOK_TITLE, HANDBOOK)

        body = client.get("/file/resolve", params={"name": HANDBOOK_TITLE}).json()

        assert body["doc_ids"] == [handbook_id]
        assert body["matched_titles"] == [HANDBOOK_TITLE]
        assert body["text"] == HANDBOOK

    def test_resolve_by_filename_keeps_each_matched_document_apart(self, client):
        first_id = _upload(client, HANDBOOK_TITLE, HANDBOOK)
        second_id = _upload(client, HANDBOOK_TITLE, "Second copy of the handbook.")

        body = client.get("/file/resolve", params={"name": HANDBOOK_TITLE}).json()

        assert sorted(document["doc_id"] for document in body["documents"]) == sorted(
            [first_id, second_id]
        )
        texts = {document["doc_id"]: document["text"] for document in body["documents"]}
        assert texts[first_id] == HANDBOOK
        assert texts[second_id] == "Second copy of the handbook."
        assert {document["title"] for document in body["documents"]} == {HANDBOOK_TITLE}

    def test_the_analysis_is_stored_once_per_document(self, client, fake_collection):
        handbook_id = _upload(client, HANDBOOK_TITLE, HANDBOOK)

        chunks = sorted(
            (metadata for _text, metadata in fake_collection.rows.values()),
            key=lambda metadata: metadata["chunk_index"],
        )

        assert len(chunks) > 1
        assert all(metadata["doc_id"] == handbook_id for metadata in chunks)
        assert "auto_summary" in chunks[0]
        assert all("auto_summary" not in metadata for metadata in chunks[1:])
        assert all("entities" not in metadata for metadata in chunks[1:])


class TestPdfPages:
    def test_pdf_passages_record_the_page_they_start_on(self, client, monkeypatch, fake_collection):
        from app.api.routes import file as file_routes  # noqa: PLC0415

        first_page = " ".join(f"Budget line {n} is approved." for n in range(60))
        second_page = " ".join(f"Parking rule {n} applies to the garage." for n in range(60))
        monkeypatch.setattr(
            file_routes, "pdf_pages", AsyncMock(return_value=[first_page, second_page])
        )

        doc_id = client.post(
            "/file", files=[("files", ("budget.pdf", b"%PDF", "application/pdf"))]
        ).json()[0]["doc_id"]

        chunks = sorted(
            (meta for _text, meta in fake_collection.rows.values() if meta["doc_id"] == doc_id),
            key=lambda meta: meta["chunk_index"],
        )
        second_page_starts_at = len(first_page) + 1
        assert chunks[0]["page"] == 1
        assert chunks[-1]["page"] == 2
        assert all(
            meta["page"] == (2 if meta["char_start"] >= second_page_starts_at else 1)
            for meta in chunks
        )
        text = client.get(f"/file/{doc_id}/text").json()["text"]
        assert text == f"{first_page}\n{second_page}"


class TestCorpusScanStoresChunks:
    @pytest.fixture
    def corpus_root(self, tmp_path, monkeypatch, client, deleted_sources_file):
        from app.api.routes import corpus  # noqa: PLC0415

        root = tmp_path / "corpus"
        (root / "policies").mkdir(parents=True)
        (root / "policies" / "handbook.md").write_text(HANDBOOK, encoding="utf-8")
        monkeypatch.setattr(corpus, "CORPUS_ROOT", root.resolve())
        monkeypatch.setattr(
            corpus._ANALYZER, "analyze", MagicMock(return_value={"auto_category": "hr"})
        )
        return root.resolve()

    async def _scan(self, root, rel: str = "policies/handbook.md") -> dict:
        from app.api.routes import corpus  # noqa: PLC0415

        job = corpus._new_job(dry_run=False)
        candidate = {label: cand for _p, label, cand in corpus.walk_corpus(root)}[rel]
        await corpus._ingest_one(job, candidate.resolved, rel, candidate)
        return job

    async def test_a_scanned_file_is_stored_as_chunks_that_carry_its_path(
        self, corpus_root, fake_collection
    ):
        job = await self._scan(corpus_root)

        entry = job["files"][-1]
        assert entry["decision"] == "ingested"
        assert entry["chunks"] == len(fake_collection.rows) > 1
        assert {meta["source_path"] for _t, meta in fake_collection.rows.values()} == {
            "policies/handbook.md"
        }

    async def test_a_second_scan_of_the_same_file_skips_it(self, corpus_root, fake_collection):
        await self._scan(corpus_root)
        rows = dict(fake_collection.rows)

        job = await self._scan(corpus_root)

        assert job["files"][-1]["decision"] == "skipped_unchanged"
        assert fake_collection.rows == rows

    async def test_an_edited_file_replaces_every_chunk_of_the_old_version(
        self, corpus_root, fake_collection
    ):
        first = await self._scan(corpus_root)
        old_id = first["files"][-1]["doc_id"]
        (corpus_root / "policies" / "handbook.md").write_text(MEMO, encoding="utf-8")

        second = await self._scan(corpus_root)

        assert second["totals"]["replaced_stale"] == 1
        assert {meta["doc_id"] for _t, meta in fake_collection.rows.values()} == {
            second["files"][-1]["doc_id"]
        }
        assert old_id != second["files"][-1]["doc_id"]

    async def test_chunks_left_without_their_head_are_ingested_again(
        self, corpus_root, fake_collection
    ):
        first = await self._scan(corpus_root)
        doc_id = first["files"][-1]["doc_id"]
        del fake_collection.rows[f"{doc_id}:0"]

        second = await self._scan(corpus_root)

        assert second["files"][-1]["decision"] == "ingested"
        assert f"{doc_id}:0" in fake_collection.rows
