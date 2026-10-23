from __future__ import annotations

import asyncio
import hashlib
import hmac
import os
import stat
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NamedTuple

from fastapi import APIRouter, Depends, Header, HTTPException, Query

from app.api.routes.file import ExtractedText, _content_analyzer, extract_document
from app.chroma_db import DocumentModel, knowledge_collection, store_file
from app.chroma_db.services import file_service, reindex
from app.chroma_db.services.corpus_version import bump_corpus_version
from app.chroma_db.services.deleted_sources import forget_deleted, was_deleted
from app.chroma_db.services.file_service import chunk_id, document_id_of
from app.core.logging import get_logger
from app.services.content_analyzer import ContentAnalyzer

logger = get_logger("CorpusRouter")

CORPUS_TOKEN_ENV = "CORPUS_SCAN_TOKEN"
CORPUS_TOKEN_HEADER = "X-Corpus-Token"
STARTUP_REINDEX_ENV = "KNOWLEDGE_STORE_REINDEX_ON_STARTUP"
DISABLED_VALUES = frozenset({"0", "false", "no", "off"})
REQUESTED = "request"
STARTUP = "startup"


async def require_corpus_token(
    presented: str | None = Header(default=None, alias=CORPUS_TOKEN_HEADER),
) -> None:
    expected = os.getenv(CORPUS_TOKEN_ENV, "").strip()
    if not expected:
        raise HTTPException(
            status_code=503,
            detail=(
                f"Corpus routes are disabled: {CORPUS_TOKEN_ENV} is unset in the "
                "knowledge_store container. Set it in src/infra/.env and restart."
            ),
        )
    if not hmac.compare_digest((presented or "").encode(), expected.encode()):
        raise HTTPException(
            status_code=403,
            detail=f"Missing or invalid {CORPUS_TOKEN_HEADER} header.",
        )


router = APIRouter(tags=["Corpus"], dependencies=[Depends(require_corpus_token)])

_ANALYZER: ContentAnalyzer = _content_analyzer

CORPUS_ROOT = Path(os.getenv("CORPUS_DIR", "/app/corpus")).resolve(strict=False)


def _env_int(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, "").strip())
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


ALLOWED_EXTENSIONS = frozenset({".pdf", ".docx", ".txt", ".md", ".csv", ".json", ".log"})

MAX_FILE_BYTES = _env_int("CORPUS_MAX_FILE_BYTES", 20 * 1024 * 1024)

PRUNED_DIR_NAMES = frozenset(
    {
        ".git",
        ".ssh",
        ".svn",
        ".hg",
        "node_modules",
        "__pycache__",
        ".venv",
        "venv",
        ".tox",
        ".mypy_cache",
        ".pytest_cache",
    }
)

HASH_CHUNK_BYTES = 1024 * 1024

OPEN_FLAGS = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)

HAS_PROC_FD = os.path.exists("/proc/self/fd")

MAX_REPORT_ENTRIES = _env_int("CORPUS_MAX_REPORT_ENTRIES", 2000)

SKIP_SYMLINK = "symlink"
SKIP_HARD_LINK = "hard-link"
SKIP_OUTSIDE_ROOT = "outside-corpus-root"
SKIP_UNRESOLVABLE = "unresolvable-path"
SKIP_NOT_REGULAR = "not-a-regular-file"
SKIP_EXTENSION = "unsupported-extension"
SKIP_EMPTY = "empty-file"
SKIP_TOO_LARGE = "too-large"
SKIP_CHANGED_DURING_SCAN = "changed-during-scan"


class Candidate(NamedTuple):
    resolved: Path | None
    reason: str | None
    size: int
    dev: int = 0
    ino: int = 0


def _rejected(reason: str, size: int = 0) -> Candidate:
    return Candidate(None, reason, size)


