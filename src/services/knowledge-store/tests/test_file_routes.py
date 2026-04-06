import pytest
import os
import uuid

@pytest.mark.asyncio
async def test_upload_multiple_files(async_client):
    filename1 = f"test_multi_1_{uuid.uuid4()}.txt"
    filename2 = f"test_multi_2_{uuid.uuid4()}.txt"
    
    files = [
        ("files", (filename1, b"Content 1", "text/plain")),
        ("files", (filename2, b"Content 2", "text/plain"))
    ]
    
    response = await async_client.post("/file", files=files)
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 2
    for item in data:
        assert "error" not in item, f"Upload failed with error: {item.get('error')}"
    assert data[0]["filename"] == filename1
    assert "doc_id" in data[0]

@pytest.mark.asyncio
async def test_get_all_files(async_client):
    response = await async_client.get("/file")
    assert response.status_code == 200
    data = response.json()
    assert "documents" in data
    assert isinstance(data["documents"], list)

@pytest.mark.asyncio
async def test_delete_file(async_client):
    # Ensure a file exists to delete
    filename = f"to_delete_{uuid.uuid4()}.txt"
    os.makedirs("documents", exist_ok=True)
    with open(f"documents/{filename}", "w") as f:
        f.write("delete me")
        
    response = await async_client.delete(f"/file/{filename}")
    assert response.status_code == 200
    assert response.json() == {"msg": f"{filename} deleted"}
    assert not os.path.exists(f"documents/{filename}")
    
    # Test delete non-existent
    response = await async_client.delete("/file/non_existent_file.txt")
    assert response.status_code == 404

from unittest.mock import patch, MagicMock

@pytest.mark.asyncio
async def test_upload_file_to_text_endpoint(async_client):
    # Mock save_file and pdf_to_text and store_file and getsize
    with patch("app.api.routes.file.save_file") as mock_save, \
         patch("app.api.routes.file.pdf_to_text") as mock_pdf, \
         patch("app.api.routes.file.store_file") as mock_store, \
         patch("os.path.getsize") as mock_size:
         
        mock_save.return_value = "/tmp/fake.pdf"
        mock_pdf.return_value = "Extracted Text"
        mock_size.return_value = 100
        
        filename = "test.pdf"
        files = {"file": (filename, b"dummy content", "application/pdf")}
        doc_id = str(uuid.uuid4())
        
        # Route expects path param {type} and query param doc_id? 
        # Code: @router.post('/{type}') async def upload_file_to_text(type: str, doc_id: str...)
        # doc_id is query param because it's not in path.
        
        response = await async_client.post(f"/file/pdf?doc_id={doc_id}", files=files)
        
        assert response.status_code == 200
        data = response.json()
        assert data["filename"] == filename
        assert data["text"] == "Extracted Text"
        assert data["stored_at"] == "/tmp/fake.pdf"
        
        mock_save.assert_called_once()
        mock_pdf.assert_called_once()
        mock_store.assert_called_once()

@pytest.mark.asyncio
async def test_upload_file_to_text_invalid_type(async_client):
    with patch("app.api.routes.file.save_file") as mock_save:
        mock_save.return_value = "/tmp/fake.xyz"
        
        filename = "test.xyz"
        files = {"file": (filename, b"content", "application/octet-stream")}
        doc_id = "123"
        
        response = await async_client.post(f"/file/unknown?doc_id={doc_id}", files=files)
        assert response.status_code == 400
        assert "Invalid file type" in response.json()["error"]



@pytest.mark.asyncio
async def test_upload_file_types_coverage(async_client):
    """Test PDF and DOCX upload paths"""
    with patch("app.api.routes.file.save_file") as mock_save,          patch("app.api.routes.file.pdf_to_text") as mock_pdf,          patch("app.api.routes.file.docx_to_text") as mock_docx,          patch("app.api.routes.file.store_file") as mock_store,          patch("os.path.getsize", return_value=123):
         
        mock_save.return_value = "/tmp/test"
        
        # Test PDF
        mock_pdf.return_value = "PDF Content"
        files = [("files", ("test.pdf", b"pdf content", "application/pdf"))]
        resp = await async_client.post("/file", files=files)
        assert resp.status_code == 200
        assert resp.json()[0]["filename"] == "test.pdf"
        mock_pdf.assert_called()
        
        # Test DOCX
        mock_docx.return_value = "DOCX Content"
        files = [("files", ("test.docx", b"docx content", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"))]
        resp = await async_client.post("/file", files=files)
        assert resp.status_code == 200
        assert resp.json()[0]["filename"] == "test.docx"
        mock_docx.assert_called()

@pytest.mark.asyncio
async def test_upload_file_exception(async_client):
    """Test exception handling in upload_file"""
    with patch("app.api.routes.file.save_file", side_effect=Exception("Upload Error")):
        files = [("files", ("test.txt", b"content", "text/plain"))]
        resp = await async_client.post("/file", files=files)
        assert resp.status_code == 200
        data = resp.json()
        assert "error" in data[0]
        assert data[0]["error"] == "Upload Error"

@pytest.mark.asyncio
async def test_get_all_files_exception(async_client):
    """Test exception handling in get_all_files"""
    with patch("app.api.routes.file.knowledge_collection.get", side_effect=Exception("DB Error")):
        resp = await async_client.get("/file")
        assert resp.status_code == 404
        assert "DB Error" in resp.json()["error"]

@pytest.mark.asyncio
async def test_upload_file_to_text_image(async_client):
    """Test 'image' type in upload_file_to_text"""
    with patch("app.api.routes.file.save_file") as mock_save,          patch("app.api.routes.file.image_pdf_to_text") as mock_ocr,          patch("app.api.routes.file.store_file"),          patch("os.path.getsize", return_value=50):
         
        mock_save.return_value = "/tmp/img.pdf"
        mock_ocr.return_value = "OCR Text"
        
        files = {"file": ("test.pdf", b"img", "application/pdf")}
        resp = await async_client.post("/file/image?doc_id=123", files=files)
        assert resp.status_code == 200
        assert resp.json()["text"] == "OCR Text"

