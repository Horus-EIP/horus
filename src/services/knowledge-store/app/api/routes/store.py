from fastapi import APIRouter, HTTPException, Request
from app.chroma_db import DocumentModel, store_file, delete_document, query_knowledge
from fastapi.responses import RedirectResponse

router = APIRouter()

@router.post("/")
async def add_text(doc: DocumentModel):
    """
    Add a text to the knowledge store.

    Parameters:

            doc (DocumentModel): The document to add to the knowledge store.

    Returns:
    
            status (str): The status of the operation.
            id (str): The id of the document added.
    """
    await store_file(doc)

    return {"status": "document added", "id": doc.id}

@router.get("/")
async def query_knowledge_store(query: str, n_results: int = 1):
    """
    Query the knowledge store with a query string to retrieve relevant documents.

    Parameters:

            query (str): The query string to search for relevant documents.
            n_results (int): The number of results to return.

    Returns:
    
            results (dict): The results of the query.
    """
    print("CHECKING")
    try:
        results = await query_knowledge(query, n_results)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    print(results)

    if not results['documents'][0]:
        raise HTTPException(status_code=404, detail="No results found")
    
    return results

@router.delete("/{id}")
async def delete_document_store(id: str):
    """
    Delete a document from the knowledge store.
    
    Parameters:

            id (str): The id of the document to delete.

    Returns:

            status (str): The status of the operation.
    """
    try:
        await delete_document(id)
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))

    return {"status": "Document deleted"}
