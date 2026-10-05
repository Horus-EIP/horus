"""RabbitMQ consumer loops for this agent.

Two long-running consumers read from RabbitMQ:

- :func:`_consume_messages` — pooled task queue (``server.WORK_QUEUE_NAME``)
  shared by every instance of this ``AGENT_TYPE``; each message → run pipeline
  + POST result back to MAS. Honours ``type=cancel`` control messages and
  forwards ``assigned_agent_id`` from the payload so MAS can match the
  database row regardless of which pooled worker actually ran the task.
- :func:`_consume_agent_messages` — inter-agent comms (``agent_comm_{AGENT_ID}``)
  → dispatch to :mod:`agent_server.delegation_bridge`.

Functions deliberately do a lazy ``from agent_server import server`` inside
the body to read current module-level state (``AGENT_ID``, ``WORK_QUEUE_NAME``,
``active_agent``, ``AGENT_TYPE``, ``send_result``). This keeps
``patch("agent_server.server.X")`` working from the tests and matches the
semantics of the original, pre-split implementation where these names lived
next to the consumer.
"""

import asyncio
import base64
import json
import os
import threading
import time as time_module
import uuid
from collections import OrderedDict, deque
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from enum import Enum

import pika
from pika.exceptions import AMQPError, ChannelClosedByBroker

from ai_agents.answer_contract import AgentAnswer, AnswerStatus, answer_of, source_label
from ai_agents.generation_stop import GenerationTimedOut
from config.settings import RABBITMQ_PORT
from core.logger import get_correlation_id, get_logger, set_correlation_id
from core.memory_usage import peak_rss_mb
from core.metrics import agent_errors_total, task_processing_duration, task_processing_total

logger = get_logger("agent_server.consumers")

NOT_FOUND = 404
PRECONDITION_FAILED = 406
DEFAULT_WORK_QUEUE_MAX_LENGTH = 10
DEFAULT_MAX_CONCURRENT_TASKS = 1
_IDLE_POLL_SECONDS = 0.5
_CLAIM_RETRY_SECONDS = 5.0
REMEMBERED_TASK_IDS = 10_000
RESULT_STATUS_BY_ANSWER = {
    AnswerStatus.OK: "completed",
    AnswerStatus.NOT_FOUND: "not_found",
    AnswerStatus.FAILED: "failed",
}


class TaskClaim(str, Enum):
    CLAIMED = "claimed"
    REFUSED = "refused"
    UNAVAILABLE = "unavailable"


def _positive_int_env(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return max(1, int(raw))
    except ValueError:
        logger.warning("Ignoring non-numeric %s=%r", name, raw)
        return default


def work_queue_arguments() -> dict:
    return {
        "x-max-priority": 10,
        "x-max-length": _positive_int_env("WORK_QUEUE_MAX_LENGTH", DEFAULT_WORK_QUEUE_MAX_LENGTH),
        "x-overflow": "reject-publish",
    }


class TaskWorkerPool:
    def __init__(self, max_workers: int, remembered_tasks: int = REMEMBERED_TASK_IDS) -> None:
        self.max_workers = max_workers
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="agent-task"
        )
        self._lock = threading.Lock()
        self._busy = 0
        self._remembered_tasks = remembered_tasks
        self._started: OrderedDict[str, None] = OrderedDict()

    def has_free_slot(self) -> bool:
        with self._lock:
            return self._busy < self.max_workers

    def has_started(self, task_id: str) -> bool:
        with self._lock:
            return task_id in self._started

    def submit(self, job: Callable[[], None], task_id: str | None = None) -> None:
        with self._lock:
            self._busy += 1
            if task_id:
                self._started[task_id] = None
                while len(self._started) > self._remembered_tasks:
                    self._started.popitem(last=False)
        self._executor.submit(job).add_done_callback(self._release)

    def _release(self, _future) -> None:
        with self._lock:
            self._busy -= 1


task_workers = TaskWorkerPool(
    _positive_int_env("AGENT_MAX_CONCURRENT_TASKS", DEFAULT_MAX_CONCURRENT_TASKS)
)
_stop_pulling = threading.Event()

# Per-file caps for the demand-prepend context block. Anything larger is
# truncated with a marker so prompts stay bounded for downstream LLM calls.
_MAX_FILE_CONTEXT_CHARS = 50_000
_MAX_TOTAL_CONTEXT_CHARS = 200_000


