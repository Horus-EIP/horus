from collections.abc import Mapping
from typing import Any

from app.chroma_db.services import file_service
from app.chroma_db.services.corpus_version import bump_corpus_version
from app.chroma_db.services.file_service import (
    EmbedPassages,
    StoredEntry,
    chunk_entries,
    document_category,
    document_id_of,
    entries_of,
    fetch_entries,
    is_legacy_entry,
    write_entries,
)
from app.chroma_db.setup import COLLECTION_METADATA
from app.core.logging import get_logger

logger = get_logger("Reindex")

MIGRATED = "migrated"
REEMBEDDED = "reembedded"
UNCHANGED = "unchanged"

UPDATE_BATCH_SIZE = 100
CHUNK_POSITION_KEYS = frozenset({"chunk_index", "char_start", "char_end", "page", "chunk_count"})
RETIRED_KEYS = frozenset({"embedding_model"})


def documents_to_reindex(embed_model: str) -> list[str]:
    pending: dict[str, None] = {}
    for entry in fetch_entries():
        if is_legacy_entry(entry.metadata) or entry.metadata.get("embed_model") != embed_model:
            pending.setdefault(document_id_of(entry.id, entry.metadata), None)
    return list(pending)


def record_embedder_in_collection() -> bool:
    collection = file_service.knowledge_collection
    stored = dict(collection.metadata or {})
    if all(stored.get(key) == value for key, value in COLLECTION_METADATA.items()):
        return False
    collection.modify(metadata={**stored, **COLLECTION_METADATA})
    logger.info("re-index: the collection now records the embedder %s",
                COLLECTION_METADATA["embed_model"])
    return True


def reindex_document(doc_id: str, embed_passages: EmbedPassages, embed_model: str) -> str:
    entries = entries_of(doc_id, with_text=True)
    legacy = [entry for entry in entries if is_legacy_entry(entry.metadata)]
    if legacy:
        _migrate(doc_id, entries, legacy, embed_passages, embed_model)
        outcome = MIGRATED
    else:
        stale = [entry for entry in entries if entry.metadata.get("embed_model") != embed_model]
        if not stale:
            return UNCHANGED
        _reembed(stale, embed_passages, embed_model)
        outcome = REEMBEDDED
    bump_corpus_version()
    logger.info("re-index: %s %s", doc_id, outcome)
    return outcome


def _split_metadata(
    doc_id: str, metadata: Mapping[str, Any], embed_model: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    per_chunk: dict[str, Any] = {
        "doc_id": doc_id,
        "title": metadata.get("title") or "Untitled",
        "source_path": str(metadata.get("source_path") or ""),
        "category": document_category(metadata),
        "embed_model": embed_model,
    }
    if metadata.get("stored_path"):
        per_chunk["stored_path"] = metadata["stored_path"]
    document_level = {
        key: value for key, value in metadata.items()
        if key not in per_chunk and key not in CHUNK_POSITION_KEYS and key not in RETIRED_KEYS
    }
    return per_chunk, document_level


def _migrate(
    doc_id: str,
    entries: list[StoredEntry],
    legacy: list[StoredEntry],
    embed_passages: EmbedPassages,
    embed_model: str,
) -> None:
    original = next((entry for entry in legacy if entry.id == doc_id), legacy[0])
    per_chunk, document_level = _split_metadata(doc_id, original.metadata, embed_model)
    replacement = chunk_entries(doc_id, original.text, per_chunk, document_level)
    original_survives_the_write = original.id not in {entry.id for entry in replacement}
    cleared_first = [
        entry.id for entry in entries
        if entry.id != original.id or not original_survives_the_write
    ]
    if cleared_first:
        file_service.knowledge_collection.delete(ids=cleared_first)
    write_entries(replacement, embed_passages)
    if original_survives_the_write:
        file_service.knowledge_collection.delete(ids=[original.id])


def _reembed(
    stale: list[StoredEntry], embed_passages: EmbedPassages, embed_model: str
) -> None:
    for start in range(0, len(stale), UPDATE_BATCH_SIZE):
        batch = stale[start:start + UPDATE_BATCH_SIZE]
        file_service.knowledge_collection.update(
            ids=[entry.id for entry in batch],
            embeddings=embed_passages([entry.text for entry in batch]),
            metadatas=[{**entry.metadata, "embed_model": embed_model} for entry in batch],
        )
