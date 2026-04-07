import pytest
import os
from unittest.mock import MagicMock, patch
from fastapi import UploadFile
from app.api.utils import save_file, pdf_to_text, docx_to_text

@pytest.mark.asyncio
async def test_save_file(tmp_path):
    # Mock UploadFile
    content = b"test content"
    filename = "test_file.txt"
    
    # We need to mock the file attribute of UploadFile to be a file-like object
    # OR we use a real file opened in binary mode.
    # But UploadFile logic is specific to FastAPI/Starlette, using tempfile usually.
    
    # Let's create a dummy UploadFile object
    mock_file = MagicMock(spec=UploadFile)
    mock_file.filename = filename
    mock_file.file = MagicMock()
    
    # Configure read/write side effects if needed, but shutil.copyfileobj uses .read()
    # mock_file.file.read.return_value = content 
    # copyfileobj calls read on source and write on dest.
    
    # Since shutil.copyfileobj takes a file-like object, let's use IoBytes
    from io import BytesIO
    mock_file.file = BytesIO(content)
    
    # We need to patch os.path.join or ensure the directory exists
    # The utils.py has 'documents/', dir_name, filename
    # We should patch open or redirect 'documents/' to tmp_path
    
    with patch("app.api.utils.open", create=True) as mock_open:
        # We also need os.path.join to behave or we mock it?
        # The code does: path = os.path.join('documents/', dir_name, file.filename)
        # If we run this test, it will try to write to actual file system relative to cwd.
        # Better to mock open so we don't write changes.
        
        mock_file_handle = MagicMock()
        mock_open.return_value.__enter__.return_value = mock_file_handle
        
        saved_path = await save_file(mock_file, "test_dir")
        
        expected_path = os.path.join('documents/', "test_dir", filename)
        assert saved_path == expected_path
        # Verification of copy logic is hidden in shutil.copyfileobj which writes to mock_file_handle
        # We assume shutil works if called.

@pytest.mark.asyncio
async def test_pdf_to_text():
    with patch("app.api.utils.pdfplumber") as mock_pdfplumber:
        mock_pdf = MagicMock()
        mock_page = MagicMock()
        mock_page.extract_text.return_value = "Page text"
        mock_pdf.pages = [mock_page]
        
        mock_pdfplumber.open.return_value.__enter__.return_value = mock_pdf
        
        text = await pdf_to_text("dummy.pdf")
        assert "Page text" in text

@pytest.mark.asyncio
async def test_docx_to_text():
    with patch("app.api.utils.Document") as mock_document_cls:
        mock_doc = MagicMock()
        
        p1 = MagicMock()
        p1.text = "Paragraph 1"
        
        mock_doc.paragraphs = [p1]
        mock_doc.tables = []
        
        mock_document_cls.return_value = mock_doc
        
        text = await docx_to_text("dummy.docx")
        assert "Paragraph 1" in text
