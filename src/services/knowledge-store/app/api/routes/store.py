import asyncio
import json

from fastapi import APIRouter, File, HTTPException, Query, UploadFile

from app.api.utils import docx_to_text, pdf_to_text, save_file
from app.chroma_db import (
    DocumentModel,
    SmartSearchRequest,
    build_where_clause,
    delete_document,
    knowledge_collection,
    query_knowledge,
    query_with_filters,
    store_file,
)
from app.core.logging import get_logger
from app.services.content_analyzer import ContentAnalyzer
from app.services.document_chunker import DocumentChunker

router = APIRouter(tags=["Store"])
logger = get_logger("StoreRouter")

_content_analyzer = ContentAnalyzer()
_document_chunker = DocumentChunker()


@router.post(
    "/",
    summary="Add a text document",
    description="Add a plain text document to the knowledge store with automatic content analysis.",
    responses={
        200: {
            "description": "Document added successfully",
            "content": {
                "application/json": {
                    "example": {"status": "document added", "id": "123456", "auto_analysis": {}}
                }
            },
        }
    },
)
async def add_text(doc: DocumentModel):
    """
    Add a text document to the knowledge store.

    Runs auto-analysis (category, entities, topics, summary) and stores the
    document with its metadata.
    """
    logger.info(f"Adding new text document: {doc.title} (ID: {doc.id}, Size: {doc.size})")

    auto_analysis = await asyncio.to_thread(
        _content_analyzer.analyze,
        doc.content,
        doc.title,
    )
    await store_file(doc, auto_analysis=auto_analysis)

    logger.info(f"Document {doc.id} added successfully.")
    return {
        "status": "document added",
        "id": doc.id,
        "auto_analysis": auto_analysis,
    }


@router.get(
    "/",
    summary="Query the knowledge store",
    description="Search for relevant documents using a query string with optional metadata filters.",
    responses={
        200: {
            "description": "Query successful",
            "content": {
                "application/json": {
                    "example": {
                        "ids": [["id1", "id2"]],
                        "distances": [[0.1, 0.2]],
                        "metadatas": [[{"title": "Doc 1"}, {"title": "Doc 2"}]],
                        "documents": [["Content 1", "Content 2"]],
                    }
                }
            },
        },
        404: {"description": "No results found"},
    },
)
async def query_knowledge_store(
    query: str, n_results: int = 1, filters: str | None = Query(None)
):
    """
    Query the knowledge store with optional JSON metadata filters.

    Args:
        query: The search query text.
        n_results: Number of results to return (default: 1).
        filters: Optional JSON string with ChromaDB where-clause filters.
    """
    logger.info(f"Querying knowledge store: '{query}' (limit={n_results})")

    filters_dict = None
    if filters:
        try:
            filters_dict = json.loads(filters)
        except json.JSONDecodeError:
            raise HTTPException(
                status_code=400,
                detail="Invalid filters format. Must be a valid JSON string.",
            )

    try:
        if filters_dict is not None:
            results = await query_with_filters(query, filters_dict, n_results)
        else:
            results = await query_knowledge(query, n_results)
    except Exception as e:
        logger.error(f"Query failed: {str(e)}")
        raise HTTPException(status_code=500, detail="Error querying knowledge store: " + str(e))

    documents = results.get("documents")
    if not documents or not isinstance(documents, list) or not documents[0]:
        raise HTTPException(status_code=404, detail="No results found")

    result_count = len(documents[0])
    logger.info(f"Query returned {result_count} results.")
    return results


@router.delete(
    "/{id}",
    summary="Delete a document",
    description="Remove a document from the knowledge store by its ID.",
    responses={
        200: {
            "description": "Document deleted successfully",
            "content": {"application/json": {"example": {"status": "Document deleted"}}},
        },
        404: {"description": "Document not found or deletion failed"},
    },
)
async def delete_document_store(id: str):
    """Delete a document from the knowledge store by ID."""
    logger.info(f"Request to delete document from store: {id}")
    try:
        await delete_document(id)
        logger.info(f"Document {id} deleted successfully.")
    except Exception as e:
        logger.error(f"Failed to delete document {id}: {str(e)}")
        raise HTTPException(status_code=404, detail=str(e))

    return {"status": "Document deleted"}


