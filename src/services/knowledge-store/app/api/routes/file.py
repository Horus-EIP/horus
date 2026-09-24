"""File management routes — upload, list, delete, and type-aware conversion.

Handles PDF, DOCX, TXT, and image-based PDFs. OpenAPI descriptions per
endpoint live alongside the route decorators.
"""

import asyncio
import os
import uuid

from fastapi import APIRouter, File, HTTPException, Query, UploadFile

from app.api.utils import docx_to_text, image_pdf_to_text, pdf_to_text, save_file
from app.chroma_db import DocumentModel, knowledge_collection, store_file
from app.core.logging import get_logger
from app.services.content_analyzer import ContentAnalyzer

router = APIRouter(tags=["File"])
logger = get_logger("FileRouter")

_content_analyzer = ContentAnalyzer()


async def extract_text(path: str, ext: str) -> str:
    """Turn a file on disk into plain text. The one extraction path in the service.

    Lives here rather than in ``app.api.utils`` on purpose: it resolves
    ``pdf_to_text`` / ``docx_to_text`` through *this* module's globals, which is
    where the existing route tests patch them. The corpus scanner imports it from
    here so an upload and a corpus ingest can never drift apart.

    ``ext`` may carry a leading dot or not.

    Anything that is not PDF or DOCX is read as UTF-8 with undecodable bytes
    dropped. That was already the fallback branch's behaviour; the old dedicated
    ``txt`` branch used the process default encoding, which raises on a perfectly
    good UTF-8 file whenever the container locale is not UTF-8.
    """
    kind = (ext or "").lower().lstrip(".")
    if kind == "pdf":
        return await pdf_to_text(path)
    if kind == "docx":
        return await docx_to_text(path)
    with open(path, encoding="utf-8", errors="ignore") as handle:
        return handle.read()


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
        "filename or basename (case-insensitive). Used by agents when the user names a file."
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
    """Return full text for stored document(s) matching ``name``."""
    try:
        stored = knowledge_collection.get(include=["documents", "metadatas", "ids"])
    except Exception as e:
        logger.error("resolve_document_by_name: get failed: %s", e)
        raise HTTPException(status_code=404, detail=str(e))

    ids = stored.get("ids") or []
    documents = stored.get("documents") or []
    metadatas = stored.get("metadatas") or []

    matched_ids: list[str] = []
    matched_titles: list[str] = []
    parts: list[str] = []

    for doc_id, doc_content, meta in zip(ids, documents, metadatas, strict=False):
        meta = meta or {}
        title = meta.get("title") or "Untitled"
        if not _match_stored_title(name, title):
            continue
        matched_ids.append(str(doc_id))
        matched_titles.append(title)
        text = (doc_content or "") if isinstance(doc_content, str) else str(doc_content or "")
        parts.append(text)

    if not parts:
        raise HTTPException(
            status_code=404,
            detail=f"No indexed document matched name={name!r}",
        )

    combined = "\n\n---\n\n".join(parts)
    return {
        "name": name.strip(),
        "matched_titles": matched_titles,
        "doc_ids": matched_ids,
        "text": combined,
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

            text = await extract_text(doc_path, file_ext)

            auto_analysis = await asyncio.to_thread(
                _content_analyzer.analyze,
                text,
                file.filename,
            )

            await store_file(
                DocumentModel(
                    id=doc_id,
                    title=file.filename,
                    content=text,
                    size=os.path.getsize(doc_path),
                ),
                auto_analysis=auto_analysis,
            )

            logger.info(f"File {file.filename} stored successfully with ID {doc_id}")
            responses.append({
                "filename": file.filename,
                "doc_id": doc_id,
                "stored_at": doc_path,
                "auto_analysis": auto_analysis,
            })

        except Exception as e:
            logger.error(f"Error processing file {file.filename}: {str(e)}")
            responses.append({"filename": file.filename, "error": str(e)})

    return responses


@router.get(
    "",
    summary="List all files",
    description="Retrieve a list of all files currently indexed in the knowledge store.",
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
    list_excerpt_max = 400
    try:
        stored_files = knowledge_collection.get(include=["documents", "metadatas"])

        files = []
        for doc_id, doc_content, meta in zip(
            stored_files["ids"],
            stored_files["documents"],
            stored_files["metadatas"],
            strict=False,
        ):
            meta = meta or {}
            title = meta.get("title") or "Untitled"
            date = meta.get("date") or "Unknown"
            try:
                size = int(meta.get("size", 0))
            except (TypeError, ValueError):
                size = 0
            text = (doc_content or "") if isinstance(doc_content, str) else str(doc_content or "")
            excerpt = text[:list_excerpt_max].strip()
            if len(text) > list_excerpt_max:
                excerpt = f"{excerpt}..."
            auto_summary = (meta.get("auto_summary") or "").strip()
            summary = auto_summary if auto_summary else (excerpt or "(no text extracted)")
            category = (meta.get("auto_category") or "").strip() or "general"
            document_type = (meta.get("auto_type") or "").strip() or "unknown"
            conf = meta.get("confidence_score")
            try:
                confidence = float(conf) if conf is not None and conf != "" else None
            except (TypeError, ValueError):
                confidence = None

            files.append(
                {
                    "id": doc_id,
                    "title": title,
                    "date": date,
                    "size": size,
                    "summary": summary,
                    "excerpt": excerpt,
                    "category": category,
                    "document_type": document_type,
                    **({"confidence_score": confidence} if confidence is not None else {}),
                }
            )

        return {"documents": files}
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
                    "example": {"filename": "doc.pdf", "stored_at": "/path/doc.pdf", "text": "Extracted text"}
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
        text = await pdf_to_text(path)
    elif type == "docx":
        text = await docx_to_text(path)
    elif type == "image":
        text = await image_pdf_to_text(path)
    else:
        raise HTTPException(status_code=400, detail="Invalid file type")

    auto_analysis = await asyncio.to_thread(
        _content_analyzer.analyze,
        text,
        file.filename,
    )

    await store_file(
        DocumentModel(
            id=doc_id,
            title=file.filename,
            content=text,
            size=os.path.getsize(path) if os.path.exists(path) else 0,
        ),
        auto_analysis=auto_analysis,
    )

    return {
        "filename": file.filename,
        "stored_at": path,
        "text": text,
        "auto_analysis": auto_analysis,
    }
