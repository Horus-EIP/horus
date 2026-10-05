import datetime
import json
import os
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from app.chroma_db.models import DocumentModel, SmartSearchRequest
from app.chroma_db.services.corpus_version import bump_corpus_version
from app.chroma_db.services.deleted_sources import remember_deleted
from app.chroma_db.setup import get_embedding, knowledge_collection
from app.core.logging import get_logger

logger = get_logger("FileService")

DOCUMENTS_ROOT = Path("documents")


class DocumentNotFoundError(LookupError):
    pass


#: Chroma only accepts scalars as metadata values; a dict or a list raises on add().
_SCALAR_TYPES = (str, int, float, bool)


async def store_file(
    doc: DocumentModel,
    auto_analysis: dict[str, Any] | None = None,
    extra_metadata: dict[str, Any] | None = None,
):
    """
    Store a document in the ChromaDB knowledge collection.

    Args:
        doc: DocumentModel with id, title, content, size.
        auto_analysis: Optional dict from ContentAnalyzer.analyze() with keys:
            auto_category, auto_type, auto_summary, entities, topics, confidence_score.
        extra_metadata: Optional flat scalar fields to record alongside the rest.
            The corpus scanner uses this for source_path / content_sha256 / source,
            which is how a re-scan recognises a file it has already ingested.
            Non-scalar values are dropped rather than allowed to fail the add().
    """
    embedding = get_embedding(doc.content, is_query=False)

    metadata = {
        "title": doc.title,
        "date": str(datetime.datetime.now(datetime.UTC)),
        "size": doc.size,
    }

    if auto_analysis:
        metadata["auto_category"] = auto_analysis.get("auto_category", "general")
        metadata["auto_type"] = auto_analysis.get("auto_type", "unknown")
        metadata["auto_summary"] = auto_analysis.get("auto_summary", "")
        metadata["confidence_score"] = float(auto_analysis.get("confidence_score", 0.0))

        entities = auto_analysis.get("entities", {})
        metadata["entities"] = json.dumps(entities)
        metadata["topics"] = json.dumps(auto_analysis.get("topics", []))

        if entities.get("people"):
            metadata["entities_people"] = json.dumps(entities["people"])
        if entities.get("companies"):
            metadata["entities_companies"] = json.dumps(entities["companies"])
        if entities.get("amounts"):
            metadata["entities_amounts"] = json.dumps(entities["amounts"])
        if entities.get("dates"):
            metadata["entities_dates"] = json.dumps(entities["dates"])

    if extra_metadata:
        for key, value in extra_metadata.items():
            if isinstance(value, _SCALAR_TYPES):
                metadata[key] = value

    knowledge_collection.add(
        ids=[doc.id],
        documents=[doc.content],
        metadatas=[metadata],
        embeddings=[embedding],
    )
    bump_corpus_version()


async def query_knowledge(query: str, n_results: int) -> dict:
    """
    Query the knowledge store for documents relevant to the search string.

    Args:
        query: The search query text.
        n_results: The maximum number of results to return.

    Returns:
        dict with 'ids', 'documents', 'metadatas', and 'distances'.
    """
    query_embedding = get_embedding(query, is_query=True)

    return knowledge_collection.query(
        query_embeddings=[query_embedding],
        n_results=n_results,
        include=["documents", "metadatas", "distances"],
    )


async def query_with_filters(query: str, filters: dict, n_results: int) -> dict:
    """
    Query the knowledge store with a query string and metadata filters.

    Args:
        query: The search query text.
        filters: ChromaDB where-clause filters.
        n_results: The number of results to return.

    Returns:
        dict with query results.
    """
    query_embedding = get_embedding(query, is_query=True)

    return knowledge_collection.query(
        query_embeddings=[query_embedding],
        n_results=n_results,
        include=["documents", "metadatas", "distances"],
        where=filters,
    )


def _entries(**selector: Any) -> dict[str, dict[str, Any]]:
    found = knowledge_collection.get(include=["metadatas"], **selector) or {}
    ids = found.get("ids") or []
    metadatas = found.get("metadatas") or []
    return {
        str(entry_id): dict(metadata or {})
        for entry_id, metadata in zip(ids, metadatas, strict=False)
    }


def _entries_of_document(doc_id: str) -> dict[str, dict[str, Any]]:
    entries = _entries(ids=[doc_id])
    entries.update(_entries(where={"doc_id": doc_id}))
    source_paths = sorted({
        metadata["source_path"] for metadata in entries.values() if metadata.get("source_path")
    })
    if source_paths:
        entries.update(_entries(where={"source_path": {"$in": source_paths}}))
    return entries


def _stored_file(metadata: Mapping[str, Any]) -> Path | None:
    if metadata.get("source_path"):
        return None
    recorded = metadata.get("stored_path")
    if recorded:
        candidate = Path(str(recorded))
    else:
        name = os.path.basename(str(metadata.get("title") or ""))
        if not name:
            return None
        candidate = DOCUMENTS_ROOT / name.split(".")[-1].lower() / name
    root = DOCUMENTS_ROOT.resolve()
    resolved = candidate.resolve()
    if resolved == root or not resolved.is_relative_to(root):
        return None
    return resolved


def _still_used(path: Path, title: str) -> bool:
    return any(
        _stored_file(metadata) == path
        for metadata in _entries(where={"title": title}).values()
    )


def _remove_unused_files(metadatas: Iterable[Mapping[str, Any]]) -> list[str]:
    candidates: dict[Path, str] = {}
    for metadata in metadatas:
        path = _stored_file(metadata)
        if path is not None:
            candidates.setdefault(path, str(metadata.get("title") or ""))

    removed: list[str] = []
    for path, title in candidates.items():
        if not path.is_file() or _still_used(path, title):
            continue
        try:
            path.unlink()
        except OSError as exc:
            logger.warning("could not remove stored file %s: %s", path, exc)
            continue
        removed.append(path.relative_to(DOCUMENTS_ROOT.resolve()).as_posix())
    return removed


async def delete_document(id: str) -> dict:
    entries = _entries_of_document(id)
    if not entries:
        raise DocumentNotFoundError(f"No document with id {id!r} in the knowledge store")

    remember_deleted({"doc_id": entry_id, **metadata} for entry_id, metadata in entries.items())
    deleted_ids = list(entries)
    knowledge_collection.delete(ids=deleted_ids)
    bump_corpus_version()
    return {"deleted_ids": deleted_ids, "removed_files": _remove_unused_files(entries.values())}


def build_where_clause(request: SmartSearchRequest) -> dict | None:
    """
    Build a ChromaDB metadata where-clause filter from a SmartSearchRequest.

    Args:
        request: SmartSearchRequest with optional categories, entities,
                 min_confidence, entity_type.

    Returns:
        A ChromaDB where filter dict, or None if no filters apply.
    """
    where = []

    if request.categories:
        if len(request.categories) == 1:
            where.append({"auto_category": {"$eq": request.categories[0]}})
        else:
            where.append({"$or": [{"auto_category": {"$eq": cat}} for cat in request.categories]})

    if request.entities:
        for entity in request.entities:
            where.append({"entities_people": {"$contains": entity}})

    if request.min_confidence is not None:
        where.append({"confidence_score": {"$gte": request.min_confidence}})

    if request.entity_type:
        where.append({"entity_type": {"$eq": request.entity_type}})

    if not where:
        return None
    if len(where) == 1:
        return where[0]
    return {"$and": where}
