"""File management routes — upload, list, delete, and type-aware conversion.

Handles PDF, DOCX, TXT, and image-based PDFs. OpenAPI descriptions per
endpoint live alongside the route decorators.
"""

import asyncio
import os
import uuid
from typing import NamedTuple

from fastapi import APIRouter, File, HTTPException, Query, UploadFile

from app.api.utils import docx_to_text, image_pdf_pages, pdf_pages, save_file
from app.chroma_db import DocumentModel, store_file
from app.chroma_db.services.file_service import (
    StoredDocument,
    document_category,
    document_texts,
    entry_texts,
    stored_documents,
)
from app.core.logging import get_logger
from app.core.metrics import record_document_operation
from app.services.content_analyzer import ContentAnalyzer

router = APIRouter(tags=["File"])
logger = get_logger("FileRouter")

_content_analyzer = ContentAnalyzer()

LIST_EXCERPT_MAX_CHARS = 400


class ExtractedText(NamedTuple):
    text: str
    page_starts: tuple[int, ...] = ()


def pages_to_text(pages: list[str], trailing_newline: bool = True) -> ExtractedText:
    starts: list[int] = []
    offset = 0
    for page in pages:
        starts.append(offset)
        offset += len(page) + 1
    text = "\n".join(pages) + ("\n" if trailing_newline and pages else "")
    return ExtractedText(text, tuple(starts))


async def extract_document(path: str, ext: str) -> ExtractedText:
    kind = (ext or "").lower().lstrip(".")
    if kind == "pdf":
        return pages_to_text(await pdf_pages(path))
    if kind == "docx":
        return ExtractedText(await docx_to_text(path))
    with open(path, encoding="utf-8", errors="ignore") as handle:
        return ExtractedText(handle.read())


def _match_stored_title(requested: str, stored_title: str) -> bool:
    """
    True if the user-supplied name refers to this stored document title.

    Matches full title, basename, or same stem (e.g. ``report`` vs ``report.pdf``).
    """
    r = (requested or "").strip().lower()
    s = (stored_title or "").strip().lower()
    if not r or not s:
        return False
    s_base = os.path.basename(s)
    r_base = os.path.basename(r)
    if s == r or s_base == r_base:
        return True
    s_stem = os.path.splitext(s_base)[0]
    r_stem = os.path.splitext(r_base)[0]
    return bool(s_stem and r_stem and s_stem == r_stem)


@router.get(
    "/resolve",
    summary="Resolve document by filename",
    description=(
        "Return full indexed text for stored document(s) whose title matches the given "
        "filename or basename (case-insensitive). Used by agents when the user names a file. "
        "`documents` gives each matched document's id, title and text apart, so an answer "
        "can cite the one it used."
    ),
    responses={
        200: {
            "description": "Matched document(s)",
            "content": {
                "application/json": {
                    "example": {
                        "name": "notes.txt",
                        "matched_titles": ["notes.txt"],
                        "doc_ids": ["abc123"],
                        "text": "Full document body...",
                        "documents": [
                            {
                                "doc_id": "abc123",
                                "title": "notes.txt",
                                "text": "Full document body...",
                            }
                        ],
                    }
                }
            },
        },
        404: {"description": "No document matched that name"},
    },
)
async def resolve_document_by_name(
    name: str = Query(
        ...,
        min_length=1,
        description="Filename or basename as stored in the knowledge store (e.g. report.pdf)",
    ),
):
    try:
        matched = [
            document.doc_id
            for document in stored_documents()
            if _match_stored_title(name, document.metadata.get("title") or "Untitled")
        ]
        texts = document_texts(matched)
    except Exception as e:
        logger.error("resolve_document_by_name: get failed: %s", e)
        record_document_operation("get", success=False)
        raise HTTPException(status_code=404, detail=str(e))

    found = [texts[doc_id] for doc_id in matched if doc_id in texts]
    record_document_operation("get", success=bool(found))
    if not found:
        raise HTTPException(
            status_code=404,
            detail=f"No indexed document matched name={name!r}",
        )

    return {
        "name": name.strip(),
        "matched_titles": [document.title for document in found],
        "doc_ids": [document.doc_id for document in found],
        "text": "\n\n---\n\n".join(document.text for document in found),
        "documents": [
            {"doc_id": document.doc_id, "title": document.title, "text": document.text}
            for document in found
        ],
    }


