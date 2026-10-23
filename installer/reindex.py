from __future__ import annotations

import math
import time
from collections.abc import Callable
from dataclasses import dataclass

import smoke
from common import Log, elapsed

TOKEN_HEADER = "X-Corpus-Token"
TOKEN_KEY = "CORPUS_SCAN_TOKEN"
STARTUP_KEY = "KNOWLEDGE_STORE_REINDEX_ON_STARTUP"
OFF_VALUES = frozenset({"0", "false", "no", "off"})
FINISHED = frozenset({"completed", "failed"})
DENIED = frozenset({403, 503})
BUSY = 409
POLL_SECONDS = 3.0
POST_EVERY_SECONDS = 30.0
SHORTEST_WAIT_SECONDS = 600.0
UNKNOWN_CORPUS_WAIT_SECONDS = 3600.0
WAIT_MARGIN = 3
ASK_ABOVE_DOCUMENTS = 100
CHUNK_CHARACTERS = 1000
CHUNK_OVERLAP = 200
CPU_PASSAGES_PER_SECOND = 4.0
SHOWN_FAILURES = 5


@dataclass(frozen=True)
class Corpus:
    documents: int
    passages: int

    @property
    def cpu_seconds(self) -> float:
        return self.passages / CPU_PASSAGES_PER_SECOND


def passages_in(size: object) -> int:
    if isinstance(size, bool) or not isinstance(size, (int, float)) or size <= 0:
        return 1
    return max(1, math.ceil((size - CHUNK_OVERLAP) / (CHUNK_CHARACTERS - CHUNK_OVERLAP)))


def passages_of(document: object) -> int:
    if not isinstance(document, dict):
        return 1
    counted = document.get("chunk_count")
    if isinstance(counted, int) and not isinstance(counted, bool) and counted > 0:
        return counted
    return passages_in(document.get("size"))


def stored_corpus(ks: str) -> Corpus | None:
    try:
        res = smoke.http("GET", f"{ks}/file")
    except smoke.Unreachable:
        return None
    body = res.json() if res.status == 200 else None
    documents = body.get("documents") if isinstance(body, dict) else None
    if not isinstance(documents, list):
        return None
    return Corpus(len(documents), sum(passages_of(document) for document in documents))


def about(seconds: float) -> str:
    if seconds < 60:
        return "under a minute"
    return f"about {elapsed(math.ceil(seconds / 60) * 60)}"


def announce(log: Log, corpus: Corpus | None, towards_local: bool) -> None:
    if corpus is None:
        log.say(
            "  The knowledge store did not answer, so how many documents it holds is "
            "unknown. Whatever it holds is re-embedded after the switch."
        )
        return
    log.events.emit(
        "reembed",
        documents=corpus.documents,
        passages=corpus.passages,
        cpu_seconds=round(corpus.cpu_seconds),
    )
    if corpus.documents == 0:
        log.say("  The knowledge store holds no document, so nothing needs re-embedding.")
        return
    log.say(
        f"  The knowledge store holds {corpus.documents} documents ({corpus.passages} "
        "passages). They are re-embedded with the new mode's embeddings before the "
        "smoke test."
    )
    cpu = about(corpus.cpu_seconds)
    if towards_local:
        log.say(
            f"  On the processor that takes {cpu} ({CPU_PASSAGES_PER_SECOND:g} passages "
            "per second, measured)."
        )
    else:
        log.say(
            f"  llm-mock does it in seconds. Switching back to local later re-embeds "
            f"them on the processor again: {cpu}."
        )


def needs_confirmation(corpus: Corpus | None) -> bool:
    return corpus is None or corpus.documents > ASK_ABOVE_DOCUMENTS


def patience(corpus: Corpus | None) -> float:
    if corpus is None:
        return UNKNOWN_CORPUS_WAIT_SECONDS
    return max(SHORTEST_WAIT_SECONDS, WAIT_MARGIN * corpus.cpu_seconds)


def runs_at_start(setting: str | None) -> bool:
    return (setting or "1").strip().lower() not in OFF_VALUES