class _OrderedStepSender:
    def __init__(self, post: Callable[[dict], None]) -> None:
        self._post = post
        self._pending: deque[dict] = deque()
        self._lock = threading.Lock()
        self._draining = False

    def __call__(self, event: dict) -> None:
        with self._lock:
            self._pending.append(event)
            if self._draining:
                return
            self._draining = True
        try:
            threading.Thread(target=self._drain, daemon=True).start()
        except RuntimeError:
            with self._lock:
                self._draining = False
            raise

    def _drain(self) -> None:
        while True:
            with self._lock:
                if not self._pending:
                    self._draining = False
                    return
                event = self._pending.popleft()
            try:
                self._post(event)
            except Exception:
                logger.debug("Step POST raised", exc_info=True)


def _decode_inline_file(content_b64: str) -> str:
    """Decode base64 inline-file bytes to UTF-8 text. Binary files come back as
    a hex-escaped string so the LLM at least sees that *something* was attached.
    """
    try:
        raw = base64.b64decode(content_b64, validate=True)
    except Exception as exc:
        logger.warning("Inline file base64 decode failed: %s", exc)
        return ""
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        # Best-effort textual representation for binary files. Truncate hard:
        # the LLM gains little from megabytes of hex.
        return raw[:4096].hex()


async def _resolve_attached_files(files: list[dict]) -> list[dict]:
    """Resolve each attached file to (filename, text). Knowledge-store refs go
    through the existing async client; inline files are decoded locally.
    Returns dicts: ``{filename, source, text}``.
    """
    if not files:
        return []
    from ai_agents.knowledge_store_client import KnowledgeStoreClient

    client = KnowledgeStoreClient()
    resolved: list[dict] = []
    for f in files:
        source = (f.get("source") or "").lower()
        name = f.get("filename") or ""
        if not name:
            continue
        doc_id = str(f.get("doc_id") or "").strip()
        if source == "inline":
            text = _decode_inline_file(f.get("content_b64") or "")
        elif source == "knowledge_store":
            text = await _knowledge_store_text(client, doc_id, name)
        else:
            logger.warning("Unknown file source %r for %s; skipping", source, name)
            continue
        if len(text) > _MAX_FILE_CONTEXT_CHARS:
            text = text[:_MAX_FILE_CONTEXT_CHARS] + "\n…[truncated]"
        entry = {"filename": name, "source": source, "text": text}
        if doc_id:
            entry["doc_id"] = doc_id
        resolved.append(entry)
    return resolved


async def _knowledge_store_text(client, doc_id: str, name: str) -> str:
    if doc_id:
        try:
            hit = await client.resolve_by_doc_id(doc_id)
            text = (hit or {}).get("data") or ""
        except Exception as exc:
            logger.warning("KS resolve by doc_id failed for %s (%s): %s", name, doc_id, exc)
            text = ""
        if text:
            return text
        logger.info("KS has no text for doc_id %s; resolving %s by its filename", doc_id, name)
    try:
        hit = await client.resolve_by_filename(name)
        return (hit or {}).get("data") or ""
    except Exception as exc:
        logger.warning("KS resolve failed for %s: %s", name, exc)
        return ""


def _prepend_files_to_demand(demand: str, resolved: list[dict]) -> str:
    """Wrap the user's demand with an `Attached Files` context block.

    The block sits *before* the demand so the LLM treats it as background.
    Empty texts (failed resolution, etc.) are still listed so the model knows
    the file was attached but couldn't be read.
    """
    if not resolved:
        return demand
    return _attached_files_block(resolved) + "\n" + (demand or "")


def _attached_files_block(resolved: list[dict]) -> str:
    pieces: list[str] = ["--- Attached Files ---"]
    total = 0
    for index, r in enumerate(resolved, start=1):
        header = f"[{source_label(index)}] [file: {r['filename']} (source={r['source']})]"
        body = r["text"] or "(no content available)"
        budget = _MAX_TOTAL_CONTEXT_CHARS - total - len(header) - 2
        if budget <= 0:
            pieces.append("…[remaining attached files omitted to stay within prompt budget]")
            break
        if len(body) > budget:
            body = body[:budget] + "\n…[truncated]"
        pieces.append(header)
        pieces.append(body)
        total += len(header) + len(body) + 2
    pieces.append("--- End Attached Files ---\n")
    return "\n".join(pieces)