@router.get(
    "/{doc_id}/text",
    summary="Full text of one document",
    description=(
        "Return the full indexed text of one document, rebuilt from its passages, by its "
        "document id. Used by agents to read an attached file by the id the UI sent."
    ),
    responses={
        200: {
            "description": "The document's full text",
            "content": {
                "application/json": {
                    "example": {
                        "doc_id": "abc123",
                        "title": "notes.txt",
                        "category": "general",
                        "chunk_count": 3,
                        "text": "Full document body...",
                    }
                }
            },
        },
        404: {"description": "No document with that id"},
        500: {"description": "The index could not be read"},
    },
)
async def get_document_text(doc_id: str):
    try:
        found = document_texts([doc_id]).get(doc_id)
    except Exception as e:
        logger.error("get_document_text: get failed for %s: %s", doc_id, e)
        record_document_operation("get", success=False)
        raise HTTPException(status_code=500, detail=str(e))
    record_document_operation("get", success=found is not None)
    if found is None:
        raise HTTPException(status_code=404, detail=f"No document with id {doc_id!r}")
    return {
        "doc_id": found.doc_id,
        "title": found.title,
        "category": document_category(found.metadata),
        "chunk_count": found.chunk_count,
        "text": found.text,
    }


@router.post(
    "",
    summary="Upload files",
    description="Upload multiple files to the knowledge store. Supports PDF, DOCX, and TXT.",
    responses={
        200: {
            "description": "Files processed successfully",
            "content": {
                "application/json": {
                    "example": [
                        {"filename": "doc.pdf", "doc_id": "123", "stored_at": "/path/to/doc.pdf"}
                    ]
                }
            },
        }
    },
)
async def upload_file(files: list[UploadFile] = File(...)):
    """
    Upload multiple files to the documents folder, analyze, and index them.

    Args:
        files: List of files to upload.

    Returns:
        List of results with filenames, IDs, paths, and auto-analysis.
    """
    responses = []
    logger.info(f"Received request to upload {len(files)} files.")

    for file in files:
        try:
            doc_id = uuid.uuid4().hex
            logger.info(f"Processing file: {file.filename}, generated ID: {doc_id}")
            file_ext = file.filename.split(".")[-1].lower()
            doc_path = await save_file(file, file_ext)

            extracted = await extract_document(doc_path, file_ext)

            auto_analysis = await asyncio.to_thread(
                _content_analyzer.analyze,
                extracted.text,
                file.filename,
            )

            await store_file(
                DocumentModel(
                    id=doc_id,
                    title=file.filename,
                    content=extracted.text,
                    size=os.path.getsize(doc_path),
                ),
                auto_analysis=auto_analysis,
                extra_metadata={"stored_path": doc_path},
                page_starts=extracted.page_starts,
            )

            logger.info(f"File {file.filename} stored successfully with ID {doc_id}")
            responses.append(
                {
                    "filename": file.filename,
                    "doc_id": doc_id,
                    "stored_at": doc_path,
                    "auto_analysis": auto_analysis,
                }
            )

        except Exception as e:
            logger.error(f"Error processing file {file.filename}: {str(e)}")
            responses.append({"filename": file.filename, "error": str(e)})

    return responses


def _listed(document: StoredDocument, text: str) -> dict:
    meta = document.metadata
    try:
        size = int(meta.get("size", 0))
    except (TypeError, ValueError):
        size = 0
    excerpt = text[:LIST_EXCERPT_MAX_CHARS].strip()
    if len(text) > LIST_EXCERPT_MAX_CHARS:
        excerpt = f"{excerpt}..."
    auto_summary = (meta.get("auto_summary") or "").strip()
    conf = meta.get("confidence_score")
    try:
        confidence = float(conf) if conf is not None and conf != "" else None
    except (TypeError, ValueError):
        confidence = None
    return {
        "id": document.doc_id,
        "title": meta.get("title") or "Untitled",
        "date": meta.get("date") or "Unknown",
        "size": size,
        "summary": auto_summary or excerpt or "(no text extracted)",
        "excerpt": excerpt,
        "category": document_category(meta),
        "document_type": (meta.get("auto_type") or "").strip() or "unknown",
        **({"confidence_score": confidence} if confidence is not None else {}),
        **({"chunk_count": chunks} if isinstance(chunks := meta.get("chunk_count"), int) else {}),
    }


