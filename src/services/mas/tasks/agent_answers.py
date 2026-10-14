import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from core.logger import get_logger
from core.task_events import TASK_EVENTS_TTL_SECONDS
from db.redis_client import redis_db
from schemas.schemas import TaskResultStatus

logger = get_logger("agent_answers")

NOT_IN_DOCUMENTS_TEXT = "The documents don't contain this information."
RETRYING_STATUS = "retrying"
MAX_ANSWER_ATTEMPTS = 2
DISPATCH_RECORD_TTL_SECONDS = TASK_EVENTS_TTL_SECONDS
RETRIEVAL_QUERY_MAX_CHARS = 2000
FAILURES_NOT_RETRIED = frozenset({"timeout"})
CREDENTIAL_KEYS = frozenset({"assigned_agent_api_key"})
INLINE_FILE_SOURCE = "inline"

_QUERY_WORD = re.compile(r"[\w$€£%][\w$€£%.'’-]*")
_QUERY_NOISE = re.compile(r"[^\w$€£%]+")
STOPWORDS = frozenset("""
    a about above after again all also am an and any are as at be been before being
    below between both but by can could did do does doing down during each few for
    from further give had has have having he her here hers him his how i if in into
    is it its itself just list me more most my no nor not now of off on once only or
    other our ours out over own please same she should show so some such summarise
    summarize tell than that the their theirs them then there these they this those
    through to too under until up us very was we were what when where which while who
    whom why will with would you your yours describe explain
    """.split())


@dataclass(frozen=True)
class RetryPlan:
    payload: dict[str, Any]
    detail: str

    @property
    def attempt(self) -> int:
        return int(self.payload["attempt"])


def source_key(source: dict[str, Any]) -> str:
    chunk_id = source.get("chunk_id")
    if chunk_id:
        return f"chunk:{chunk_id}"
    return f"document:{source.get('doc_id') or ''}:{source.get('title') or ''}"


def merge_sources(
    source_lists: Iterable[list[dict[str, Any]] | None],
) -> list[dict[str, Any]] | None:
    merged: dict[str, dict[str, Any]] = {}
    sent_any = False
    for sources in source_lists:
        if sources is None:
            continue
        sent_any = True
        for source in sources:
            if isinstance(source, dict):
                merged.setdefault(source_key(source), dict(source))
    return list(merged.values()) if sent_any else None


def keyword_query(text: str) -> str | None:
    words: list[str] = []
    seen: set[str] = set()
    for raw in _QUERY_WORD.findall(text or ""):
        word = raw.strip(".'’-")
        lowered = word.lower()
        if not word or lowered in STOPWORDS or lowered in seen:
            continue
        seen.add(lowered)
        words.append(word)
    query = " ".join(words)[:RETRIEVAL_QUERY_MAX_CHARS].strip()
    return query or None


def _comparable(query: str) -> str:
    return _QUERY_NOISE.sub(" ", query.lower()).strip()


def alternative_retrieval_query(
    payload: dict[str, Any], user_question: str | None
) -> str | None:
    used = payload.get("retrieval_query") or payload.get("demand") or ""
    for candidate in (user_question, keyword_query(used)):
        if candidate and _comparable(candidate) != _comparable(used):
            return candidate[:RETRIEVAL_QUERY_MAX_CHARS]
    return None


def dispatch_record_key(task_id: str) -> str:
    return f"horus:task:{task_id}:dispatch"


def _replayable_payload(payload: dict[str, Any]) -> dict[str, Any] | None:
    files = payload.get("files") or []
    if any(
        isinstance(entry, dict) and entry.get("source") == INLINE_FILE_SOURCE
        for entry in files
    ):
        return None
    return {key: value for key, value in payload.items() if key not in CREDENTIAL_KEYS}


def _attempt_of(payload: dict[str, Any]) -> int:
    try:
        return max(1, int(payload.get("attempt") or 1))
    except (TypeError, ValueError):
        return 1


def remember_dispatch(task_id: str, payload: dict[str, Any]) -> None:
    record = {"attempt": _attempt_of(payload), "payload": _replayable_payload(payload)}
    try:
        redis_db.set(
            dispatch_record_key(task_id),
            json.dumps(record, default=str),
            ex=DISPATCH_RECORD_TTL_SECONDS,
        )
    except Exception:
        logger.warning(
            "Could not keep the dispatch of task %s; it will not be tried a second time",
            task_id,
            exc_info=True,
        )


def recall_dispatch(task_id: str) -> dict[str, Any] | None:
    try:
        stored = redis_db.get(dispatch_record_key(task_id))
    except Exception:
        logger.warning("Could not read the dispatch of task %s", task_id, exc_info=True)
        return None
    if not stored:
        return None
    try:
        record = json.loads(stored)
    except ValueError:
        return None
    return record if isinstance(record, dict) else None


def _retry_detail(status: TaskResultStatus, reason: str | None, new_query: bool) -> str:
    if status == TaskResultStatus.NOT_FOUND:
        return (
            "The documents found did not answer it; searching again with another query."
        )
    again = "with another query" if new_query else "once more"
    return f"The answer failed ({reason or 'error'}); trying {again}."


def retry_plan(
    record: dict[str, Any] | None,
    status: TaskResultStatus,
    reason: str | None,
    user_question: str | None,
) -> RetryPlan | None:
    if status == TaskResultStatus.COMPLETED or record is None:
        return None
    payload = record.get("payload")
    if not isinstance(payload, dict):
        return None
    attempt = _attempt_of(record)
    if attempt >= MAX_ANSWER_ATTEMPTS:
        return None
    if status == TaskResultStatus.FAILED and reason in FAILURES_NOT_RETRIED:
        return None
    query = alternative_retrieval_query(payload, user_question)
    if query is None and status == TaskResultStatus.NOT_FOUND:
        return None
    retry_payload = {**payload, "attempt": attempt + 1}
    if query is not None:
        retry_payload["retrieval_query"] = query
    return RetryPlan(retry_payload, _retry_detail(status, reason, query is not None))
