from __future__ import annotations

import asyncio
import time

import pytest
from fastapi.testclient import TestClient

from app.api.routes import corpus
from app.chroma_db.services import file_service, reindex
from app.chroma_db.services.corpus_version import current_corpus_version

TOKEN = "corpus-test-token"
HEADERS = {corpus.CORPUS_TOKEN_HEADER: TOKEN}
CURRENT_MODEL = "fake-keywords:v2"
KEYWORDS = ("parking", "lunch", "meeting", "laptop")

LONG_POLICY = "\n".join(
    f"Rule {n}. Staff keep the shared spaces tidy and report broken equipment."
    for n in range(1, 60)
) + "\nParking. Visitors get a parking pass from reception for the parking garage."
LEGACY_METADATA = {
    "title": "Office_Policy.md",
    "date": "2026-06-01 09:00:00+00:00",
    "size": len(LONG_POLICY),
    "auto_category": "operations",
    "auto_summary": "How the office is run.",
    "entities": "{}",
    "stored_path": "documents/md/Office_Policy.md",
}


def keyword_vector(text: str) -> list[float]:
    read = text[:2000].lower()
    return [float(read.count(keyword)) for keyword in KEYWORDS]


@pytest.fixture
def embedder(monkeypatch):
    calls: list[int] = []

    def embed(texts):
        calls.append(len(texts))
        return [keyword_vector(text) for text in texts]

    monkeypatch.setattr(file_service, "get_embeddings", embed)
    monkeypatch.setattr(
        file_service, "get_embedding", lambda text, is_query=False: keyword_vector(text)
    )
    monkeypatch.setattr(file_service, "EMBED_MODEL", CURRENT_MODEL)
    return calls


@pytest.fixture
def legacy_store(fake_collection, embedder):
    fake_collection.add(
        ids=["policy"],
        documents=[LONG_POLICY],
        metadatas=[dict(LEGACY_METADATA)],
        embeddings=[keyword_vector(LONG_POLICY)],
    )
    fake_collection.add(
        ids=["memo"],
        documents=["Lunch after the meeting. Parking is limited. Bring a laptop."],
        metadatas=[{"title": "Memo.md", "auto_category": "general"}],
        embeddings=[keyword_vector("Lunch after the meeting. Parking is limited. Bring a laptop.")],
    )
    return fake_collection


@pytest.fixture
def client(monkeypatch, legacy_store, deleted_sources_file):
    from app.main import app  # noqa: PLC0415

    monkeypatch.setattr(corpus, "_job", None)
    monkeypatch.setattr(corpus, "_scan_task", None)
    monkeypatch.setattr(corpus, "_reindex_job", None)
    monkeypatch.setattr(corpus, "_reindex_task", None)
    monkeypatch.setenv(corpus.CORPUS_TOKEN_ENV, TOKEN)
    with TestClient(app) as test_client:
        yield test_client


def _reindex(client: TestClient) -> dict:
    assert client.post("/corpus/reindex", headers=HEADERS).status_code == 202
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        status = client.get("/corpus/reindex", headers=HEADERS).json()
        if status["state"] != "running":
            return status
        time.sleep(0.02)
    raise AssertionError("the re-index did not finish")


def _policy_chunks(collection) -> list[dict]:
    return sorted(
        (meta for _text, meta in collection.rows.values() if meta.get("doc_id") == "policy"),
        key=lambda meta: meta["chunk_index"],
    )