@router.get(
    "",
    summary="List all files",
    description=(
        "Retrieve a list of all documents currently indexed in the knowledge store, one "
        "entry per document however many passages it was split into."
    ),
    responses={
        200: {
            "description": "List of documents",
            "content": {
                "application/json": {
                    "example": {
                        "documents": [
                            {
                                "id": "123",
                                "title": "doc.pdf",
                                "date": "2023-01-01",
                                "size": 1024,
                                "summary": "Auto-generated summary of the document.",
                                "excerpt": "First lines of extracted text...",
                                "category": "general",
                                "document_type": "unknown",
                            }
                        ]
                    }
                }
            },
        },
        404: {"description": "Error retrieving files"},
    },
)
async def get_all_files():
    """Get all files in the knowledge store (metadata + summary; not full body)."""
    try:
        documents = stored_documents()
        texts = entry_texts(document.head_id for document in documents)
        return {
            "documents": [
                _listed(document, texts.get(document.head_id, "")) for document in documents
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete(
    "/{filename}",
    summary="Delete a file",
    description="Delete a file from the physical storage by its filename.",
    responses={
        200: {
            "description": "File deleted",
            "content": {"application/json": {"example": {"msg": "doc.pdf deleted"}}},
        },
        404: {"description": "File not found"},
    },
)
async def delete_file(filename: str):
    """Delete a file from the knowledge store storage."""
    logger.info(f"Request to delete file: {filename}")
    file_path = None
    for root, dirs, files in os.walk("documents"):
        if filename in files:
            file_path = os.path.join(root, filename)
            break

    if file_path:
        os.remove(file_path)
        logger.info(f"File {filename} deleted successfully from disk.")
        return {"msg": f"{filename} deleted"}
    else:
        logger.warning(f"File {filename} not found for deletion.")
        raise HTTPException(status_code=404, detail="File not found")


@router.post(
    "/{type}",
    summary="Upload and Convert Specific Type",
    description="Upload a single file specifying its type (pdf, docx, image) and document ID, then convert to text.",
    responses={
        200: {
            "description": "File uploaded and converted",
            "content": {
                "application/json": {
                    "example": {
                        "filename": "doc.pdf",
                        "stored_at": "/path/doc.pdf",
                        "text": "Extracted text",
                    }
                }
            },
        },
        400: {"description": "Invalid file type"},
    },
)
async def upload_file_to_text(type: str, doc_id: str, file: UploadFile = File(...)):
    """
    Upload a single file, convert it to text, analyze, and store it.

    Args:
        type: File type ('pdf', 'docx', 'image').
        doc_id: Pre-assigned document ID.
        file: The file to upload.

    Returns:
        Filename, storage path, extracted text, and auto-analysis.
    """
    path = await save_file(file, type)

    if type == "pdf":
        extracted = pages_to_text(await pdf_pages(path))
    elif type == "docx":
        extracted = ExtractedText(await docx_to_text(path))
    elif type == "image":
        extracted = pages_to_text(await image_pdf_pages(path), trailing_newline=False)
    else:
        raise HTTPException(status_code=400, detail="Invalid file type")

    auto_analysis = await asyncio.to_thread(
        _content_analyzer.analyze,
        extracted.text,
        file.filename,
    )

    await store_file(
        DocumentModel(
            id=doc_id,
            title=file.filename,
            content=extracted.text,
            size=os.path.getsize(path) if os.path.exists(path) else 0,
        ),
        auto_analysis=auto_analysis,
        extra_metadata={"stored_path": path},
        page_starts=extracted.page_starts,
    )

    return {
        "filename": file.filename,
        "stored_at": path,
        "text": extracted.text,
        "auto_analysis": auto_analysis,
    }
