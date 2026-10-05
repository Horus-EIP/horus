import asyncio
import datetime
import json
import os
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any, NamedTuple

from app.chroma_db.models import DocumentModel, SmartSearchRequest
from app.chroma_db.services.corpus_version import bump_corpus_version
from app.chroma_db.services.deleted_sources import remember_deleted
from app.chroma_db.setup import EMBED_MODEL, get_embedding, get_embeddings, knowledge_collection
from app.core.logging import get_logger
from app.core.metrics import timed_query
from app.services.document_chunker import DocumentChunker, TextChunk, page_of

logger = get_logger("FileService")

DOCUMENTS_ROOT = Path("documents")
DEFAULT_CATEGORY = "general"
WRITE_BATCH_SIZE = 100
PASSAGES_SEARCHED_PER_DOCUMENT_HIT = 5

chunker = DocumentChunker()

EmbedPassages = Callable[[list[str]], list[list[float]]]


class DocumentNotFoundError(LookupError):
    pass


#: Chroma only accepts scalars as metadata values; a dict or a list raises on add().
_SCALAR_TYPES = (str, int, float, bool)


class StoredEntry(NamedTuple):
    id: str
    text: str
    metadata: dict[str, Any]


class StoredDocument(NamedTuple):
    doc_id: str
    head_id: str
    metadata: dict[str, Any]


class DocumentText(NamedTuple):
    doc_id: str
    title: str
    text: str
    chunk_count: int
    metadata: dict[str, Any]


class Passage(NamedTuple):
    doc_id: str
    chunk_id: str
    text: str
    metadata: dict[str, Any]
    distance: float | None


def chunk_id(doc_id: str, chunk_index: int) -> str:
    return f"{doc_id}:{chunk_index}"


def document_id_of(entry_id: str, metadata: Mapping[str, Any]) -> str:
    return str(metadata.get("doc_id") or entry_id)


def is_legacy_entry(metadata: Mapping[str, Any]) -> bool:
    return metadata.get("chunk_index") is None


def is_document_head(metadata: Mapping[str, Any]) -> bool:
    return metadata.get("chunk_index") in (None, 0)


def document_category(metadata: Mapping[str, Any]) -> str:
    raw = metadata.get("category") or metadata.get("auto_category") or ""
    return str(raw).strip() or DEFAULT_CATEGORY


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _analysis_metadata(auto_analysis: Mapping[str, Any] | None) -> dict[str, Any]:
    if not auto_analysis:
        return {}
    metadata: dict[str, Any] = {
        "auto_category": auto_analysis.get("auto_category", DEFAULT_CATEGORY),
        "auto_type": auto_analysis.get("auto_type", "unknown"),
        "auto_summary": auto_analysis.get("auto_summary", ""),
        "confidence_score": float(auto_analysis.get("confidence_score", 0.0)),
    }
    entities = auto_analysis.get("entities", {})
    metadata["entities"] = json.dumps(entities)
    metadata["topics"] = json.dumps(auto_analysis.get("topics", []))
    for kind in ("people", "companies", "amounts", "dates"):
        if entities.get(kind):
            metadata[f"entities_{kind}"] = json.dumps(entities[kind])
    return metadata


def chunk_entries(
    doc_id: str,
    text: str,
    per_chunk: Mapping[str, Any],
    document_level: Mapping[str, Any],
    page_starts: Sequence[int] = (),
) -> list[StoredEntry]:
    chunks = chunker.split(text) or [TextChunk("", 0, 0)]
    entries: list[StoredEntry] = []
    for index, chunk in enumerate(chunks):
        metadata: dict[str, Any] = {
            **per_chunk,
            "chunk_index": index,
            "char_start": chunk.char_start,
            "char_end": chunk.char_end,
        }
        page = page_of(chunk.char_start, page_starts)
        if page is not None:
            metadata["page"] = page
        if index == 0:
            metadata = {**document_level, "chunk_count": len(chunks), **metadata}
        entries.append(StoredEntry(chunk_id(doc_id, index), chunk.text, metadata))
    return entries


def write_entries(entries: Sequence[StoredEntry], embed_passages: EmbedPassages) -> None:
    head_last = [*entries[1:], *entries[:1]]
    written: list[str] = []
    try:
        for start in range(0, len(head_last), WRITE_BATCH_SIZE):
            batch = head_last[start:start + WRITE_BATCH_SIZE]
            texts = [entry.text for entry in batch]
            knowledge_collection.add(
                ids=[entry.id for entry in batch],
                documents=texts,
                metadatas=[entry.metadata for entry in batch],
                embeddings=embed_passages(texts),
            )
            written.extend(entry.id for entry in batch)
    except Exception:
        if written:
            try:
                knowledge_collection.delete(ids=written)
            except Exception as exc:
                logger.warning("could not remove %d partly written chunks: %s", len(written), exc)
        raise