# Reconnect settings for the blocking consumers. A RabbitMQ restart or a
# transient network blip force-closes the connection ("CONNECTION_FORCED ...
# shutdown"); the supervisor below re-establishes it instead of letting the
# consumer thread die (which silently stops the agent from processing tasks
# until the container is manually restarted).
_CONSUMER_RECONNECT_BASE_DELAY = 2.0
_CONSUMER_RECONNECT_MAX_DELAY = 30.0
_CONSUMER_STABLE_SESSION_SECONDS = 60.0


def _run_consumer_supervisor(session, label: str) -> None:
    """Run a blocking-consumer ``session`` forever, reconnecting on failure.

    ``session`` runs one connect→consume cycle and returns ``True`` to stop
    permanently (e.g. a misconfiguration that reconnecting can't fix) or
    ``False`` when the connection dropped and it should be re-established.
    Backoff escalates on rapid failures and resets after a session that stayed
    up long enough to count as healthy.
    """
    delay = _CONSUMER_RECONNECT_BASE_DELAY
    while True:
        started = time_module.monotonic()
        if session():
            return
        if time_module.monotonic() - started >= _CONSUMER_STABLE_SESSION_SECONDS:
            delay = _CONSUMER_RECONNECT_BASE_DELAY
        logger.warning("%s disconnected; reconnecting in %.0fs", label, delay)
        time_module.sleep(delay)
        delay = min(delay * 2, _CONSUMER_RECONNECT_MAX_DELAY)


def _consume_messages():
    """Supervise the task consumer, reconnecting across broker restarts."""
    _run_consumer_supervisor(_consume_messages_session, "Task consumer")


def _consume_messages_session() -> bool:
    from agent_server import server
    from agent_server.profiles import unique_agent_types

    if not server.AGENT_ID:
        logger.error("Cannot start consumer: AGENT_ID not set")
        return True

    types = unique_agent_types() or ["general"]
    queue_to_type: dict[str, str] = {
        server.work_queue_name_for_type(t): t for t in types
    }

    try:
        connection = _open_connection()
        channel = connection.channel()
        for queue_name in queue_to_type:
            channel = _declare_work_queue(connection, channel, queue_name)
        logger.info(
            "RabbitMQ task worker started (%d task(s) at a time), pulling from %d queue(s): %s",
            task_workers.max_workers,
            len(queue_to_type),
            ", ".join(queue_to_type),
        )
        _pull_tasks(connection, channel, queue_to_type, task_workers)
        return True
    except (AMQPError, OSError) as e:
        logger.warning("Task consumer connection lost (%s); will reconnect", e)
        agent_errors_total.labels(error_type="rabbitmq").inc()
        return False
    except Exception as e:
        logger.error(f"Error in RabbitMQ consumer: {e}", exc_info=True)
        agent_errors_total.labels(error_type="rabbitmq").inc()
        return False


def _open_connection():
    credentials = pika.PlainCredentials(
        os.getenv("RABBITMQ_USER", "guest"), os.getenv("RABBITMQ_PASSWORD", "guest")
    )
    return pika.BlockingConnection(
        pika.ConnectionParameters(
            host=os.getenv("RABBITMQ_HOST", "localhost"),
            port=RABBITMQ_PORT,
            credentials=credentials,
            heartbeat=600,
            blocked_connection_timeout=300,
        )
    )


def _declare_work_queue(connection, channel, queue_name: str):
    try:
        channel.queue_declare(queue=queue_name, passive=True)
        return channel
    except ChannelClosedByBroker as exc:
        if exc.reply_code != NOT_FOUND:
            raise
    channel = connection.channel()
    try:
        channel.queue_declare(
            queue=queue_name,
            passive=False,
            durable=True,
            exclusive=False,
            auto_delete=False,
            arguments=work_queue_arguments(),
        )
        return channel
    except ChannelClosedByBroker as exc:
        if exc.reply_code != PRECONDITION_FAILED:
            raise
    channel = connection.channel()
    channel.queue_declare(queue=queue_name, passive=True)
    return channel


def _pull_tasks(connection, channel, queue_to_type: dict[str, str], workers) -> None:
    queues = list(queue_to_type)
    first = 0
    while not _stop_pulling.is_set():
        if not workers.has_free_slot():
            connection.process_data_events(time_limit=_IDLE_POLL_SECONDS)
            continue
        pause = _IDLE_POLL_SECONDS
        for offset in range(len(queues)):
            queue_name = queues[(first + offset) % len(queues)]
            method, properties, body = channel.basic_get(queue=queue_name, auto_ack=False)
            if method is None:
                continue
            first = (first + offset + 1) % len(queues)
            pause = _handle_delivery(
                channel, method, properties, body, queue_to_type[queue_name], workers
            )
            break
        if pause:
            connection.process_data_events(time_limit=pause)