class TestReindexEndpoint:
    def test_whole_file_entries_become_chunks_that_record_the_embed_model(
        self, client, legacy_store
    ):
        report = _reindex(client)

        assert report["state"] == "completed"
        assert report["embed_model"] == CURRENT_MODEL
        assert report["totals"]["migrated"] == 2
        assert "policy" not in legacy_store.rows
        chunks = _policy_chunks(legacy_store)
        assert len(chunks) > 1
        assert all(meta["embed_model"] == CURRENT_MODEL for meta in chunks)
        assert all(meta["title"] == "Office_Policy.md" for meta in chunks)
        assert all(meta["category"] == "operations" for meta in chunks)
        assert chunks[0]["auto_summary"] == "How the office is run."
        assert chunks[0]["date"] == LEGACY_METADATA["date"]
        assert all("auto_summary" not in meta for meta in chunks[1:])

    def test_after_the_re_index_the_end_of_a_long_document_is_found(self, client):
        before = client.get("/", params={"query": "parking pass", "n_results": 1}).json()
        assert before["ids"] == [["memo"]]

        _reindex(client)

        after = client.get("/", params={"query": "parking pass", "n_results": 1}).json()
        assert after["metadatas"][0][0]["doc_id"] == "policy"
        assert "parking pass" in after["documents"][0][0]

    def test_a_second_run_changes_nothing(self, client, legacy_store, embedder):
        _reindex(client)
        rows = dict(legacy_store.rows)
        embedded = len(embedder)
        version = current_corpus_version()["version"]

        report = _reindex(client)

        assert report["totals"]["pending"] == 0
        assert legacy_store.rows == rows
        assert len(embedder) == embedded
        assert current_corpus_version()["version"] == version

    def test_each_changed_document_bumps_the_corpus_version(self, client):
        before = current_corpus_version()["version"]

        _reindex(client)

        assert current_corpus_version()["version"] != before

    def test_listing_and_full_text_are_unchanged_by_the_migration(self, client):
        listed_before = {doc["id"]: doc for doc in client.get("/file").json()["documents"]}

        _reindex(client)

        listed_after = {doc["id"]: doc for doc in client.get("/file").json()["documents"]}
        passages = {doc_id: doc.pop("chunk_count") for doc_id, doc in listed_after.items()}
        assert listed_after == listed_before
        assert all(count >= 1 for count in passages.values())
        assert passages["policy"] > 1
        assert client.get("/file/policy/text").json()["text"] == LONG_POLICY

    def test_the_status_is_idle_before_any_run(self, client):
        status = client.get("/corpus/reindex", headers=HEADERS).json()

        assert status == {"state": "idle", "embed_model": CURRENT_MODEL}

    def test_the_re_index_needs_the_corpus_token(self, client):
        assert client.post("/corpus/reindex").status_code == 403

    def test_a_re_index_waits_for_a_running_scan(self, client, monkeypatch):
        monkeypatch.setattr(corpus, "_job", {"job_id": "scan-1", "state": "running"})
        monkeypatch.setattr(corpus, "_scan_slot", asyncio.Semaphore(0))

        response = client.post("/corpus/reindex", headers=HEADERS)

        assert response.status_code == 409
        assert "scan-1" in response.json()["error"]


class TestReindexDocument:
    def test_an_interrupted_migration_is_finished_by_the_next_run(
        self, legacy_store, embedder, monkeypatch
    ):
        monkeypatch.setattr(file_service, "WRITE_BATCH_SIZE", 2)
        add = legacy_store.add
        batches = {"seen": 0}

        def crash_on_the_third_batch(**kwargs):
            batches["seen"] += 1
            if batches["seen"] == 3:
                raise RuntimeError("container stopped")
            add(**kwargs)

        monkeypatch.setattr(legacy_store, "add", crash_on_the_third_batch)
        with pytest.raises(RuntimeError):
            reindex.reindex_document("policy", file_service.get_embeddings, CURRENT_MODEL)
        assert legacy_store.rows["policy"][0] == LONG_POLICY

        monkeypatch.setattr(legacy_store, "add", add)
        outcome = reindex.reindex_document("policy", file_service.get_embeddings, CURRENT_MODEL)

        assert outcome == reindex.MIGRATED
        assert "policy" not in legacy_store.rows
        assert file_service.document_texts(["policy"])["policy"].text == LONG_POLICY

    def test_chunks_left_by_a_crash_after_the_write_are_rebuilt(self, legacy_store, embedder):
        legacy_store.add(
            ids=["policy:0"],
            documents=["stale partial chunk"],
            metadatas=[{"doc_id": "policy", "chunk_index": 0, "char_start": 0, "char_end": 19}],
        )

        reindex.reindex_document("policy", file_service.get_embeddings, CURRENT_MODEL)

        assert "stale partial chunk" not in [text for text, _meta in legacy_store.rows.values()]
        assert file_service.document_texts(["policy"])["policy"].text == LONG_POLICY

    def test_chunks_from_another_embed_model_are_embedded_again_in_place(
        self, legacy_store, embedder
    ):
        reindex.reindex_document("policy", file_service.get_embeddings, "old-model")
        ids_before = sorted(entry_id for entry_id in legacy_store.rows if entry_id.startswith("policy:"))
        embedded = sum(embedder)

        outcome = reindex.reindex_document("policy", file_service.get_embeddings, CURRENT_MODEL)

        assert outcome == reindex.REEMBEDDED
        assert sum(embedder) - embedded == len(ids_before)
        assert sorted(meta["chunk_index"] for meta in _policy_chunks(legacy_store)) == list(
            range(len(ids_before))
        )
        assert all(meta["embed_model"] == CURRENT_MODEL for meta in _policy_chunks(legacy_store))

    def test_documents_to_reindex_lists_legacy_and_stale_documents_once(
        self, legacy_store, embedder
    ):
        reindex.reindex_document("policy", file_service.get_embeddings, "old-model")

        assert reindex.documents_to_reindex(CURRENT_MODEL) == ["memo", "policy"]
        assert reindex.documents_to_reindex("old-model") == ["memo"]

    def test_an_up_to_date_document_is_unchanged(self, legacy_store, embedder):
        reindex.reindex_document("memo", file_service.get_embeddings, CURRENT_MODEL)

        assert (
            reindex.reindex_document("memo", file_service.get_embeddings, CURRENT_MODEL)
            == reindex.UNCHANGED
        )