async def store_file(
    doc: DocumentModel,
    auto_analysis: dict[str, Any] | None = None,
    extra_metadata: dict[str, Any] | None = None,
    page_starts: Sequence[int] = (),
) -> int:
    extra = {
        key: value for key, value in (extra_metadata or {}).items()
        if isinstance(value, _SCALAR_TYPES)
    }
    analysis = _analysis_metadata(auto_analysis)
    per_chunk: dict[str, Any] = {
        "doc_id": doc.id,
        "title": doc.title,
        "source_path": str(extra.pop("source_path", "") or ""),
        "category": document_category(analysis),
        "embed_model": EMBED_MODEL,
    }
    if extra.get("stored_path"):
        per_chunk["stored_path"] = extra.pop("stored_path")
    document_level = {
        "date": str(datetime.datetime.now(datetime.UTC)),
        "size": doc.size,
        **analysis,
        **extra,
    }
    try:
        return await asyncio.to_thread(
            _replace_document, doc.id, doc.content, per_chunk, document_level, page_starts
        )
    finally:
        bump_corpus_version()


def _replace_document(
    doc_id: str,
    text: str,
    per_chunk: Mapping[str, Any],
    document_level: Mapping[str, Any],
    page_starts: Sequence[int],
) -> int:
    entries = chunk_entries(doc_id, text, per_chunk, document_level, page_starts)
    previous = [entry.id for entry in entries_of(doc_id)]
    if previous:
        knowledge_collection.delete(ids=previous)
    write_entries(entries, get_embeddings)
    return len(entries)


@timed_query
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


@timed_query
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


def fetch_entries(with_text: bool = False, **selector: Any) -> list[StoredEntry]:
    include = ["documents", "metadatas"] if with_text else ["metadatas"]
    found = knowledge_collection.get(include=include, **selector) or {}
    ids = found.get("ids") or []
    metadatas = found.get("metadatas") or []
    documents = (found.get("documents") or []) if with_text else []
    entries: list[StoredEntry] = []
    for index, entry_id in enumerate(ids):
        metadata = metadatas[index] if index < len(metadatas) else None
        text = documents[index] if index < len(documents) else ""
        entries.append(StoredEntry(
            str(entry_id),
            text if isinstance(text, str) else str(text or ""),
            dict(metadata or {}),
        ))
    return entries


def entries_of(doc_id: str, with_text: bool = False) -> list[StoredEntry]:
    found = {
        entry.id: entry
        for entry in (
            *fetch_entries(with_text, ids=[doc_id]),
            *fetch_entries(with_text, where={"doc_id": doc_id}),
        )
    }
    return list(found.values())


def stored_documents() -> list[StoredDocument]:
    heads: dict[str, StoredDocument] = {}
    for entry in fetch_entries():
        if is_document_head(entry.metadata):
            doc_id = document_id_of(entry.id, entry.metadata)
            heads.setdefault(doc_id, StoredDocument(doc_id, entry.id, entry.metadata))
    return list(heads.values())


def entry_texts(entry_ids: Iterable[str]) -> dict[str, str]:
    wanted = list(dict.fromkeys(entry_ids))
    if not wanted:
        return {}
    return {entry.id: entry.text for entry in fetch_entries(True, ids=wanted)}


def document_texts(doc_ids: Iterable[str]) -> dict[str, DocumentText]:
    wanted = list(dict.fromkeys(doc_ids))
    if not wanted:
        return {}
    wanted_set = set(wanted)
    grouped: dict[str, dict[str, StoredEntry]] = {}
    for entry in (
        *fetch_entries(True, ids=wanted),
        *fetch_entries(True, where={"doc_id": {"$in": wanted}}),
    ):
        doc_id = document_id_of(entry.id, entry.metadata)
        if doc_id in wanted_set:
            grouped.setdefault(doc_id, {})[entry.id] = entry
    return {
        doc_id: _assembled(doc_id, list(grouped[doc_id].values()))
        for doc_id in wanted if doc_id in grouped
    }


def _assembled(doc_id: str, entries: list[StoredEntry]) -> DocumentText:
    legacy = [entry for entry in entries if is_legacy_entry(entry.metadata)]
    if legacy:
        head = legacy[0]
        return DocumentText(
            doc_id, head.metadata.get("title") or "Untitled", head.text, 1, head.metadata
        )
    chunks = sorted(
        entries,
        key=lambda entry: (
            _as_int(entry.metadata.get("chunk_index"), 0),
            _as_int(entry.metadata.get("char_start"), 0),
        ),
    )
    head = chunks[0]
    return DocumentText(
        doc_id,
        head.metadata.get("title") or "Untitled",
        _joined(chunks),
        len(chunks),
        head.metadata,
    )


def _joined(chunks: list[StoredEntry]) -> str:
    parts: list[str] = []
    reached: int | None = None
    for entry in chunks:
        start = _as_int(entry.metadata.get("char_start"), reached or 0)
        end = _as_int(entry.metadata.get("char_end"), start + len(entry.text))
        if reached is None:
            parts.append(entry.text)
        elif end <= reached:
            continue
        elif start >= reached:
            parts.append(("\n" if start > reached else "") + entry.text)
        else:
            parts.append(entry.text[reached - start:])
        reached = end
    return "".join(parts)


