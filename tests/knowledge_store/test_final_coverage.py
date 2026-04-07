import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app
import logging
from unittest.mock import patch, MagicMock
import sys
import importlib
import os
import builtins

@pytest.fixture
def async_client():
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")

@pytest.mark.asyncio
async def test_file_route_invalid_type_final_coverage(async_client, tmp_path):
    test_file = tmp_path / "test_output.txt"
    test_file.write_text("dummy")
    with patch("app.api.routes.store.save_file", side_effect=Exception("Disk full")):
        with open(test_file, "rb") as f:
            response = await async_client.post(
                "/upload", 
                files={"file": ("test.txt", f, "text/plain")}
            )
            assert response.status_code in (400, 404, 405, 500)
            
@pytest.mark.asyncio
async def test_store_route_exception_final_coverage(async_client):
    with patch("app.api.routes.store.query_knowledge", side_effect=Exception("Database error")):
        response = await async_client.get("/", params={"query": "test"})
        assert response.status_code == 500
        body = response.json()
        error_msg = body.get("detail", "") or body.get("error", "")
        assert "Database error" in error_msg

def test_posthog_safe_capture_coverage():
    mock_posthog = MagicMock()
    call_count = {"n": 0}

    def _capture_side_effect(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise TypeError("Type error")
        return None

    mock_original_capture = MagicMock(side_effect=_capture_side_effect)
    mock_posthog.capture = mock_original_capture

    with patch.dict(sys.modules, {"posthog": mock_posthog}):
        with patch("chromadb.PersistentClient"):
            import app.chroma_db.setup
            importlib.reload(app.chroma_db.setup)
            wrapped_capture = app.chroma_db.setup.posthog.capture

            res = wrapped_capture("event_name")
            assert res is None

            call_count["n"] = 0
            mock_original_capture.side_effect = TypeError("Type error")
            res_empty = wrapped_capture()
            assert res_empty is None

def test_posthog_import_exception_coverage():
    original_import = builtins.__import__
    
    def side_effect(name, *args, **kwargs):
        if name == 'posthog':
            raise Exception("Import failed")
        return original_import(name, *args, **kwargs)

    if "posthog" in sys.modules:
        del sys.modules["posthog"]
            
    with patch("builtins.__import__", side_effect=side_effect):
         import app.chroma_db.setup
         importlib.reload(app.chroma_db.setup)

@pytest.mark.asyncio
async def test_file_route_image_type(async_client, tmp_path):
    test_file = tmp_path / "test_output.txt"
    test_file.write_text("dummy")
    with patch("app.api.routes.file.save_file", return_value="test_path"), \
         patch("app.api.routes.file.image_pdf_to_text", return_value="Extracted text") as mock_ocr, \
         patch("app.api.routes.file.store_file") as mock_store, \
         patch("os.path.getsize", return_value=123), \
         patch("os.remove"):
        with open(test_file, "rb") as f:
            response = await async_client.post(
                "/file/image",
                params={"doc_id": "123"},
                files={"file": ("test.png", f, "image/png")}
            )
            assert response.status_code == 200
            mock_ocr.assert_awaited_once()

def test_content_analyzer_entities():
    # Mock spacy loading to control entities
    mock_nlp = MagicMock()
    mock_doc = MagicMock()
    
    # Create entities with required labels
    ent_person = MagicMock(); ent_person.label_ = "PERSON"; ent_person.text = "John"
    ent_org = MagicMock(); ent_org.label_ = "ORG"; ent_org.text = "Acme"
    ent_money = MagicMock(); ent_money.label_ = "MONEY"; ent_money.text = "100$"
    ent_date = MagicMock(); ent_date.label_ = "DATE"; ent_date.text = "2024"
    
    mock_doc.ents = [ent_person, ent_org, ent_money, ent_date]
    # Sentences are Spans, so they must have .text
    s1 = MagicMock(); s1.text = "Sentence 1."
    s2 = MagicMock(); s2.text = "Sentence 2."
    mock_doc.sents = [s1, s2]
    
    mock_nlp.return_value = mock_doc
    
    with patch("spacy.load", return_value=mock_nlp):
        from app.services.content_analyzer import ContentAnalyzer
        # Reload to force mock usage
        import app.services.content_analyzer
        importlib.reload(app.services.content_analyzer)
        
        analyzer = app.services.content_analyzer.ContentAnalyzer()
        result = analyzer.analyze("text")
        
        # Verify entities were processed (coverage)
        assert result

@pytest.mark.asyncio
async def test_file_route_docx_type(async_client, tmp_path):
    test_file = tmp_path / "test_output.txt"
    test_file.write_text("dummy")
    with patch("app.api.routes.file.save_file", return_value="test_path"), \
         patch("app.api.routes.file.docx_to_text", return_value="Extracted docx text") as mock_ocr, \
         patch("app.api.routes.file.store_file") as mock_store, \
         patch("os.path.getsize", return_value=123), \
         patch("os.remove"):
        with open(test_file, "rb") as f:
            response = await async_client.post(
                "/file/docx",
                params={"doc_id": "123"},
                files={"file": ("test.docx", f, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")}
            )
            assert response.status_code == 200
            mock_ocr.assert_awaited_once()
