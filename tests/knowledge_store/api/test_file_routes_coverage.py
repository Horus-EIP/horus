"""Coverage-focused contract tests for file.py route handlers.

Complements test_file_routes.py with the resolve/list/upload/delete success
paths, the title-matching helper, and the per-file error handling.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes import file as file_mod
from app.chroma_db.services import file_service


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(file_mod.router, prefix="/file")
    return TestClient(app)


class TestMatchStoredTitle:
    def test_match_variants(self):
        m = file_mod._match_stored_title
        assert m("report.pdf", "report.pdf") is True       # exact
        assert m("report", "report.pdf") is True           # same stem
        assert m("/a/b/report.pdf", "report.pdf") is True  # basename
        assert m("other", "report.pdf") is False           # no match
        assert m("", "report.pdf") is False                # empty guard


class TestResolve:
    def test_match_returns_combined_text(self, client, monkeypatch):
        getter = MagicMock(return_value={
            "ids": ["a", "b"],
            "documents": ["body A", "body B"],
            "metadatas": [{"title": "notes.txt"}, {"title": "other.txt"}],
        })
        monkeypatch.setattr(file_service.knowledge_collection, "get", getter)
        r = client.get("/file/resolve", params={"name": "notes.txt"})
        assert r.status_code == 200
        body = r.json()
        assert body["matched_titles"] == ["notes.txt"]
        assert "body A" in body["text"]

    def test_no_match_returns_404(self, client, monkeypatch):
        monkeypatch.setattr(file_service.knowledge_collection, "get", MagicMock(return_value={
            "ids": ["a"], "documents": ["x"], "metadatas": [{"title": "zzz.txt"}],
        }))
        r = client.get("/file/resolve", params={"name": "nope.txt"})
        assert r.status_code == 404

    def test_backend_error_returns_404(self, client, monkeypatch):
        monkeypatch.setattr(file_service.knowledge_collection, "get", MagicMock(side_effect=RuntimeError("boom")))
        r = client.get("/file/resolve", params={"name": "x"})
        assert r.status_code == 404


class TestListFiles:
    def test_returns_documents(self, client, monkeypatch):
        getter = MagicMock(return_value={
            "ids": ["a"],
            "documents": ["the body text"],
            "metadatas": [{
                "title": "doc.pdf", "size": 10, "date": "2023",
                "auto_summary": "sum", "auto_category": "finance",
                "auto_type": "report", "confidence_score": 0.7,
            }],
        })
        monkeypatch.setattr(file_service.knowledge_collection, "get", getter)
        r = client.get("/file")
        assert r.status_code == 200
        docs = r.json()["documents"]
        assert docs[0]["title"] == "doc.pdf"
        assert docs[0]["category"] == "finance"
        assert docs[0]["confidence_score"] == 0.7

    def test_backend_error_returns_404(self, client, monkeypatch):
        monkeypatch.setattr(file_service.knowledge_collection, "get", MagicMock(side_effect=RuntimeError("boom")))
        r = client.get("/file")
        assert r.status_code == 404


class TestUpload:
    def test_pdf_success(self, client, monkeypatch):
        monkeypatch.setattr(file_mod, "save_file", AsyncMock(return_value="/tmp/x.pdf"))
        monkeypatch.setattr(file_mod, "pdf_pages", AsyncMock(return_value=["text"]))
        monkeypatch.setattr(file_mod._content_analyzer, "analyze", MagicMock(return_value={"auto_category": "c"}))
        monkeypatch.setattr(file_mod, "store_file", AsyncMock())
        monkeypatch.setattr(file_mod.os.path, "getsize", lambda p: 123)
        # POST "" takes `files: list[UploadFile]` → multipart field name is "files".
        r = client.post("/file", files=[("files", ("x.pdf", b"%PDF", "application/pdf"))])
        assert r.status_code == 200
        item = r.json()[0]
        assert item["filename"] == "x.pdf"
        assert item["doc_id"]

    def test_per_file_error_captured(self, client, monkeypatch):
        monkeypatch.setattr(file_mod, "save_file", AsyncMock(side_effect=OSError("nope")))
        r = client.post("/file", files=[("files", ("x.pdf", b"%PDF", "application/pdf"))])
        assert r.status_code == 200
        assert "error" in r.json()[0]

    def test_upload_records_where_the_file_is_stored(self, client, monkeypatch):
        monkeypatch.setattr(file_mod, "save_file", AsyncMock(return_value="documents/pdf/x.pdf"))
        monkeypatch.setattr(file_mod, "pdf_pages", AsyncMock(return_value=["text"]))
        monkeypatch.setattr(file_mod._content_analyzer, "analyze", MagicMock(return_value={}))
        store = AsyncMock()
        monkeypatch.setattr(file_mod, "store_file", store)
        monkeypatch.setattr(file_mod.os.path, "getsize", lambda p: 123)

        client.post("/file", files=[("files", ("x.pdf", b"%PDF", "application/pdf"))])

        assert store.await_args.kwargs["extra_metadata"] == {"stored_path": "documents/pdf/x.pdf"}


class TestDelete:
    def test_success(self, client, monkeypatch):
        monkeypatch.setattr(file_mod.os, "walk", lambda d: iter([("documents", [], ["foo.txt"])]))
        removed = {}
        monkeypatch.setattr(file_mod.os, "remove", lambda p: removed.setdefault("p", p))
        r = client.delete("/file/foo.txt")
        assert r.status_code == 200
        assert r.json() == {"msg": "foo.txt deleted"}
        assert removed["p"].endswith("foo.txt")

    def test_missing_returns_404(self, client, monkeypatch):
        monkeypatch.setattr(file_mod.os, "walk", lambda d: iter([]))
        r = client.delete("/file/ghost.txt")
        assert r.status_code == 404


class TestUploadToText:
    def test_pdf_success(self, client, monkeypatch):
        monkeypatch.setattr(file_mod, "save_file", AsyncMock(return_value="/tmp/x.pdf"))
        monkeypatch.setattr(file_mod, "pdf_pages", AsyncMock(return_value=["extracted"]))
        monkeypatch.setattr(file_mod._content_analyzer, "analyze", MagicMock(return_value={"auto_category": "c"}))
        monkeypatch.setattr(file_mod, "store_file", AsyncMock())
        monkeypatch.setattr(file_mod.os.path, "exists", lambda p: False)
        r = client.post("/file/pdf", params={"doc_id": "d1"},
                        files={"file": ("x.pdf", b"%PDF", "application/pdf")})
        assert r.status_code == 200
        assert r.json()["text"] == "extracted\n"

    def test_upload_records_where_the_file_is_stored(self, client, monkeypatch):
        monkeypatch.setattr(file_mod, "save_file", AsyncMock(return_value="documents/image/x.pdf"))
        monkeypatch.setattr(file_mod, "image_pdf_pages", AsyncMock(return_value=["scanned"]))
        monkeypatch.setattr(file_mod._content_analyzer, "analyze", MagicMock(return_value={}))
        store = AsyncMock()
        monkeypatch.setattr(file_mod, "store_file", store)
        monkeypatch.setattr(file_mod.os.path, "exists", lambda p: False)

        client.post("/file/image", params={"doc_id": "d1"},
                    files={"file": ("x.pdf", b"%PDF", "application/pdf")})

        assert store.await_args.kwargs["extra_metadata"] == {
            "stored_path": "documents/image/x.pdf"
        }

    def test_invalid_type_returns_400(self, client, monkeypatch):
        monkeypatch.setattr(file_mod, "save_file", AsyncMock(return_value="/tmp/x.bin"))
        r = client.post("/file/exe", params={"doc_id": "d1"},
                        files={"file": ("x.bin", b"x", "application/octet-stream")})
        assert r.status_code == 400

    def test_docx_success(self, client, monkeypatch):
        monkeypatch.setattr(file_mod, "save_file", AsyncMock(return_value="/tmp/x.docx"))
        monkeypatch.setattr(file_mod, "docx_to_text", AsyncMock(return_value="d"))
        monkeypatch.setattr(file_mod._content_analyzer, "analyze", MagicMock(return_value={}))
        monkeypatch.setattr(file_mod, "store_file", AsyncMock())
        monkeypatch.setattr(file_mod.os.path, "exists", lambda p: False)
        r = client.post("/file/docx", params={"doc_id": "d1"},
                        files={"file": ("x.docx", b"PK", "application/octet-stream")})
        assert r.status_code == 200

    def test_image_success(self, client, monkeypatch):
        monkeypatch.setattr(file_mod, "save_file", AsyncMock(return_value="/tmp/x.png"))
        monkeypatch.setattr(file_mod, "image_pdf_pages", AsyncMock(return_value=["ocr"]))
        monkeypatch.setattr(file_mod._content_analyzer, "analyze", MagicMock(return_value={}))
        monkeypatch.setattr(file_mod, "store_file", AsyncMock())
        monkeypatch.setattr(file_mod.os.path, "exists", lambda p: True)
        monkeypatch.setattr(file_mod.os.path, "getsize", lambda p: 9)
        r = client.post("/file/image", params={"doc_id": "d2"},
                        files={"file": ("x.png", b"\x89PNG", "image/png")})
        assert r.status_code == 200
        assert r.json()["text"] == "ocr"


class TestUploadMoreFormats:
    """docx / txt / unknown-extension branches of the multi-file upload."""

    def _patch_common(self, monkeypatch):
        monkeypatch.setattr(file_mod._content_analyzer, "analyze", MagicMock(return_value={}))
        monkeypatch.setattr(file_mod, "store_file", AsyncMock())
        monkeypatch.setattr(file_mod.os.path, "getsize", lambda p: 5)

    def test_docx_branch(self, client, monkeypatch):
        self._patch_common(monkeypatch)
        monkeypatch.setattr(file_mod, "save_file", AsyncMock(return_value="/tmp/x.docx"))
        monkeypatch.setattr(file_mod, "docx_to_text", AsyncMock(return_value="text"))
        r = client.post("/file", files=[("files", ("x.docx", b"PK", "application/octet-stream"))])
        assert r.status_code == 200
        assert r.json()[0]["filename"] == "x.docx"

    def test_txt_branch(self, client, monkeypatch, tmp_path):
        self._patch_common(monkeypatch)
        p = tmp_path / "x.txt"
        p.write_text("plain text body")
        monkeypatch.setattr(file_mod, "save_file", AsyncMock(return_value=str(p)))
        r = client.post("/file", files=[("files", ("x.txt", b"plain text body", "text/plain"))])
        assert r.status_code == 200

    def test_unknown_extension_branch(self, client, monkeypatch, tmp_path):
        self._patch_common(monkeypatch)
        p = tmp_path / "x.bin"
        p.write_text("some bytes as text")
        monkeypatch.setattr(file_mod, "save_file", AsyncMock(return_value=str(p)))
        r = client.post("/file", files=[("files", ("x.bin", b"x", "application/octet-stream"))])
        assert r.status_code == 200


class TestListEdges:
    def test_bad_metadata_and_long_text(self, client, monkeypatch):
        long_text = "x" * 500
        getter = MagicMock(return_value={
            "ids": ["a"],
            "documents": [long_text],
            "metadatas": [{"title": "d", "size": "notint", "confidence_score": "bad"}],
        })
        monkeypatch.setattr(file_service.knowledge_collection, "get", getter)
        r = client.get("/file")
        assert r.status_code == 200
        doc = r.json()["documents"][0]
        assert doc["size"] == 0                  # int("notint") → ValueError → 0
        assert doc["excerpt"].endswith("...")    # text > 400 chars → truncated
        assert "confidence_score" not in doc     # float("bad") → None → key omitted
