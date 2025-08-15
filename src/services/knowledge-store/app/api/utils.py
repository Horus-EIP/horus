from fastapi import UploadFile
import shutil
import os
import pdfplumber
import pytesseract
from pdf2image import convert_from_path
from docx import Document

async def docx_to_text(filepath: str):
    """
    Convert a .docx file to text.

    Parameters:
    
            filepath (str): The path to the DOCX file.

    Returns:
        
            text (str): The text extracted from the DOCX file.
    """
    doc = Document(filepath)
    text = []
    for paragraph in doc.paragraphs:
        text.append(paragraph.text)
    
    for table in doc.tables:
        for row in table.rows:
            row_text = [cell.text for cell in row.cells]
            text.append('\t'.join(row_text))

    return '\n'.join(text)

async def image_pdf_to_text(filepath: str):
    """
    Convert a PDF file to text using OCR.

    Parameters:
    
            filepath (str): The path to the PDF file.

    Returns:
        
            text (str): The text extracted from the PDF file.
    """
    images = convert_from_path(filepath)
    text = '\n'.join([pytesseract.image_to_string(img) for img in images])

    return text

async def pdf_to_text(filepath: str):
    """
    Convert a PDF file to text.

    Parameters:
    
            filepath (str): The path to the PDF file.

    Returns:
        
            text (str): The text extracted from the PDF file.
    """
    text = ''
    with pdfplumber.open(filepath) as pdf:
        for page in pdf.pages:
            text += page.extract_text() + '\n'
    return text

async def save_file(file: UploadFile, dir_name: str):
    """
    Save a file to a specified path.

    Parameters:
    
            file (UploadFile): The file to save.
            dir_name (str): The directory to save the file in.

    Returns:
        
            path (str): The path where the file is saved
    """
    path = os.path.join('documents/', dir_name, file.filename)
    with open(path, 'wb') as buffer:
        shutil.copyfileobj(file.file, buffer)
    return path
