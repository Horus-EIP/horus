from fastapi import APIRouter, HTTPException, File, UploadFile
from app.api.utils import pdf_to_text, save_file, image_pdf_to_text, docx_to_text
from app.chroma_db import store_file, DocumentModel, knowledge_collection
from typing import List
import os
import uuid
import datetime

router = APIRouter()

@router.post('', tags=['file'])
async def upload_file(files: List[UploadFile] = File(...)):
    """
    Upload a file to the documents folder.

    Parameters:
    
            file (UploadFile): The file to upload to the knowledge store.

    Returns:
        
            filename (str): The name of the uploaded file.
            stored_at (str): The path where the file is stored.
    """
    responses = []

    for file in files:
        try:
            doc_id = uuid.uuid4().hex
            type = file.filename.split('.')[-1]
            doc_path = await save_file(file, type)

            if type == 'pdf':
                text = await pdf_to_text(doc_path)
            elif type == 'docx':
                text = await docx_to_text(doc_path)
            elif type == 'txt':
                with open(doc_path, 'r') as f:
                    text = f.read()

            await store_file(DocumentModel(
                id=doc_id,
                title=file.filename,
                content=text,
                size=os.path.getsize(doc_path)
            ))

            responses.append({'filename': file.filename, 'doc_id': doc_id, 'stored_at': doc_path})
        except Exception as e:
            responses.append({'filename': file.filename, 'error': str(e)})

    return responses

@router.get('', tags=['file'])
async def get_all_files():
    """
    Get all files in the knowledge store.

    Returns:
        
            files (List[str]): A list of all files in the knowledge store.
    """
    try:
        stored_files = knowledge_collection.get(include=["documents", "metadatas"])
        
        files = [
            {
                'id': doc_id,
                'title': meta.get('title', 'Untitled'),
                'content': doc_content,
                'date': meta.get('date', 'Unknown'),
                'size': meta.get('size', 0)
            }
            for doc_id, doc_content, meta in zip(
                stored_files['ids'],
                stored_files['documents'],
                stored_files['metadatas']
            )
        ]

        return {'documents': files}
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))

@router.delete('/{filename}', tags=['file'])
async def delete_file(filepath: str):
    """
    Delete a file from the knowledge store.

    Parameters:
    
            filename (str): The name of the file to delete.

    Returns:
        
            msg (str): The message indicating the file was deleted.
    """
    path = os.path.join('documents', filepath)
    if os.path.exists(path):
        os.remove(path)
        return {"msg": f'{filepath} deleted'}
    else:
        raise HTTPException(status_code=404, detail="File not found")

@router.post('/{type}', tags=['file'])
async def upload_file_to_text(type: str, doc_id: str, file: UploadFile = File(...)):
    """
    Upload a file to the knowledge store and convert it to text.

    Parameters:
        
            type (str): The type of file to upload. Can be 'pdf', 'docx' or 'image'.
            doc_id (str): The id of the document to upload
            file (UploadFile): The file to upload to the knowledge store.
            
    Returns:
        
            filename (str): The filename of the uploaded file.
            stored_at (str): The path where the file is stored.
            text (str): The text extracted from the file
    """
    path = await save_file(file, type)

    if type == 'pdf':
        text = await pdf_to_text(path)
    elif type == 'docx':
        text = await docx_to_text(path)
    elif type == 'image':
        text = await image_pdf_to_text(path)
    else:
        raise HTTPException(status_code=400, detail="Invalid file type")

    await store_file(DocumentModel(
        id=doc_id,
        title=file.filename,
        content=text
    ))
    return {'filename': file.filename, 'stored_at': path, 'text': text}
