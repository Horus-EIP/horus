import contextlib
import json
import os
import tempfile
import threading
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import Any

from app.chroma_db.setup import CHROMA_DATA_DIR
from app.core.logging import get_logger

logger = get_logger("DeletedSources")

DELETED_SOURCES_FILE = CHROMA_DATA_DIR / "deleted_sources.json"

_lock = threading.Lock()


def _read_entries() -> list[dict[str, Any]]:
    try:
        raw = DELETED_SOURCES_FILE.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    try:
        return [entry for entry in json.loads(raw)["deleted"] if isinstance(entry, dict)]
    except (ValueError, KeyError, TypeError) as exc:
        logger.warning(
            "deleted sources list %s is unreadable, treating it as empty: %s",
            DELETED_SOURCES_FILE, exc,
        )
        return []


def _write_entries(entries: list[dict[str, Any]]) -> None:
    DELETED_SOURCES_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd, staging = tempfile.mkstemp(
        dir=DELETED_SOURCES_FILE.parent, prefix=DELETED_SOURCES_FILE.name, suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump({"deleted": entries}, handle, indent=2)
        os.replace(staging, DELETED_SOURCES_FILE)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(staging)
        raise


def _matches(entry: Mapping[str, Any], source_path: str, content_sha256: str) -> bool:
    same_path = bool(source_path) and entry.get("source_path") == source_path
    same_content = bool(content_sha256) and entry.get("content_sha256") == content_sha256
    return same_path or same_content


def remember_deleted(sources: Iterable[Mapping[str, Any]]) -> int:
    deleted_at = datetime.now(UTC).isoformat()
    with _lock:
        entries = _read_entries()
        known = {(e.get("source_path"), e.get("content_sha256") or "") for e in entries}
        added = 0
        for source in sources:
            key = (source.get("source_path") or "", source.get("content_sha256") or "")
            if not key[0] or key in known:
                continue
            known.add(key)
            entries.append({
                "doc_id": str(source.get("doc_id") or ""),
                "source_path": key[0],
                "content_sha256": key[1],
                "deleted_at": deleted_at,
            })
            added += 1
        if added:
            _write_entries(entries)
    return added


def was_deleted(source_path: str, content_sha256: str) -> bool:
    with _lock:
        entries = _read_entries()
    return any(_matches(entry, source_path, content_sha256) for entry in entries)


def forget_deleted(source_path: str, content_sha256: str) -> int:
    with _lock:
        entries = _read_entries()
        kept = [e for e in entries if not _matches(e, source_path, content_sha256)]
        if len(kept) != len(entries):
            _write_entries(kept)
    return len(entries) - len(kept)