def inspect_candidate(
    path: Path,
    root: Path,
    max_bytes: int | None = None,
) -> Candidate:
    max_bytes = MAX_FILE_BYTES if max_bytes is None else max_bytes

    if path.is_symlink():
        return _rejected(SKIP_SYMLINK)

    try:
        resolved = path.resolve(strict=True)
    except OSError:
        return _rejected(SKIP_UNRESOLVABLE)

    if not resolved.is_relative_to(root):
        return _rejected(SKIP_OUTSIDE_ROOT)

    try:
        info = resolved.stat()
    except OSError:
        return _rejected(SKIP_UNRESOLVABLE)

    if not stat.S_ISREG(info.st_mode):
        return _rejected(SKIP_NOT_REGULAR)

    if info.st_nlink > 1:
        return _rejected(SKIP_HARD_LINK, info.st_size)

    if path.suffix.lower() not in ALLOWED_EXTENSIONS:
        return _rejected(SKIP_EXTENSION)

    if info.st_size == 0:
        return _rejected(SKIP_EMPTY)
    if info.st_size > max_bytes:
        return _rejected(SKIP_TOO_LARGE, info.st_size)

    return Candidate(resolved, None, info.st_size, info.st_dev, info.st_ino)


def _relative_label(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.name


def walk_corpus(
    root: Path,
    max_bytes: int | None = None,
) -> list[tuple[Path, str, Candidate]]:
    root = root.resolve(strict=False)
    rows: list[tuple[Path, str, Candidate]] = []
    if not root.is_dir():
        return rows

    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        here = Path(dirpath)
        dirnames[:] = [
            name
            for name in sorted(dirnames)
            if not name.startswith(".")
            and name not in PRUNED_DIR_NAMES
            and not (here / name).is_symlink()
        ]
        for name in sorted(filenames):
            path = here / name
            rows.append(
                (
                    path,
                    _relative_label(path, root),
                    inspect_candidate(path, root, max_bytes),
                )
            )

    return rows


def sha256_of_fd(fd: int, chunk_bytes: int = HASH_CHUNK_BYTES) -> str:
    digest = hashlib.sha256()
    os.lseek(fd, 0, os.SEEK_SET)
    while chunk := os.read(fd, chunk_bytes):
        digest.update(chunk)
    os.lseek(fd, 0, os.SEEK_SET)
    return digest.hexdigest()


def sha256_of_file(path: Path, chunk_bytes: int = HASH_CHUNK_BYTES) -> str:
    fd = os.open(path, OPEN_FLAGS)
    try:
        return sha256_of_fd(fd, chunk_bytes)
    finally:
        os.close(fd)


def doc_id_for(digest: str) -> str:
    return f"corpus-{digest[:32]}"


def _identity(info: os.stat_result) -> tuple[int, int, int]:
    return (info.st_dev, info.st_ino, info.st_size)


def _open_pinned(path: Path, pinned: Candidate) -> int | None:
    fd = os.open(path, OPEN_FLAGS)
    if _identity(os.fstat(fd)) != (pinned.dev, pinned.ino, pinned.size):
        os.close(fd)
        return None
    return fd


def _still_pinned(path: Path, pinned: Candidate) -> bool:
    fd = _open_pinned(path, pinned)
    if fd is None:
        return False
    os.close(fd)
    return True


def _pinned_path(fd: int, path: Path) -> str:
    return f"/proc/self/fd/{fd}" if HAS_PROC_FD else str(path)


def _extract_text_blocking(path: str, ext: str) -> ExtractedText:
    return asyncio.run(extract_document(path, ext))


def _store_blocking(
    doc: DocumentModel,
    auto_analysis: dict[str, Any],
    extra_metadata: dict[str, Any],
    page_starts: tuple[int, ...] = (),
) -> int:
    return asyncio.run(
        store_file(
            doc,
            auto_analysis=auto_analysis,
            extra_metadata=extra_metadata,
            page_starts=page_starts,
        )
    )


def _already_stored(doc_id: str) -> bool:
    try:
        found = knowledge_collection.get(ids=[chunk_id(doc_id, 0), doc_id], include=["metadatas"])
    except Exception as exc:  # noqa: BLE001 - a lookup failure must not abort the scan
        logger.warning("corpus: id lookup failed for %s: %s", doc_id, exc)
        return False
    return bool(found and found.get("ids"))


def _drop_previous_versions(rel: str, keep_id: str) -> int:
    try:
        found = knowledge_collection.get(where={"source_path": rel}, include=["metadatas"])
    except Exception as exc:  # noqa: BLE001
        logger.warning("corpus: stale lookup failed for %s: %s", rel, exc)
        return 0
    stale_ids: list[str] = []
    stale_documents: set[str] = set()
    for entry_id, metadata in zip(
        found.get("ids") or [], found.get("metadatas") or [], strict=False
    ):
        document = document_id_of(str(entry_id), metadata or {})
        if document != keep_id:
            stale_ids.append(str(entry_id))
            stale_documents.add(document)
    if not stale_ids:
        return 0
    try:
        knowledge_collection.delete(ids=stale_ids)
    except Exception as exc:  # noqa: BLE001
        logger.warning("corpus: stale delete failed for %s: %s", rel, exc)
        return 0
    bump_corpus_version()
    return len(stale_documents)


_scan_slot = asyncio.Semaphore(1)
_job: dict[str, Any] | None = None
_scan_task: asyncio.Task | None = None
_reindex_job: dict[str, Any] | None = None
_reindex_task: asyncio.Task | None = None
_startup_check: asyncio.Task | None = None


def _busy_detail() -> str:
    if (_reindex_job or {}).get("state") == "running":
        return (
            f"A re-index is running (job {_reindex_job['job_id']}). "
            f"Poll GET /corpus/reindex and retry when it reports completed."
        )
    running = (_job or {}).get("job_id", "unknown")
    return (
        f"A corpus scan is already running (job {running}). "
        f"Poll GET /corpus/status and retry when it reports completed."
    )


def _new_job(dry_run: bool, include_deleted: bool = False) -> dict[str, Any]:
    return {
        "job_id": uuid.uuid4().hex,
        "state": "running",
        "dry_run": dry_run,
        "include_deleted": include_deleted,
        "root": str(CORPUS_ROOT),
        "started_at": datetime.now(UTC).isoformat(),
        "finished_at": None,
        "error": None,
        "totals": {
            "files_seen": 0,
            "eligible": 0,
            "ingested": 0,
            "would_ingest": 0,
            "skipped_unchanged": 0,
            "skipped_deleted": 0,
            "rejected": 0,
            "failed": 0,
            "replaced_stale": 0,
        },
        "files": [],
        "report_truncated": False,
    }


def _record(job: dict[str, Any], entry: dict[str, Any]) -> None:
    if len(job["files"]) < MAX_REPORT_ENTRIES:
        job["files"].append(entry)
    else:
        job["report_truncated"] = True


def _record_changed(job: dict[str, Any], rel: str, size: int) -> None:
    job["totals"]["rejected"] += 1
    _record(
        job,
        {
            "path": rel,
            "decision": "skipped",
            "reason": SKIP_CHANGED_DURING_SCAN,
            "bytes": size,
        },
    )


async def _ingest_one(job: dict[str, Any], path: Path, rel: str, pinned: Candidate) -> None:
    fd = await asyncio.to_thread(_open_pinned, path, pinned)
    if fd is None:
        _record_changed(job, rel, pinned.size)
        return

    try:
        size = pinned.size
        digest = await asyncio.to_thread(sha256_of_fd, fd)
        doc_id = doc_id_for(digest)

        if await asyncio.to_thread(_already_stored, doc_id):
            job["totals"]["skipped_unchanged"] += 1
            _record(
                job,
                {
                    "path": rel,
                    "decision": "skipped_unchanged",
                    "doc_id": doc_id,
                    "bytes": size,
                },
            )
            return

        if not job["include_deleted"] and await asyncio.to_thread(was_deleted, rel, digest):
            job["totals"]["skipped_deleted"] += 1
            _record(
                job,
                {
                    "path": rel,
                    "decision": "skipped_deleted",
                    "doc_id": doc_id,
                    "bytes": size,
                },
            )
            return

        if job["dry_run"]:
            job["totals"]["would_ingest"] += 1
            _record(
                job,
                {
                    "path": rel,
                    "decision": "would_ingest",
                    "doc_id": doc_id,
                    "bytes": size,
                },
            )
            return

        if not HAS_PROC_FD and not await asyncio.to_thread(_still_pinned, path, pinned):
            _record_changed(job, rel, size)
            return

        extracted = await asyncio.to_thread(
            _extract_text_blocking, _pinned_path(fd, path), path.suffix
        )
        analysis = await asyncio.to_thread(_ANALYZER.analyze, extracted.text, path.name)

        replaced = await asyncio.to_thread(_drop_previous_versions, rel, doc_id)
        job["totals"]["replaced_stale"] += replaced

        chunks = await asyncio.to_thread(
            _store_blocking,
            DocumentModel(id=doc_id, title=path.name, content=extracted.text, size=size),
            analysis,
            {"source_path": rel, "content_sha256": digest, "source": "corpus"},
            extracted.page_starts,
        )
        if job["include_deleted"]:
            await asyncio.to_thread(forget_deleted, rel, digest)

        job["totals"]["ingested"] += 1
        _record(
            job,
            {
                "path": rel,
                "decision": "ingested",
                "doc_id": doc_id,
                "bytes": size,
                "characters": len(extracted.text),
                "chunks": chunks,
                **({"replaced_stale": replaced} if replaced else {}),
            },
        )
    finally:
        os.close(fd)


async def _run_scan(job: dict[str, Any]) -> None:
    try:
        rows = await asyncio.to_thread(walk_corpus, CORPUS_ROOT, MAX_FILE_BYTES)
        job["totals"]["files_seen"] = len(rows)

        for path, rel, candidate in rows:
            if candidate.reason is None:
                candidate = await asyncio.to_thread(
                    inspect_candidate, path, CORPUS_ROOT, MAX_FILE_BYTES
                )

            if candidate.reason is not None:
                job["totals"]["rejected"] += 1
                _record(
                    job,
                    {
                        "path": rel,
                        "decision": "skipped",
                        "reason": candidate.reason,
                        "bytes": candidate.size,
                    },
                )
                continue

            job["totals"]["eligible"] += 1
            try:
                await _ingest_one(job, candidate.resolved, rel, candidate)
            except Exception as exc:  # noqa: BLE001
                job["totals"]["failed"] += 1
                _record(
                    job,
                    {
                        "path": rel,
                        "decision": "failed",
                        "reason": f"{type(exc).__name__}: {exc}",
                        "bytes": candidate.size,
                    },
                )
                logger.warning("corpus: %s failed: %s", rel, exc)

        job["state"] = "completed"
        logger.info("corpus scan %s complete: %s", job["job_id"], job["totals"])
    except Exception as exc:  # noqa: BLE001 - the walk itself blew up
        job["state"] = "failed"
        job["error"] = f"{type(exc).__name__}: {exc}"
        logger.error("corpus scan %s failed: %s", job["job_id"], exc)
    finally:
        job["finished_at"] = datetime.now(UTC).isoformat()
        _scan_slot.release()


@router.post(
    "/scan",
    status_code=202,
    summary="Ingest the mounted corpus folder",
    description=(
        "Walk the read-only folder mounted at CORPUS_DIR (default /app/corpus) and "
        "index every supported file. Returns immediately with a job id; poll "
        "GET /corpus/status for progress. Files already indexed with identical "
        "content are skipped, so running this twice is a no-op. Files deleted from "
        "the knowledge store are skipped too (decision skipped_deleted), even after "
        "an edit, unless include_deleted=true. "
        "Pass dry_run=true to get the candidate list and per-file decisions "
        "without embedding anything. Requires the X-Corpus-Token header."
    ),
    responses={
        202: {
            "description": "Scan accepted and running in the background",
            "content": {
                "application/json": {
                    "example": {
                        "job_id": "9f2c...",
                        "state": "running",
                        "dry_run": False,
                        "include_deleted": False,
                    }
                }
            },
        },
        403: {"description": "Missing or invalid X-Corpus-Token"},
        404: {"description": "No corpus folder is mounted"},
        409: {"description": "A scan is already running"},
        503: {"description": "CORPUS_SCAN_TOKEN is not configured"},
    },
)
async def scan_corpus(
    dry_run: bool = Query(
        False,
        description="Report what would happen without embedding or storing anything.",
    ),
    include_deleted: bool = Query(
        False,
        description=(
            "Also index files that were deleted from the knowledge store, and take "
            "the ones it indexes off the deleted list."
        ),
    ),
):
    global _job, _scan_task

    if not CORPUS_ROOT.is_dir():
        raise HTTPException(
            status_code=404,
            detail=(
                f"No corpus folder at {CORPUS_ROOT}. Set HORUS_CORPUS_DIR to the folder "
                "you want indexed and restart the knowledge_store container."
            ),
        )

    if _scan_slot.locked():
        raise HTTPException(status_code=409, detail=_busy_detail())
    await _scan_slot.acquire()

    _job = _new_job(dry_run, include_deleted)
    logger.info(
        "corpus scan %s starting (dry_run=%s, include_deleted=%s) on %s",
        _job["job_id"],
        dry_run,
        include_deleted,
        CORPUS_ROOT,
    )
    _scan_task = asyncio.create_task(_run_scan(_job))

    return {
        "job_id": _job["job_id"],
        "state": "running",
        "dry_run": dry_run,
        "include_deleted": include_deleted,
        "root": str(CORPUS_ROOT),
    }


@router.get(
    "/status",
    summary="Progress of the most recent corpus scan",
    description=(
        "Totals and per-file decisions for the latest scan. state is one of "
        "idle, running, completed, failed. Requires the X-Corpus-Token header: "
        "the per-file list is a map of the tester's folder."
    ),
    responses={
        200: {
            "description": "Latest scan state",
            "content": {
                "application/json": {
                    "example": {
                        "job_id": "9f2c...",
                        "state": "completed",
                        "totals": {
                            "files_seen": 12,
                            "eligible": 5,
                            "ingested": 5,
                            "would_ingest": 0,
                            "skipped_unchanged": 0,
                            "skipped_deleted": 0,
                            "rejected": 7,
                            "failed": 0,
                            "replaced_stale": 0,
                        },
                        "files": [
                            {
                                "path": "reports/q4.md",
                                "decision": "ingested",
                                "doc_id": "corpus-1a2b",
                                "bytes": 4096,
                            },
                            {
                                "path": "id_rsa.pem",
                                "decision": "skipped",
                                "reason": "unsupported-extension",
                                "bytes": 0,
                            },
                        ],
                    }
                }
            },
        },
        403: {"description": "Missing or invalid X-Corpus-Token"},
        503: {"description": "CORPUS_SCAN_TOKEN is not configured"},
    },
)
async def corpus_status():
    if _job is None:
        return {
            "state": "idle",
            "root": str(CORPUS_ROOT),
            "mounted": CORPUS_ROOT.is_dir(),
            "allowed_extensions": sorted(ALLOWED_EXTENSIONS),
            "max_file_bytes": MAX_FILE_BYTES,
        }
    return _job


def _new_reindex_job(trigger: str = REQUESTED) -> dict[str, Any]:
    return {
        "job_id": uuid.uuid4().hex,
        "state": "running",
        "trigger": trigger,
        "embed_model": file_service.EMBED_MODEL,
        "started_at": datetime.now(UTC).isoformat(),
        "finished_at": None,
        "error": None,
        "totals": {
            "pending": 0,
            reindex.MIGRATED: 0,
            reindex.REEMBEDDED: 0,
            reindex.UNCHANGED: 0,
            "failed": 0,
        },
        "failures": [],
    }


async def _run_reindex(job: dict[str, Any]) -> None:
    try:
        embed_model = job["embed_model"]
        pending = await asyncio.to_thread(reindex.documents_to_reindex, embed_model)
        job["totals"]["pending"] = len(pending)
        for doc_id in pending:
            try:
                outcome = await asyncio.to_thread(
                    reindex.reindex_document, doc_id, file_service.get_embeddings, embed_model
                )
            except Exception as exc:
                job["totals"]["failed"] += 1
                if len(job["failures"]) < MAX_REPORT_ENTRIES:
                    job["failures"].append(
                        {"doc_id": doc_id, "reason": f"{type(exc).__name__}: {exc}"}
                    )
                logger.warning("re-index: %s failed: %s", doc_id, exc)
                continue
            job["totals"][outcome] += 1
        job["state"] = "completed"
        logger.info("re-index %s complete: %s", job["job_id"], job["totals"])
        if not job["totals"]["failed"]:
            await asyncio.to_thread(reindex.record_embedder_in_collection)
        await asyncio.to_thread(file_service.refresh_document_count)
    except Exception as exc:
        job["state"] = "failed"
        job["error"] = f"{type(exc).__name__}: {exc}"
        logger.error("re-index %s failed: %s", job["job_id"], exc)
    finally:
        job["finished_at"] = datetime.now(UTC).isoformat()
        _scan_slot.release()


def reindex_on_startup_enabled() -> bool:
    return os.getenv(STARTUP_REINDEX_ENV, "1").strip().lower() not in DISABLED_VALUES


def _start_reindex(trigger: str) -> dict[str, Any]:
    global _reindex_job, _reindex_task
    _reindex_job = _new_reindex_job(trigger)
    _reindex_task = asyncio.create_task(_run_reindex(_reindex_job))
    return _reindex_job


async def check_index_on_startup() -> dict[str, Any] | None:
    embed_model = file_service.EMBED_MODEL
    try:
        await asyncio.to_thread(file_service.refresh_document_count)
        pending = await asyncio.to_thread(reindex.documents_to_reindex, embed_model)
        if not pending:
            await asyncio.to_thread(reindex.record_embedder_in_collection)
            logger.info("startup: every stored passage is embedded with %s", embed_model)
            return None
    except Exception as exc:
        logger.warning("startup: could not check the index against %s: %s", embed_model, exc)
        return None
    if not reindex_on_startup_enabled():
        logger.warning(
            "startup: %d documents are stored as whole files or with another embedder than "
            "%s, and %s is off; run scripts/reindex-knowledge-store.py",
            len(pending),
            embed_model,
            STARTUP_REINDEX_ENV,
        )
        return None
    if _scan_slot.locked():
        logger.warning(
            "startup: %d documents need a re-index, but %s", len(pending), _busy_detail()
        )
        return None
    await _scan_slot.acquire()
    job = _start_reindex(STARTUP)
    logger.info(
        "startup: re-index %s started in the background for %d documents stored as whole "
        "files or with another embedder than %s",
        job["job_id"],
        len(pending),
        embed_model,
    )
    return job


def schedule_startup_check() -> asyncio.Task:
    global _startup_check
    _startup_check = asyncio.create_task(check_index_on_startup())
    return _startup_check


def cancel_startup_check() -> None:
    if _startup_check is not None and not _startup_check.done():
        _startup_check.cancel()


@router.post(
    "/reindex",
    status_code=202,
    summary="Re-index the stored documents",
    description=(
        "Bring every stored document to the current index layout: a document still "
        "stored as one whole-file entry is split into passages, and a passage embedded "
        "with another model than the running one (embed_model) is embedded again. "
        "Documents already up to date are left alone, so running it twice is a no-op, "
        "and an interrupted run picks up where it stopped. Each changed document bumps "
        "the corpus version. Returns immediately; poll GET /corpus/reindex. Never runs "
        "together with a corpus scan. The service also starts this job by itself at "
        "startup when it finds such passages or whole-file entries (trigger startup), "
        "unless KNOWLEDGE_STORE_REINDEX_ON_STARTUP=0. Requires the X-Corpus-Token header."
    ),
    responses={
        202: {
            "description": "Re-index accepted and running in the background",
            "content": {
                "application/json": {
                    "example": {
                        "job_id": "9f2c...",
                        "state": "running",
                        "embed_model": "fastembed-0.8.1:BAAI/bge-base-en-v1.5",
                    }
                }
            },
        },
        403: {"description": "Missing or invalid X-Corpus-Token"},
        409: {"description": "A corpus scan or a re-index is already running"},
        503: {"description": "CORPUS_SCAN_TOKEN is not configured"},
    },
)
async def reindex_corpus():
    if _scan_slot.locked():
        raise HTTPException(status_code=409, detail=_busy_detail())
    await _scan_slot.acquire()

    job = _start_reindex(REQUESTED)
    logger.info("re-index %s starting with %s", job["job_id"], job["embed_model"])

    return {"job_id": job["job_id"], "state": "running", "embed_model": job["embed_model"]}


@router.get(
    "/reindex",
    summary="Progress of the most recent re-index",
    description=(
        "Totals of the latest re-index: pending documents, and how many were migrated "
        "from whole-file entries, re-embedded, already up to date, or failed. state is "
        "one of idle, running, completed, failed; trigger is request or startup. "
        "Requires the X-Corpus-Token header."
    ),
    responses={
        200: {
            "description": "Latest re-index state",
            "content": {
                "application/json": {
                    "example": {
                        "job_id": "9f2c...",
                        "state": "completed",
                        "trigger": "startup",
                        "embed_model": "fastembed-0.8.1:BAAI/bge-base-en-v1.5",
                        "totals": {
                            "pending": 5,
                            "migrated": 5,
                            "reembedded": 0,
                            "unchanged": 0,
                            "failed": 0,
                        },
                        "failures": [],
                    }
                }
            },
        },
        403: {"description": "Missing or invalid X-Corpus-Token"},
        503: {"description": "CORPUS_SCAN_TOKEN is not configured"},
    },
)
async def reindex_status():
    if _reindex_job is None:
        return {"state": "idle", "embed_model": file_service.EMBED_MODEL}
    return _reindex_job