def _delivery_key(task_id: str, attempt) -> str:
    try:
        number = int(attempt)
    except (TypeError, ValueError):
        number = 1
    return task_id if number <= 1 else f"{task_id}#attempt-{number}"


def _decode_payload(body) -> dict:
    try:
        return json.loads(body.decode("utf-8")) if body else {}
    except Exception:
        return {"demand": body.decode("utf-8")}


def _adopt_assigned_profile(payload: dict, queue_type: str) -> None:
    external_agent_id = payload.get("assigned_agent_id")
    external_api_key = payload.get("assigned_agent_api_key")
    if external_agent_id and external_api_key:
        from agent_server.profiles import upsert_external_profile

        upsert_external_profile(
            agent_id=external_agent_id,
            api_key=external_api_key,
            name=payload.get("assigned_agent_name") or "",
            agent_type=payload.get("assigned_agent_type") or queue_type,
            skills=payload.get("assigned_agent_skills") or [],
        )


def _handle_delivery(channel, method, properties, body, queue_type: str, workers) -> float:
    from agent_server import server

    payload = _decode_payload(body)
    if payload.get("type") == "cancel":
        logger.info("Received cancel control message (task_id=%s)", payload.get("task_id"))
        channel.basic_ack(delivery_tag=method.delivery_tag)
        return 0.0

    task_id = payload.get("task_id")
    if not (payload.get("demand") or payload.get("query")):
        logger.warning("RabbitMQ task message has no demand/query (task_id=%s).", task_id)
        channel.basic_ack(delivery_tag=method.delivery_tag)
        return 0.0

    _adopt_assigned_profile(payload, queue_type)
    delivery = _delivery_key(task_id, payload.get("attempt")) if task_id else None
    if task_id:
        if workers.has_started(delivery):
            logger.info(
                "Task %s was delivered again after this worker started it; its message is dropped",
                task_id,
            )
            channel.basic_ack(delivery_tag=method.delivery_tag)
            return 0.0
        claim = server.claim_task(task_id, payload.get("assigned_agent_id"))
        if claim is TaskClaim.UNAVAILABLE:
            logger.warning(
                "MAS did not confirm the claim of task %s; its message goes back to the queue",
                task_id,
            )
            channel.basic_nack(delivery_tag=method.delivery_tag, requeue=True)
            return _CLAIM_RETRY_SECONDS
        if claim is TaskClaim.REFUSED:
            logger.info(
                "Task %s is already claimed, finished or cancelled; its message is dropped",
                task_id,
            )
            channel.basic_ack(delivery_tag=method.delivery_tag)
            return 0.0

    headers = getattr(properties, "headers", None) or {}
    correlation_id = headers.get("X-Request-ID")
    try:
        channel.basic_ack(delivery_tag=method.delivery_tag)
    finally:
        workers.submit(lambda: _run_task(payload, queue_type, correlation_id), delivery)
    return 0.0


def _task_dict(task_id: str, demand: str, payload: dict, resolved_files: list[dict]) -> dict:
    effective_demand = _prepend_files_to_demand(demand, resolved_files)
    first_file = resolved_files[0] if resolved_files else {}
    any_file_readable = any(f.get("text") for f in resolved_files)
    return {
        "task_id": task_id,
        "query": effective_demand or payload.get("query", ""),
        "demand": demand,
        "attached_context": (
            _attached_files_block(resolved_files) if any_file_readable else None
        ),
        "retrieval_query": payload.get("retrieval_query"),
        "operation": payload.get("operation"),
        "expression": payload.get("expression"),
        "file_url": payload.get("file_url"),
        "file_content": payload.get("file_content") or first_file.get("text"),
        "file_type": payload.get("file_type"),
        "filename": payload.get("filename") or first_file.get("filename"),
        "files": resolved_files,
        "text": payload.get("text"),
        "max_sentences": payload.get("max_sentences"),
        "format": payload.get("format"),
        "extraction_type": payload.get("extraction_type"),
        "analysis_type": payload.get("analysis_type"),
    }


