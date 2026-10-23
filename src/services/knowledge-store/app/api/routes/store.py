import asyncio
import json

from fastapi import APIRouter, File, HTTPException, Query, UploadFile

from app.api.utils import docx_to_text, pdf_to_text, save_file
from app.chroma_db import (
    DocumentModel,
    SmartSearchRequest,
    build_where_clause,
    delete_document,
    query_knowledge,
    query_with_filters,
    store_file,
)
from app.chroma_db.services.corpus_version import current_corpus_version
from app.chroma_db.services.file_service import (
    Passage,
    document_category,
    document_where,
    passage_where,
    search_documents,
    stored_documents,
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
    description=(
        "Search for relevant passages using a query string with optional metadata filters. "
        "Each result is a passage of at most 1,000 characters: ids holds its chunk id "
        "({doc_id}:{n}), and its metadata carries doc_id, title, source_path, chunk_index, "
        "char_start, char_end, page (PDFs), category and embed_model. n_results counts "
        "passages, so one document can appear several times."
    ),
    responses={
        200: {
            "description": "Query successful",
            "content": {
                "application/json": {
                    "example": {
                        "ids": [["3f9a2c:4", "b71e09:0"]],
                        "distances": [[0.1, 0.2]],
                        "metadatas": [
                            [
                                {
                                    "doc_id": "3f9a2c",
                                    "title": "Doc 1.pdf",
                                    "chunk_index": 4,
                                    "char_start": 3200,
                                    "char_end": 4180,
                                    "page": 2,
                                    "source_path": "",
                                    "category": "finance",
                                    "embed_model": "fastembed-0.8.1:BAAI/bge-base-en-v1.5",
                                },
                                {
                                    "doc_id": "b71e09",
                                    "title": "Doc 2.md",
                                    "chunk_index": 0,
                                    "char_start": 0,
                                    "char_end": 950,
                                    "source_path": "policies/doc2.md",
                                    "category": "hr",
                                    "embed_model": "fastembed-0.8.1:BAAI/bge-base-en-v1.5",
                                },
                            ]
                        ],
                        "documents": [["Passage of Doc 1", "Passage of Doc 2"]],
                    }
                }
            },
        },
        404: {"description": "No results found"},
    },
)
async def query_knowledge_store(query: str, n_results: int = 1, filters: str | None = Query(None)):
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
    description=(
        "Remove a document from the knowledge store by its ID (or by the doc_id its "
        "entries carry), together with its uploaded file in documents/ and every other "
        "entry indexed from the same corpus path. A deleted corpus file goes on the "
        "deleted list, so a later POST /corpus/scan does not add it back."
    ),
    responses={
        200: {
            "description": "Document deleted successfully",
            "content": {
                "application/json": {
                    "example": {
                        "status": "Document deleted",
                        "deleted_ids": ["123456"],
                        "removed_files": ["pdf/report.pdf"],
                    }
                }
            },
        },
        404: {"description": "Document not found or deletion failed"},
    },
)
async def delete_document_store(id: str):
    """Delete a document from the knowledge store by ID."""
    logger.info(f"Request to delete document from store: {id}")
    try:
        outcome = await delete_document(id)
        logger.info(f"Document {id} deleted successfully: {outcome}")
    except Exception as e:
        logger.error(f"Failed to delete document {id}: {str(e)}")
        raise HTTPException(status_code=404, detail=str(e))

    return {**outcome, "status": "Document deleted"}


def _hit_columns(hits: list[Passage]) -> dict:
    return {
        "ids": [hit.doc_id for hit in hits],
        "chunk_ids": [hit.chunk_id for hit in hits],
        "documents": [hit.text for hit in hits],
        "metadatas": [hit.metadata for hit in hits],
        "distances": [hit.distance for hit in hits],
    }


@router.post(
    "/smart-search",
    summary="Search documents with filters",
    description=(
        "Semantic search that returns documents, not passages: each document appears once, "
        "with its best-matching passage. ids holds the document ids and chunk_ids the ids "
        "of those passages. categories filters passages; entities, min_confidence and "
        "entity_type filter on the document's analysis."
    ),
)
async def smart_search(request: SmartSearchRequest):
    try:
        hits = await search_documents(
            request.query,
            request.n_results,
            passage_where=passage_where(request),
            document_where=document_where(request),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail="Error performing smart search: " + str(e))

    if not hits:
        raise HTTPException(status_code=404, detail="No results found")

    return {
        "query": request.query,
        "filters": build_where_clause(request),
        "total": len(hits),
        "results": _hit_columns(hits),
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

    where_clause = {f"entities_{entity_type}": {"$contains": entity}}
    try:
        hits = await search_documents(entity, n_results, document_where=where_clause)
    except Exception as e:
        raise HTTPException(status_code=500, detail="Error searching by entity: " + str(e))

    if not hits:
        raise HTTPException(status_code=404, detail="No documents found for this entity")

    return {
        "entity": entity,
        "entity_type": entity_type,
        "filter": where_clause,
        "total": len(hits),
        "results": {key: [column] for key, column in _hit_columns(hits).items()},
    }


@router.get("/categories")
async def get_categories():
    """Get the list of categories available in the knowledge store with counts."""
    try:
        documents = stored_documents()
    except Exception as e:
        raise HTTPException(status_code=500, detail="Error retrieving categories: " + str(e))

    counts: dict[str, int] = {}
    for document in documents:
        category = document_category(document.metadata)
        counts[category] = counts.get(category, 0) + 1

    return {
        "total_documents": len(documents),
        "categories": [
            {"category": cat, "count": count}
            for cat, count in sorted(counts.items(), key=lambda x: x[1], reverse=True)
        ],
    }


@router.get(
    "/corpus-version",
    summary="Current corpus version",
    description=(
        "An opaque version of the indexed corpus. It changes on every upload, every delete, "
        "every corpus scan that adds or removes an entry, every document a re-index changes, "
        "and every restart of the service. "
        "The agent puts it in its response cache key, so a cached answer is never served "
        "after the corpus changed."
    ),
    responses={
        200: {
            "description": "Current corpus version",
            "content": {
                "application/json": {
                    "example": {
                        "version": "3f9a2c1e7b4d-12",
                        "changed_at": "2026-10-05T09:30:12.000000+00:00",
                    }
                }
            },
        }
    },
)
async def get_corpus_version():
    return current_corpus_version()


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
