import asyncio
import os
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import UploadFile

from app.api.utils import docx_to_text, image_pdf_pages, pdf_pages, pdf_to_text, save_file


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

class SlowPdf:
    def __init__(self, release, waits, texts):
        self.release, self.waits, self.texts = release, waits, texts

    def __enter__(self):
        self.waits.append(self.release.wait(timeout=2))
        pages = []
        for text in self.texts:
            page = MagicMock()
            page.extract_text.return_value = text
            pages.append(page)
        return SimpleNamespace(pages=pages)

    def __exit__(self, *_exc):
        return False


async def extract_while_another_request_runs(extract, release):
    async def another_request():
        release.set()

    result, _ = await asyncio.gather(extract("big.pdf"), another_request())
    return result


@pytest.mark.asyncio
async def test_pdf_pages_are_read_while_other_requests_run():
    release, waits = threading.Event(), []
    with patch("app.api.utils.pdfplumber") as mock_pdfplumber:
        mock_pdfplumber.open.return_value = SlowPdf(release, waits, ["first", None, "third"])
        pages = await extract_while_another_request_runs(pdf_pages, release)

    assert waits == [True]
    assert pages == ["first", "", "third"]


@pytest.mark.asyncio
async def test_pdf_text_is_read_while_other_requests_run():
    release, waits = threading.Event(), []
    with patch("app.api.utils.pdfplumber") as mock_pdfplumber:
        mock_pdfplumber.open.return_value = SlowPdf(release, waits, ["first", "second"])
        text = await extract_while_another_request_runs(pdf_to_text, release)

    assert waits == [True]
    assert text == "first\nsecond\n"


@pytest.mark.asyncio
async def test_scanned_pages_are_read_while_other_requests_run():
    release, waits = threading.Event(), []

    def slow_conversion(_filepath):
        waits.append(release.wait(timeout=2))
        return ["image-1", "image-2"]

    with (
        patch("app.api.utils.convert_from_path", side_effect=slow_conversion),
        patch("app.api.utils.pytesseract") as mock_tesseract,
    ):
        mock_tesseract.image_to_string.side_effect = lambda image: f"ocr of {image}"
        pages = await extract_while_another_request_runs(image_pdf_pages, release)

    assert waits == [True]
    assert pages == ["ocr of image-1", "ocr of image-2"]


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