async def _answer(payload: dict, queue_type: str, task_id: str, demand: str) -> AgentAnswer:
    from agent_server import server

    resolved_files = await _resolve_attached_files(payload.get("files") or [])
    task_dict = _task_dict(task_id, demand, payload, resolved_files)
    op = (task_dict.get("operation") or "").strip().lower()
    effective_type = queue_type
    pipeline = server.get_pipeline_for_type(queue_type)
    if queue_type in ("researcher", "analyst", "writer") and not op:
        logger.info(
            "Specialist task without 'operation' → general RAG fallback "
            "(queue_type=%s task_id=%s)",
            queue_type,
            task_id,
        )
        effective_type = "general"
        pipeline = server.get_pipeline_for_type("general")
    if effective_type == "general":
        return answer_of(await pipeline.process_task(task_dict))
    if effective_type in ("researcher", "analyst", "writer"):
        return answer_of(
            await pipeline.process_request(
                task_type=op,
                data=task_dict.get("query"),
                extra_parameters=task_dict,
            )
        )
    raise ValueError(f"Unsupported queue type: {effective_type}")


def _report_failure(
    emit_step: Callable[[dict], None],
    title: str,
    detail: str,
    phase: str,
) -> None:
    try:
        emit_step(
            {
                "step_type": "error",
                "title": title,
                "detail": detail,
                "timestamp": None,
                "metadata": {"phase": phase},
            }
        )
    except Exception:
        logger.debug("Failure step could not be emitted", exc_info=True)


def _send_failed_result(text: str, conversation_id, task_id: str, payload: dict, reason: str) -> None:
    from agent_server import server

    try:
        server.send_result(
            text,
            str(conversation_id),
            str(task_id),
            assigned_agent_id=payload.get("assigned_agent_id"),
            skill_used=payload.get("skill_used") or payload.get("operation"),
            status="failed",
            reason=reason,
        )
    except Exception as send_exc:
        logger.error("Failed to send error result to MAS: %s", send_exc)


def _run_task(payload: dict, queue_type: str, correlation_id: str | None) -> None:
    from agent_server import server
    from agent_server.profiles import (
        current_agent_name,
        current_persona,
        current_step_emitter,
        get_profile_by_agent_id,
    )

    if correlation_id:
        set_correlation_id(correlation_id)
    demand = payload.get("demand", "")
    conversation_id = payload.get("conversation_id") or ""
    task_id = payload.get("task_id") or ("task_" + uuid.uuid4().hex)
    assigned_agent_id = payload.get("assigned_agent_id")
    logger.info(
        "Received task on %s queue: task_id=%s, conv=%s, demand_len=%d, corr=%s",
        queue_type,
        task_id,
        conversation_id,
        len(demand),
        get_correlation_id(),
    )

    active_profile = get_profile_by_agent_id(assigned_agent_id)
    persona_token = current_persona.set(active_profile.system_prompt if active_profile else None)
    name_token = current_agent_name.set(active_profile.name if active_profile else None)
    emit_step = _OrderedStepSender(
        lambda event: server.send_step(
            event, conversation_id, task_id, assigned_agent_id=assigned_agent_id
        )
    )
    emitter_token = current_step_emitter.set(emit_step)
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    start_time = time_module.time()
    try:
        answer = loop.run_until_complete(_answer(payload, queue_type, task_id, demand))
        processing_duration = time_module.time() - start_time
        task_processing_duration.observe(processing_duration)
        if answer.status is AnswerStatus.FAILED:
            task_processing_total.labels(status="error").inc()
            agent_errors_total.labels(error_type=answer.reason or "error").inc()
            logger.warning(
                "Task answer failed: task_id=%s reason=%s duration=%.2fs peak_rss_mb=%s",
                task_id,
                answer.reason,
                processing_duration,
                peak_rss_mb(),
            )
            _report_failure(emit_step, "Answer failed", answer.answer, "generation")
            _send_failed_result(
                answer.answer, conversation_id, task_id, payload, answer.reason or "error"
            )
            return
        task_processing_total.labels(status="success").inc()
        logger.info(
            "Task processed (%s): task_id=%s duration=%.2fs peak_rss_mb=%s",
            queue_type,
            task_id,
            processing_duration,
            peak_rss_mb(),
        )
        server.send_result(
            answer.answer,
            conversation_id,
            task_id,
            assigned_agent_id=assigned_agent_id,
            skill_used=payload.get("skill_used") or payload.get("operation"),
            status=RESULT_STATUS_BY_ANSWER[answer.status],
            reason=answer.reason,
            sources=answer.sources,
        )
    except GenerationTimedOut as timed_out:
        task_processing_duration.observe(time_module.time() - start_time)
        task_processing_total.labels(status="error").inc()
        agent_errors_total.labels(error_type="timeout").inc()
        logger.warning(
            "Task timed out: task_id=%s after=%.0fs peak_rss_mb=%s",
            task_id,
            timed_out.seconds,
            peak_rss_mb(),
        )
        _report_failure(emit_step, "Answer timed out", str(timed_out), "generation")
        _send_failed_result(str(timed_out), conversation_id, task_id, payload, "timeout")
    except Exception as e:
        task_processing_duration.observe(time_module.time() - start_time)
        task_processing_total.labels(status="error").inc()
        agent_errors_total.labels(error_type="task_processing").inc()
        logger.error(
            "Task processing failed: task_id=%s error=%s peak_rss_mb=%s",
            task_id,
            str(e),
            peak_rss_mb(),
            exc_info=True,
        )
        _report_failure(emit_step, "Task processing failed", str(e), "pipeline")
        _send_failed_result(
            f"Agent processing failed: {e}", conversation_id, task_id, payload, "error"
        )
    finally:
        try:
            current_persona.reset(persona_token)
            current_agent_name.reset(name_token)
            current_step_emitter.reset(emitter_token)
        except (LookupError, ValueError):
            pass
        asyncio.set_event_loop(None)
        loop.close()