def _first_row(value: Any) -> list[Any]:
    if isinstance(value, list) and value and isinstance(value[0], list):
        return value[0]
    return []


def passages_of(results: Mapping[str, Any]) -> list[Passage]:
    ids = _first_row(results.get("ids"))
    documents = _first_row(results.get("documents"))
    metadatas = _first_row(results.get("metadatas"))
    distances = _first_row(results.get("distances"))
    passages: list[Passage] = []
    for index, entry_id in enumerate(ids):
        metadata = dict((metadatas[index] if index < len(metadatas) else None) or {})
        text = documents[index] if index < len(documents) else ""
        distance = distances[index] if index < len(distances) else None
        passages.append(Passage(
            document_id_of(str(entry_id), metadata),
            str(entry_id),
            text if isinstance(text, str) else str(text or ""),
            metadata,
            distance,
        ))
    return passages


def _all_of(conditions: list[dict]) -> dict | None:
    if not conditions:
        return None
    if len(conditions) == 1:
        return conditions[0]
    return {"$and": conditions}


def _any_of(conditions: list[dict]) -> list[dict]:
    if len(conditions) <= 1:
        return conditions
    return [{"$or": conditions}]


def _passage_conditions(request: SmartSearchRequest) -> list[dict]:
    return _any_of([{"category": {"$eq": category}} for category in request.categories or []])


def _document_conditions(request: SmartSearchRequest) -> list[dict]:
    conditions = [
        {"entities_people": {"$contains": entity}} for entity in request.entities or []
    ]
    if request.min_confidence is not None:
        conditions.append({"confidence_score": {"$gte": request.min_confidence}})
    if request.entity_type:
        conditions.append({"entity_type": {"$eq": request.entity_type}})
    return conditions


def passage_where(request: SmartSearchRequest) -> dict | None:
    return _all_of(_passage_conditions(request))


def document_where(request: SmartSearchRequest) -> dict | None:
    return _all_of(_document_conditions(request))


def build_where_clause(request: SmartSearchRequest) -> dict | None:
    return _all_of(_passage_conditions(request) + _document_conditions(request))


def _documents_matching(document_where: dict) -> list[str]:
    return list(dict.fromkeys(
        document_id_of(entry.id, entry.metadata)
        for entry in fetch_entries(where=document_where)
        if is_document_head(entry.metadata)
    ))


def _head_metadata(doc_ids: Sequence[str]) -> dict[str, dict[str, Any]]:
    if not doc_ids:
        return {}
    heads: dict[str, dict[str, Any]] = {}
    for entry in fetch_entries(ids=[*(chunk_id(d, 0) for d in doc_ids), *doc_ids]):
        if is_document_head(entry.metadata):
            heads.setdefault(document_id_of(entry.id, entry.metadata), entry.metadata)
    return heads


async def search_documents(
    query: str,
    n_results: int,
    passage_where: dict | None = None,
    document_where: dict | None = None,
) -> list[Passage]:
    conditions = [passage_where] if passage_where else []
    if document_where:
        matching = _documents_matching(document_where)
        if not matching:
            return []
        conditions.append({"doc_id": {"$in": matching}})
    where = _all_of(conditions)
    searched = n_results * PASSAGES_SEARCHED_PER_DOCUMENT_HIT
    if where:
        results = await query_with_filters(query, where, searched)
    else:
        results = await query_knowledge(query, searched)

    best: dict[str, Passage] = {}
    for passage in passages_of(results):
        best.setdefault(passage.doc_id, passage)
        if len(best) == n_results:
            break
    heads = _head_metadata(list(best))
    return [
        hit._replace(metadata={**heads.get(hit.doc_id, {}), **hit.metadata})
        for hit in best.values()
    ]


def _entries(**selector: Any) -> dict[str, dict[str, Any]]:
    return {entry.id: entry.metadata for entry in fetch_entries(**selector)}


def _entries_of_document(doc_id: str) -> dict[str, dict[str, Any]]:
    entries = {entry.id: entry.metadata for entry in entries_of(doc_id)}
    source_paths = sorted({
        metadata["source_path"] for metadata in entries.values() if metadata.get("source_path")
    })
    if source_paths:
        entries.update(_entries(where={"source_path": {"$in": source_paths}}))
    return entries


def _deleted_sources(entries: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    documents: dict[str, dict[str, Any]] = {}
    for entry_id, metadata in entries.items():
        source = documents.setdefault(document_id_of(entry_id, metadata), {})
        for key in ("source_path", "content_sha256"):
            if metadata.get(key) and not source.get(key):
                source[key] = metadata[key]
    return [{"doc_id": doc_id, **source} for doc_id, source in documents.items()]


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

    remember_deleted(_deleted_sources(entries))
    deleted_ids = list(entries)
    knowledge_collection.delete(ids=deleted_ids)
    bump_corpus_version()
    return {"deleted_ids": deleted_ids, "removed_files": _remove_unused_files(entries.values())}
