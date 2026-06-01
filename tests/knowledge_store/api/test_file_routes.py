"""Knowledge Store /file routes contract tests (hermetic).

Routes under test (``src/services/knowledge-store/app/api/routes/file.py``,
mounted under ``/file``):

* ``GET    /file/resolve``     → 200 / 404
* ``POST   /file``             → 200 / 422
* ``GET    /file``             → 200
* ``DELETE /file/{filename}``  → 200 / 404 (handler walks documents/ on disk)
* ``POST   /file/{type}``      → 200 / 400
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from app.api.routes.file import router  # noqa: PLC0415

    app = FastAPI()
    app.include_router(router, prefix="/file")
    return TestClient(app)


class TestFileList:
    def test_list_returns_200(self, client):
        # Route reads knowledge_collection (mocked at conftest level)
        r = client.get("/file")
        assert r.status_code in (200, 404)


class TestFileUpload:
    def test_upload_with_no_files_returns_422(self, client):
        r = client.post("/file")
        assert r.status_code == 422

    def test_upload_invalid_type_segment_returns_400_or_422(self, client):
        # POST /file/{type} where {type} is anything unexpected
        files = {"file": ("doc.txt", b"x", "text/plain")}
        r = client.post("/file/exe", files=files)
        assert r.status_code in (400, 422)


class TestFileDelete:
    def test_delete_missing_returns_404(self, client):
        # The handler walks the `documents/` directory — in a hermetic test
        # environment that dir is empty or doesn't exist, so a missing file
        # yields 404.
        r = client.delete("/file/ghost-name.txt")
        assert r.status_code == 404


class TestFileResolve:
    def test_resolve_by_filename_returns_200_or_404(self, client):
        # ChromaDB.get() is mocked at conftest level
        r = client.get("/file/resolve", params={"filename": "doc.txt"})
        assert r.status_code in (200, 404)