def _consume_agent_messages():
    """Supervise the inter-agent message consumer, reconnecting across restarts."""
    _run_consumer_supervisor(_consume_agent_messages_session, "Agent message consumer")


def _consume_agent_messages_session() -> bool:
    """Consume inter-agent messages from ``agent_comm_{AGENT_ID}`` (delegation).

    Returns ``True`` to stop permanently, ``False`` if the connection dropped.
    """
    from agent_server import server
    from agent_server.delegation_bridge import _process_delegation_message

    if not server.AGENT_ID:
        logger.error("Cannot start agent message consumer: AGENT_ID not set")
        return True  # permanent — reconnecting can't set AGENT_ID

    try:
        rabbit_host = os.getenv("RABBITMQ_HOST", "localhost")
        rabbit_user = os.getenv("RABBITMQ_USER", "guest")
        rabbit_pass = os.getenv("RABBITMQ_PASSWORD", "guest")
        credentials = pika.PlainCredentials(rabbit_user, rabbit_pass)
        connection = pika.BlockingConnection(
            pika.ConnectionParameters(
                host=rabbit_host,
                port=RABBITMQ_PORT,
                credentials=credentials,
                heartbeat=600,
                blocked_connection_timeout=300,
            )
        )
        channel = connection.channel()
        queue_name = f"agent_comm_{server.AGENT_ID}"
        channel.queue_declare(
            queue=queue_name,
            passive=False,
            durable=True,
            exclusive=False,
            auto_delete=False,
            arguments={"x-max-priority": 10},
        )

        def _on_agent_message(ch, method, properties, body):
            try:
                payload = json.loads(body.decode("utf-8")) if body else {}
            except Exception:
                logger.error("Failed to decode agent message")
                ch.basic_ack(delivery_tag=method.delivery_tag)
                return

            message_type = payload.get("message_type", "")
            message_id = payload.get("id", "")
            sender = payload.get("sender_agent_id", "")

            logger.info(
                f"Received agent message: id={message_id}, type={message_type}, "
                f"from={sender}"
            )

            if message_type == "delegation":
                _process_delegation_message(payload)
            else:
                logger.warning(f"Unknown agent message type: {message_type}")

            ch.basic_ack(delivery_tag=method.delivery_tag)

        channel.basic_qos(prefetch_count=1)
        channel.basic_consume(queue=queue_name, on_message_callback=_on_agent_message)
        logger.info(f"Agent message consumer started on queue '{queue_name}'")
        channel.start_consuming()
        return True  # returned without error → graceful stop
    except (AMQPError, OSError) as e:
        # Broker restart / blip / socket drop — reconnect, don't kill the thread.
        logger.warning("Agent message consumer connection lost (%s); will reconnect", e)
        agent_errors_total.labels(error_type="rabbitmq").inc()
        return False
    except Exception as e:
        logger.error(f"Error in agent message consumer: {e}", exc_info=True)
        agent_errors_total.labels(error_type="rabbitmq").inc()
        return False
