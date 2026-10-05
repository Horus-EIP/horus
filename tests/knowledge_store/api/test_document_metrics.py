from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from prometheus_client import REGISTRY

from app.chroma_db.models import DocumentModel
from app.chroma_db.services import file_service

OPERATIONS = "knowledge_store_document_operations_total"
DOCUMENTS = "knowledge_store_documents_total"

REPORT = "Q4 revenue was $4.2M. Operating costs were $3.1M. " * 40
MEMO = "Lunch is served after the Monday meeting."


def operations(operation: str, status: str) -> float:
    return REGISTRY.get_sample_value(
        OPERATIONS, {"operation": operation, "status": status}
    ) or 0.0


def documents() -> float | None:
    return REGISTRY.get_sample_value(DOCUMENTS)


class Counted:
    def __init__(self):
        self.before = {
            (operation, status): operations(operation, status)
            for operation in ("add", "delete", "get")
            for status in ("success", "error")
        }

    def since(self, operation: str, status: str) -> float:
        return operations(operation, status) - self.before[(operation, status)]


@pytest.fixture
def client(fake_collection, documents_root, deleted_sources_file, monkeypatch):
    from app.main import app  # noqa: PLC0415

    monkeypatch.setattr(file_service, "get_embeddings", lambda texts: [[1.0, 0.0] for _ in texts])
    with TestClient(app) as test_client:
        yield test_client


def upload(client: TestClient, title: str, body: str) -> str:
    response = client.post("/file", files=[("files", (title, body.encode(), "text/plain"))])
    assert response.status_code == 200
    return response.json()[0]["doc_id"]


class TestDocumentOperations:
    def test_an_upload_counts_one_add_and_updates_the_document_count(self, client):
        counted = Counted()

        upload(client, "q4.txt", REPORT)
        upload(client, "memo.txt", MEMO)

        assert counted.since("add", "success") == 2
        assert counted.since("add", "error") == 0
        assert documents() == 2

    async def test_a_failed_add_is_counted_as_an_error(self, fake_collection, monkeypatch):
        def unavailable(_texts):
            raise RuntimeError("embedder unavailable")

        monkeypatch.setattr(file_service, "get_embeddings", unavailable)
        counted = Counted()

        with pytest.raises(RuntimeError, match="embedder unavailable"):
            await file_service.store_file(
                DocumentModel(id="notes", title="notes.txt", content=MEMO, size=len(MEMO))
            )

        assert counted.since("add", "error") == 1
        assert counted.since("add", "success") == 0

    def test_a_delete_counts_and_lowers_the_document_count(self, client):
        report_id = upload(client, "q4.txt", REPORT)
        upload(client, "memo.txt", MEMO)
        counted = Counted()

        assert client.delete(f"/{report_id}").status_code == 200

        assert counted.since("delete", "success") == 1
        assert documents() == 1

    def test_deleting_an_unknown_document_is_counted_as_an_error(self, client):
        counted = Counted()

        assert client.delete("/no-such-document").status_code == 404

        assert counted.since("delete", "error") == 1
        assert counted.since("delete", "success") == 0

    def test_reading_a_document_counts_a_get(self, client):
        report_id = upload(client, "q4.txt", REPORT)
        counted = Counted()

        assert client.get(f"/file/{report_id}/text").status_code == 200
        assert client.get("/file/no-such-document/text").status_code == 404

        assert counted.since("get", "success") == 1
        assert counted.since("get", "error") == 1

    def test_resolving_a_document_by_name_counts_a_get(self, client):
        upload(client, "q4.txt", REPORT)
        counted = Counted()

        assert client.get("/file/resolve", params={"name": "q4.txt"}).status_code == 200
        assert client.get("/file/resolve", params={"name": "missing.txt"}).status_code == 404

        assert counted.since("get", "success") == 1
        assert counted.since("get", "error") == 1

    def test_a_count_that_cannot_be_read_leaves_the_gauge_alone(
        self, fake_collection, monkeypatch
    ):
        file_service.refresh_document_count()
        before = documents()

        def locked(**_selector):
            raise RuntimeError("chroma is locked")

        monkeypatch.setattr(fake_collection, "get", locked)
        file_service.refresh_document_count()

        assert documents() == before
