from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient
from prometheus_client import REGISTRY

from app.api.routes import corpus
from app.chroma_db import setup
from app.chroma_db.services import file_service

TOKEN = "corpus-test-token"
HEADERS = {corpus.CORPUS_TOKEN_HEADER: TOKEN}
OLD_MODEL = "sentence-transformers:BAAI/bge-base-en-v1.5"
KEYWORDS = ("parking", "lunch", "meeting", "laptop")

POLICY = (
    "\n".join(
        f"Rule {n}. Staff keep the shared spaces tidy and report broken equipment."
        for n in range(1, 40)
    )
    + "\nParking. Visitors get a parking pass from reception."
)
MEMO = "Lunch after the meeting. Parking is limited. Bring a laptop."


def keyword_vector(text: str) -> list[float]:
    read = text[:2000].lower()
    return [float(read.count(keyword)) for keyword in KEYWORDS]


def wait_for(condition: Callable[[], bool], timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(0.02)
    raise AssertionError("the startup check did not finish")


def documents_gauge() -> float | None:
    return REGISTRY.get_sample_value("knowledge_store_documents_total")


@pytest.fixture
def embedded(monkeypatch):
    texts: list[str] = []
    release = threading.Event()
    release.set()

    def embed(batch):
        release.wait(timeout=10)
        texts.extend(batch)
        return [keyword_vector(text) for text in batch]

    monkeypatch.setattr(file_service, "get_embeddings", embed)
    return texts, release


@pytest.fixture
def startup(monkeypatch, fake_collection, deleted_sources_file):
    from app.main import app  # noqa: PLC0415

    for name in ("_job", "_scan_task", "_reindex_job", "_reindex_task", "_startup_check"):
        monkeypatch.setattr(corpus, name, None)
    monkeypatch.setenv(corpus.CORPUS_TOKEN_ENV, TOKEN)
    monkeypatch.setenv(corpus.STARTUP_REINDEX_ENV, "1")

    def start() -> TestClient:
        return TestClient(app)

    return start


def store_whole_file(collection, doc_id: str, text: str, title: str) -> None:
    collection.add(
        ids=[doc_id],
        documents=[text],
        metadatas=[{"title": title, "auto_category": "operations"}],
        embeddings=[keyword_vector(text)],
    )


def store_passage(collection, doc_id: str, text: str, embed_model: str) -> None:
    collection.add(
        ids=[f"{doc_id}:0"],
        documents=[text],
        metadatas=[
            {
                "doc_id": doc_id,
                "title": f"{doc_id}.md",
                "chunk_index": 0,
                "chunk_count": 1,
                "char_start": 0,
                "char_end": len(text),
                "category": "general",
                "embed_model": embed_model,
            }
        ],
        embeddings=[keyword_vector(text)],
    )


def reindex_report(client: TestClient) -> dict:
    return client.get("/corpus/reindex", headers=HEADERS).json()


def finished(client: TestClient) -> Callable[[], bool]:
    return lambda: reindex_report(client)["state"] in ("completed", "failed")


def startup_check_done() -> bool:
    return corpus._startup_check is not None and corpus._startup_check.done()


class TestStartupReindex:
    def test_whole_file_and_stale_entries_are_reindexed_once_in_the_background(
        self, startup, fake_collection, embedded, caplog
    ):
        store_whole_file(fake_collection, "policy", POLICY, "Office_Policy.md")
        store_passage(fake_collection, "memo", MEMO, OLD_MODEL)
        texts, _ = embedded

        with caplog.at_level(logging.INFO, logger="CorpusRouter"), startup() as client:
            wait_for(finished(client))
            report = reindex_report(client)

        assert report["state"] == "completed"
        assert report["trigger"] == corpus.STARTUP
        assert report["embed_model"] == setup.EMBED_MODEL
        assert report["totals"]["pending"] == 2
        assert report["totals"]["migrated"] == 1
        assert report["totals"]["reembedded"] == 1
        assert "policy" not in fake_collection.rows
        assert {metadata["embed_model"] for _, metadata in fake_collection.rows.values()} == {
            setup.EMBED_MODEL
        }
        assert MEMO in texts
        assert "started in the background for 2 documents" in caplog.text

    def test_the_collection_records_the_embedder_and_the_count_once_the_job_is_done(
        self, startup, fake_collection, embedded
    ):
        fake_collection.metadata = {"embedding_model": "BAAI/bge-base-en-v1.5", "dimensions": 768}
        store_whole_file(fake_collection, "policy", POLICY, "Office_Policy.md")
        store_passage(fake_collection, "memo", MEMO, OLD_MODEL)

        with startup() as client:
            wait_for(finished(client))

        assert fake_collection.metadata == setup.COLLECTION_METADATA
        assert documents_gauge() == 2

    def test_the_health_check_answers_while_the_reindex_runs(
        self, startup, fake_collection, embedded
    ):
        store_passage(fake_collection, "memo", MEMO, OLD_MODEL)
        _, release = embedded
        release.clear()

        with startup() as client:
            wait_for(lambda: reindex_report(client)["state"] == "running")
            health = client.get("/health")
            still_running = reindex_report(client)["state"] == "running"
            release.set()
            wait_for(finished(client))

        assert health.status_code == 200
        assert still_running

    def test_a_restart_after_the_reindex_starts_no_second_job(
        self, startup, fake_collection, embedded
    ):
        store_whole_file(fake_collection, "policy", POLICY, "Office_Policy.md")
        with startup() as client:
            wait_for(finished(client))
        corpus._reindex_job = None
        texts, _ = embedded
        texts.clear()

        with startup() as client:
            wait_for(startup_check_done)
            report = reindex_report(client)

        assert report["state"] == "idle"
        assert texts == []

    def test_an_index_already_on_the_current_embedder_starts_no_job(
        self, startup, fake_collection, embedded, caplog
    ):
        store_passage(fake_collection, "memo", MEMO, setup.EMBED_MODEL)

        with caplog.at_level(logging.INFO, logger="CorpusRouter"), startup() as client:
            wait_for(startup_check_done)
            report = reindex_report(client)

        assert report["state"] == "idle"
        assert embedded[0] == []
        assert fake_collection.metadata == setup.COLLECTION_METADATA
        assert documents_gauge() == 1
        assert f"every stored passage is embedded with {setup.EMBED_MODEL}" in caplog.text

    def test_turned_off_it_only_says_how_many_documents_need_it(
        self, startup, fake_collection, embedded, monkeypatch, caplog
    ):
        monkeypatch.setenv(corpus.STARTUP_REINDEX_ENV, "0")
        store_whole_file(fake_collection, "policy", POLICY, "Office_Policy.md")
        store_passage(fake_collection, "memo", MEMO, OLD_MODEL)

        with caplog.at_level(logging.WARNING, logger="CorpusRouter"), startup() as client:
            wait_for(startup_check_done)
            report = reindex_report(client)

        assert report["state"] == "idle"
        assert "policy" in fake_collection.rows
        assert embedded[0] == []
        assert "2 documents are stored as whole files or with another embedder" in caplog.text
        assert "scripts/reindex-knowledge-store.py" in caplog.text


class TestStartupCheckEdges:
    async def test_a_scan_already_running_is_left_alone(
        self, fake_collection, embedded, monkeypatch, caplog
    ):
        monkeypatch.setattr(corpus, "_reindex_job", None)
        monkeypatch.setenv(corpus.STARTUP_REINDEX_ENV, "1")
        store_passage(fake_collection, "memo", MEMO, OLD_MODEL)
        await corpus._scan_slot.acquire()
        try:
            with caplog.at_level(logging.WARNING, logger="CorpusRouter"):
                job = await corpus.check_index_on_startup()
        finally:
            corpus._scan_slot.release()

        assert job is None
        assert corpus._reindex_job is None
        assert "1 documents need a re-index" in caplog.text

    async def test_a_failed_check_is_logged_and_starts_nothing(
        self, fake_collection, monkeypatch, caplog
    ):
        monkeypatch.setattr(corpus, "_reindex_job", None)

        def unreadable(_embed_model):
            raise RuntimeError("chroma is locked")

        monkeypatch.setattr(corpus.reindex, "documents_to_reindex", unreadable)

        with caplog.at_level(logging.WARNING, logger="CorpusRouter"):
            job = await corpus.check_index_on_startup()

        assert job is None
        assert corpus._reindex_job is None
        assert "chroma is locked" in caplog.text

    @pytest.mark.parametrize("value", ["0", "false", "No", " off "])
    def test_the_switch_reads_the_usual_off_values(self, monkeypatch, value):
        monkeypatch.setenv(corpus.STARTUP_REINDEX_ENV, value)

        assert corpus.reindex_on_startup_enabled() is False

    def test_the_reindex_runs_at_startup_unless_told_otherwise(self, monkeypatch):
        monkeypatch.delenv(corpus.STARTUP_REINDEX_ENV, raising=False)

        assert corpus.reindex_on_startup_enabled() is True
