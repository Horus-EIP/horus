from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.api.routes import corpus
from app.chroma_db.services.corpus_version import current_corpus_version

TOKEN = "corpus-test-token"
HEADERS = {corpus.CORPUS_TOKEN_HEADER: TOKEN}


@pytest.fixture
def corpus_root(tmp_path):
    root = tmp_path / "corpus"
    (root / "reports").mkdir(parents=True)
    (root / "reports" / "q4.md").write_text("Q4 2025 revenue was 4.2M.", encoding="utf-8")
    return root


@pytest.fixture
def client(monkeypatch, fake_collection, deleted_sources_file, corpus_root):
    from app.main import app  # noqa: PLC0415

    monkeypatch.setattr(corpus, "CORPUS_ROOT", corpus_root.resolve())
    monkeypatch.setattr(corpus, "_job", None)
    monkeypatch.setattr(corpus, "_scan_task", None)
    monkeypatch.setenv(corpus.CORPUS_TOKEN_ENV, TOKEN)
    monkeypatch.setattr(
        corpus._ANALYZER, "analyze", MagicMock(return_value={"auto_category": "finance"})
    )
    with TestClient(app) as test_client:
        yield test_client


def _version(client: TestClient) -> str:
    response = client.get("/corpus-version")
    assert response.status_code == 200
    return response.json()["version"]


def _scan(client: TestClient, **params) -> dict:
    assert client.post("/corpus/scan", headers=HEADERS, params=params).status_code == 202
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        status = client.get("/corpus/status", headers=HEADERS).json()
        if status["state"] != "running":
            return status
        time.sleep(0.02)
    raise AssertionError("the corpus scan did not finish")


def _upload(client: TestClient, name: str = "notes.txt", body: bytes = b"Q4 planning notes") -> str:
    response = client.post("/file", files=[("files", (name, body, "text/plain"))])
    assert response.status_code == 200
    return response.json()[0]["doc_id"]


class TestCorpusVersionEndpoint:
    def test_the_version_is_served_without_a_corpus_token(self, client):
        response = client.get("/corpus-version")

        assert response.status_code == 200
        body = response.json()
        assert isinstance(body["version"], str) and body["version"]
        assert body["changed_at"]

    def test_reading_the_version_does_not_change_it(self, client):
        assert _version(client) == _version(client)

    def test_queries_and_listings_do_not_change_the_version(self, client):
        _upload(client)
        before = _version(client)

        client.get("/", params={"query": "Q4 planning"})
        client.get("/file")
        client.get("/categories")

        assert _version(client) == before


class TestCorpusVersionBumps:
    def test_an_upload_bumps_the_version(self, client):
        before = _version(client)

        _upload(client)

        assert _version(client) != before

    def test_each_upload_gives_a_new_version(self, client):
        _upload(client, "a.txt", b"first")
        after_first = _version(client)

        _upload(client, "b.txt", b"second")

        assert _version(client) != after_first

    def test_adding_a_text_document_bumps_the_version(self, client):
        before = _version(client)

        response = client.post(
            "/", json={"id": "doc-1", "title": "notes.txt", "content": "Q4 notes", "size": 8}
        )

        assert response.status_code == 200
        assert _version(client) != before

    def test_a_delete_bumps_the_version(self, client):
        doc_id = _upload(client)
        before = _version(client)

        assert client.delete(f"/{doc_id}").status_code == 200

        assert _version(client) != before

    def test_a_delete_of_an_unknown_id_keeps_the_version(self, client):
        before = _version(client)

        assert client.delete("/not-stored").status_code == 404

        assert _version(client) == before

    def test_a_scan_that_adds_documents_bumps_the_version(self, client):
        before = _version(client)

        assert _scan(client)["totals"]["ingested"] == 1

        assert _version(client) != before

    def test_a_scan_that_changes_nothing_keeps_the_version(self, client):
        _scan(client)
        before = _version(client)

        assert _scan(client)["totals"]["skipped_unchanged"] == 1

        assert _version(client) == before

    def test_a_dry_run_scan_keeps_the_version(self, client):
        before = _version(client)

        assert _scan(client, dry_run=True)["totals"]["would_ingest"] == 1

        assert _version(client) == before

    def test_a_scan_that_replaces_an_edited_file_bumps_the_version_for_the_removal(
        self, client, corpus_root, fake_collection, monkeypatch
    ):
        _scan(client)
        (corpus_root / "reports" / "q4.md").write_text(
            "Q4 2025 revenue was 4.3M.", encoding="utf-8"
        )
        versions_seen_when_storing = []
        store = fake_collection.add

        def record_the_version_then_store(**kwargs):
            versions_seen_when_storing.append(current_corpus_version()["version"])
            return store(**kwargs)

        monkeypatch.setattr(fake_collection, "add", record_the_version_then_store)
        before = _version(client)

        report = _scan(client)

        assert report["totals"]["replaced_stale"] == 1
        assert versions_seen_when_storing[0] != before
        assert _version(client) != versions_seen_when_storing[0]