@router.post("/smart-search")
async def smart_search(request: SmartSearchRequest):
    """
    Perform a smart search with metadata filters (category, entities, confidence).
    """
    where_clause = build_where_clause(request)

    try:
        if where_clause:
            results = await query_with_filters(request.query, where_clause, request.n_results)
        else:
            results = await query_knowledge(request.query, request.n_results)
    except Exception as e:
        raise HTTPException(status_code=500, detail="Error performing smart search: " + str(e))

    documents = results.get("documents", [[]])[0]
    metadatas = results.get("metadatas", [[]])[0]
    distances = results.get("distances", [[]])[0]

    if not documents:
        raise HTTPException(status_code=404, detail="No results found")

    filtered = list(zip(documents, metadatas, distances, strict=False))

    if not filtered:
        raise HTTPException(status_code=404, detail="No results found within distance threshold")

    filtered_docs, filtered_metas, filtered_dists = zip(*filtered, strict=False)
    return {
        "query": request.query,
        "filters": where_clause,
        "total": len(filtered_docs),
        "results": {
            "documents": filtered_docs,
            "metadatas": filtered_metas,
            "distances": filtered_dists,
        },
    }


@router.get("/search-by-entity")
async def search_by_entity(entity: str, entity_type: str, n_results: int = 5):
    """Search for documents containing a specific entity."""
    VALID_ENTITY_TYPES = {"people", "companies", "amounts", "dates"}
    if entity_type not in VALID_ENTITY_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid entity_type. Must be one of: {', '.join(VALID_ENTITY_TYPES)}",
        )

    try:
        metadata_field = f"entities_{entity_type}"
        where_clause = {metadata_field: {"$contains": entity}}
        results = await query_with_filters(entity, where_clause, n_results)
    except Exception as e:
        raise HTTPException(status_code=500, detail="Error searching by entity: " + str(e))

    documents = results.get("documents", [[]])[0]
    if not documents:
        raise HTTPException(status_code=404, detail="No documents found for this entity")

    return {
        "entity": entity,
        "entity_type": entity_type,
        "filter": where_clause,
        "total": len(documents),
        "results": results,
    }


@router.get("/categories")
async def get_categories():
    """Get the list of categories available in the knowledge store with counts."""
    try:
        results = knowledge_collection.get(include=["metadatas"])
        metadatas = results.get("metadatas", [])

        if not metadatas:
            return {"total_documents": 0, "categories": []}

        counts: dict = {}
        for meta in metadatas:
            category = ((meta or {}).get("auto_category") or "").strip() or "general"
            counts[category] = counts.get(category, 0) + 1

        categories = [
            {"category": cat, "count": count}
            for cat, count in sorted(counts.items(), key=lambda x: x[1], reverse=True)
        ]

        return {
            "total_documents": len(metadatas),
            "categories": categories,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail="Error retrieving categories: " + str(e))


@router.post(
    "/upload",
    summary="Upload, Analyze, and Chunk File",
    description="Upload a file (PDF, DOCX, TXT), extract its text, analyze contents, and chunk it for storage.",
    responses={
        200: {
            "description": "File processed successfully",
            "content": {
                "application/json": {
                    "example": {
                        "filename": "example.pdf",
                        "auto_analysis": {"topics": ["AI", "Tech"], "summary": "An example doc."},
                        "chunks": ["Chunk 1 content", "Chunk 2 content"],
                        "total_chunks": 2,
                    }
                }
            },
        },
        400: {"description": "Processing error"},
    },
)
async def upload_file(file: UploadFile = File(...)):
    """Upload a file, extract text, auto-analyze, and chunk it."""
    logger.info(f"Processing upload for file {file.filename}")
    try:
        file_ext = file.filename.split(".")[-1].lower()
        doc_path = await save_file(file, file_ext)

        if file_ext == "pdf":
            text = await pdf_to_text(doc_path)
        elif file_ext == "docx":
            text = await docx_to_text(doc_path)
        elif file_ext == "txt":
            with open(doc_path) as f:
                text = f.read()
        else:
            with open(doc_path, encoding="utf-8", errors="ignore") as f:
                text = f.read()

        logger.info(f"Text extracted from {file.filename}, length: {len(text)} chars.")
    except Exception as e:
        logger.error(f"Error processing file {file.filename}: {str(e)}")
        raise HTTPException(status_code=400, detail=f"Processing error: {e}")

    analysis = _content_analyzer.analyze(text, title=file.filename)
    chunks = _document_chunker.chunk_document(text)

    logger.info(f"Analysis complete. Generated {len(chunks)} chunks.")

    return {
        "filename": file.filename,
        "auto_analysis": analysis,
        "chunks": chunks,
        "total_chunks": len(chunks),
    }
