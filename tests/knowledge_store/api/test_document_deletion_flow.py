from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.api.routes import corpus

TOKEN = "corpus-test-token"
HEADERS = {corpus.CORPUS_TOKEN_HEADER: TOKEN}


@pytest.fixture
def client(monkeypatch, fake_collection, deleted_sources_file, tmp_path):
    from app.main import app  # noqa: PLC0415

    root = tmp_path / "corpus"
    (root / "reports").mkdir(parents=True)
    (root / "reports" / "q4.md").write_text("Q4 2025 revenue was 4.2M.", encoding="utf-8")
    monkeypatch.setattr(corpus, "CORPUS_ROOT", root.resolve())
    monkeypatch.setattr(corpus, "_job", None)
    monkeypatch.setattr(corpus, "_scan_task", None)
    monkeypatch.setenv(corpus.CORPUS_TOKEN_ENV, TOKEN)
    monkeypatch.setattr(
        corpus._ANALYZER, "analyze", MagicMock(return_value={"auto_category": "finance"})
    )
    with TestClient(app) as test_client:
        yield test_client


def _scan(client: TestClient) -> dict:
    assert client.post("/corpus/scan", headers=HEADERS).status_code == 202
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        status = client.get("/corpus/status", headers=HEADERS).json()
        if status["state"] != "running":
            return status
        time.sleep(0.02)
    raise AssertionError("the corpus scan did not finish")


def _listed_ids(client: TestClient) -> list[str]:
    return [doc["id"] for doc in client.get("/file").json()["documents"]]


class TestDeleteFromTheKnowledgeStorePage:
    def test_an_uploaded_document_is_gone_from_the_list_and_the_disk(
        self, client, tmp_path
    ):
        uploaded = client.post(
            "/file", files=[("files", ("notes.txt", b"Q4 planning notes", "text/plain"))]
        ).json()[0]
        doc_id = uploaded["doc_id"]
        stored = tmp_path / "documents" / "txt" / "notes.txt"
        assert stored.exists()
        assert _listed_ids(client) == [doc_id]

        assert client.delete(f"/{doc_id}").status_code == 200

        assert _listed_ids(client) == []
        assert not stored.exists()
        assert client.get("/", params={"query": "Q4 planning"}).status_code == 404

    def test_a_deleted_corpus_document_does_not_come_back_on_the_next_scan(self, client):
        first = _scan(client)
        assert first["totals"]["ingested"] == 1
        doc_id = first["files"][0]["doc_id"]
        assert _listed_ids(client) == [doc_id]

        assert client.delete(f"/{doc_id}").status_code == 200
        second = _scan(client)

        assert second["state"] == "completed"
        assert second["files"][0]["decision"] == "skipped_deleted"
        assert second["totals"]["skipped_deleted"] == 1
        assert _listed_ids(client) == []
        assert client.get("/", params={"query": "Q4 revenue"}).status_code == 404
