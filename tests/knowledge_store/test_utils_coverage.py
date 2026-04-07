
import pytest
from unittest.mock import MagicMock, patch
from app.api.utils import docx_to_text, image_pdf_to_text

@pytest.mark.asyncio
async def test_docx_to_text_with_tables():
    # Mock the Document object
    with patch("app.api.utils.Document") as MockDocument:
        mock_doc = MagicMock()
        MockDocument.return_value = mock_doc
        
        # Setup paragraphs
        mock_para1 = MagicMock()
        mock_para1.text = "Paragraph 1"
        mock_doc.paragraphs = [mock_para1]
        
        # Setup tables
        mock_table = MagicMock()
        mock_row = MagicMock()
        mock_cell1 = MagicMock()
        mock_cell1.text = "Cell 1"
        mock_cell2 = MagicMock()
        mock_cell2.text = "Cell 2"
        mock_row.cells = [mock_cell1, mock_cell2]
        mock_table.rows = [mock_row]
        mock_doc.tables = [mock_table]
        
        text = await docx_to_text("dummy.docx")
        
        assert "Paragraph 1" in text
        assert "Cell 1\tCell 2" in text

@pytest.mark.asyncio
async def test_image_pdf_to_text():
    # Mock convert_from_path and pytesseract.image_to_string
    with patch("app.api.utils.convert_from_path") as mock_convert, \
         patch("app.api.utils.pytesseract.image_to_string") as mock_ocr:
         
        mock_convert.return_value = ["img1", "img2"]
        mock_ocr.side_effect = ["Page 1 Text", "Page 2 Text"]
        
        text = await image_pdf_to_text("dummy.pdf")
        
        assert "Page 1 Text" in text
        assert "Page 2 Text" in text