def request(ks: str, token: str, method: str) -> smoke.Response | None:
    try:
        return smoke.http(
            method,
            f"{ks}/corpus/reindex",
            data=b"" if method == "POST" else None,
            headers={TOKEN_HEADER: token},
        )
    except smoke.Unreachable:
        return None


def denied(log: Log, res: smoke.Response) -> bool:
    if res.status not in DENIED:
        return False
    body = res.json()
    reason = body.get("error") if isinstance(body, dict) else res.text()
    log.warn(
        f"The installer cannot follow the knowledge store's re-index "
        f"(HTTP {res.status}: {reason}). The smoke test runs without waiting for it."
    )
    return True


def done_of(job: dict) -> tuple[int, int, int]:
    totals = job.get("totals") if isinstance(job.get("totals"), dict) else {}
    done = sum(
        int(totals.get(key) or 0) for key in ("migrated", "reembedded", "unchanged", "failed")
    )
    return done, int(totals.get("pending") or 0), int(totals.get("failed") or 0)


def retry_advice(startup: bool) -> str:
    if startup:
        return "the next start of Horus tries them again"
    return (
        "KNOWLEDGE_STORE_REINDEX_ON_STARTUP is off, so run scripts/reindex-knowledge-store.py "
        "or this switch again to finish"
    )


def report(log: Log, job: dict, seconds: float, startup: bool) -> None:
    done, pending, failed = done_of(job)
    log.events.emit("reindex", state=job.get("state"), done=done, pending=pending, failed=failed)
    if job.get("state") == "failed":
        log.warn(
            f"The knowledge store's re-index stopped after {elapsed(seconds)}: "
            f"{job.get('error') or 'no reason given'}. Search may mix old and new vectors; "
            f"{retry_advice(startup)}."
        )
    elif failed:
        names = ", ".join(
            str(item.get("doc_id"))
            for item in (job.get("failures") or [])[:SHOWN_FAILURES]
            if isinstance(item, dict)
        )
        log.warn(
            f"{failed} of {pending} documents could not be re-embedded ({names}). They keep "
            f"their old vectors; {retry_advice(startup)}."
        )
    elif pending:
        log.ok(
            f"Re-embedded {pending} documents with {job.get('embed_model')} in {elapsed(seconds)}"
        )
    else:
        log.ok(f"Every stored document already uses {job.get('embed_model')}: nothing to re-embed")


def follow(
    log: Log,
    ks: str,
    token: str,
    start_now: bool,
    may_start: bool,
    startup: bool,
    wait_seconds: float,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> dict | None:
    began = clock()
    must_start = start_now
    posted_at: float | None = None
    shown: tuple | None = None
    told_busy = False
    job: dict | None = None
    while True:
        if must_start and (posted_at is None or clock() - posted_at >= POST_EVERY_SECONDS):
            res = request(ks, token, "POST")
            posted_at = clock()
            must_start = False
            if res is not None and denied(log, res):
                return None
            if res is not None and res.status == BUSY and not told_busy:
                told_busy = True
                log.say(
                    "  The knowledge store is busy with a corpus scan or another re-index; "
                    "the installer waits for it."
                )
        res = request(ks, token, "GET")
        if res is not None and denied(log, res):
            return None
        answer = res.json() if res is not None and res.status == 200 else None
        if isinstance(answer, dict):
            job = answer
            state = job.get("state")
            if state in FINISHED:
                report(log, job, clock() - began, startup)
                return job
            if state == "idle":
                if not may_start:
                    return None
                must_start = True
            elif state == "running" and (job.get("job_id"), *done_of(job)) != shown:
                shown = (job.get("job_id"), *done_of(job))
                done, pending, failed = done_of(job)
                log.say(f"  re-embedding the stored documents: {done}/{pending or '?'}")
                log.events.emit(
                    "reindex", state="running", done=done, pending=pending, failed=failed
                )
        if clock() - began >= wait_seconds:
            log.warn(
                f"The knowledge store's re-index did not end within {elapsed(wait_seconds)}; "
                "the smoke test runs without waiting longer."
            )
            return job
        sleep(POLL_SECONDS)
