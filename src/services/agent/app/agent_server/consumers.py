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

import pika

from config.settings import RABBITMQ_PORT
from core.logger import get_correlation_id, get_logger, set_correlation_id
from core.metrics import agent_errors_total, task_processing_duration, task_processing_total

logger = get_logger("agent_server.consumers")

# Per-file caps for the demand-prepend context block. Anything larger is
# truncated with a marker so prompts stay bounded for downstream LLM calls.
_MAX_FILE_CONTEXT_CHARS = 50_000
_MAX_TOTAL_CONTEXT_CHARS = 200_000


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
        if source == "inline":
            text = _decode_inline_file(f.get("content_b64") or "")
        elif source == "knowledge_store":
            try:
                hit = await client.resolve_by_filename(name)
                text = (hit or {}).get("text") or ""
            except Exception as exc:
                logger.warning("KS resolve failed for %s: %s", name, exc)
                text = ""
        else:
            logger.warning("Unknown file source %r for %s; skipping", source, name)
            continue
        if len(text) > _MAX_FILE_CONTEXT_CHARS:
            text = text[:_MAX_FILE_CONTEXT_CHARS] + "\n…[truncated]"
        resolved.append({"filename": name, "source": source, "text": text})
    return resolved


def _prepend_files_to_demand(demand: str, resolved: list[dict]) -> str:
    """Wrap the user's demand with an `Attached Files` context block.

    The block sits *before* the demand so the LLM treats it as background.
    Empty texts (failed resolution, etc.) are still listed so the model knows
    the file was attached but couldn't be read.
    """
    if not resolved:
        return demand
    pieces: list[str] = ["--- Attached Files ---"]
    total = 0
    for r in resolved:
        header = f"[file: {r['filename']} (source={r['source']})]"
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
    return "\n".join(pieces) + "\n" + (demand or "")


def _consume_messages():
    """Consume tasks from this agent's RabbitMQ queue and run them through the pipeline.

    Each message is a JSON payload with at least ``demand`` and
    ``conversation_id``. Result is POSTed back via ``send_result``.
    """
    from agent_server import server  # lazy: state + send_result live there
    from agent_server.profiles import unique_agent_types

    if not server.AGENT_ID:
        logger.error("Cannot start consumer: AGENT_ID not set")
        return

    # Which work queues to subscribe to depends on which profile types are
    # registered. ``unique_agent_types()`` is e.g. ["general", "analyst",
    # "writer", "researcher"] for the default 5-profile lineup — one channel,
    # one consumer-tag per queue, all sharing the same Qwen.
    types = unique_agent_types() or ["general"]
    queue_to_type: dict[str, str] = {
        server.work_queue_name_for_type(t): t for t in types
    }

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
        for queue_name in queue_to_type:
            channel.queue_declare(
                queue=queue_name,
                passive=False,
                durable=True,
                exclusive=False,
                auto_delete=False,
                arguments={"x-max-priority": 10},
            )

        def _make_on_message(queue_type: str):
            """Bind ``queue_type`` into the per-message handler closure.

            Each subscribed queue gets its own callback that knows which type
            of pipeline to run for tasks it receives.
            """

            def _on_message(ch, method, properties, body):
                try:
                    payload = json.loads(body.decode("utf-8")) if body else {}
                except Exception:
                    payload = {"demand": body.decode("utf-8")}

                # Cancel control messages share the work queue. They carry no
                # demand/conversation_id; just ack and move on.
                if payload.get("type") == "cancel":
                    logger.info(
                        "Received cancel control message (task_id=%s)",
                        payload.get("task_id"),
                    )
                    ch.basic_ack(delivery_tag=method.delivery_tag)
                    return

                demand = payload.get("demand", "")
                # Standalone tasks publish a null/missing conversation_id;
                # normalise to "" so downstream code treats it uniformly.
                conversation_id = payload.get("conversation_id") or ""
                task_id = payload.get("task_id") or ("task_" + uuid.uuid4().hex)
                if not (demand or payload.get("query")):
                    logger.warning(
                        "RabbitMQ task message has no demand/query (task_id=%s).",
                        task_id,
                    )
                    ch.basic_ack(delivery_tag=method.delivery_tag)
                    return

                corr_id = properties.headers.get("X-Request-ID") if properties.headers else None
                if corr_id:
                    set_correlation_id(corr_id)

                logger.info(
                    "Received task on %s queue: task_id=%s, conv=%s, demand_len=%d, corr=%s",
                    queue_type,
                    task_id,
                    conversation_id,
                    len(demand),
                    get_correlation_id(),
                )

                # If MAS minted a new specialist for this task it ships the
                # credentials inline. Adopt them into our profile registry so
                # heartbeats + result POSTs use the right identity going
                # forward (no MAS round-trip needed on subsequent tasks).
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

                # Bind the active profile to a contextvar so the LLM layer
                # can read its persona without every helper accepting a new
                # arg. The reset token is held in this frame so the binding
                # is scoped to this task only.
                from agent_server.profiles import (
                    current_agent_name,
                    current_persona,
                    current_step_emitter,
                    get_profile_by_agent_id,
                )

                active_profile = get_profile_by_agent_id(
                    payload.get("assigned_agent_id")
                )
                persona_token = current_persona.set(
                    active_profile.system_prompt if active_profile else None
                )
                name_token = current_agent_name.set(
                    active_profile.name if active_profile else None
                )

                # Fire-and-forget HTTP emitter for "thought process" steps.
                # Runs the POST on a daemon thread so pipeline work never
                # waits on MAS — steps drop silently if MAS is slow or down.
                _assigned_for_emit = payload.get("assigned_agent_id")
                _conv_for_emit = conversation_id
                _task_for_emit = task_id

                def _emit_step(event: dict) -> None:
                    def _post():
                        try:
                            server.send_step(
                                event,
                                _conv_for_emit,
                                _task_for_emit,
                                assigned_agent_id=_assigned_for_emit,
                            )
                        except Exception:
                            logger.debug(
                                "Step POST raised", exc_info=True
                            )

                    threading.Thread(target=_post, daemon=True).start()

                emitter_token = current_step_emitter.set(_emit_step)

                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)

                attached_files_meta = payload.get("files") or []
                resolved_files = loop.run_until_complete(
                    _resolve_attached_files(attached_files_meta)
                )
                effective_demand = _prepend_files_to_demand(demand, resolved_files)
                first_file = resolved_files[0] if resolved_files else {}

                task_dict = {
                    "task_id": task_id,
                    "query": effective_demand or payload.get("query", ""),
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

                # Pick the pipeline that matches the queue this message came
                # from — NOT a globally-bound AGENT_TYPE. The same process
                # serves general / analyst / writer / researcher tasks here.
                pipeline = server.get_pipeline_for_type(queue_type)

                start_time = time_module.time()
                # Specialists' op-typed paths (extract / analyze / calculate /
                # summarize / write / format) expect the caller to supply the
                # raw input inline and skip retrieval — they're tool calls, not
                # response modes. Natural-language tasks (e.g. "summarise Q4
                # financial risks") arrive without ``operation`` and need RAG.
                # When no operation is set, route to the general RAG pipeline
                # so retrieval runs against the KS. The active profile's
                # persona is already bound on ``current_persona``, so the
                # answer is still scoped to the specialist's domain.
                op = (task_dict.get("operation") or "").strip().lower()
                effective_type = queue_type
                if queue_type in ("researcher", "analyst", "writer") and not op:
                    logger.info(
                        "Specialist task without 'operation' → general RAG fallback "
                        "(queue_type=%s task_id=%s)",
                        queue_type,
                        task_id,
                    )
                    effective_type = "general"
                    pipeline = server.get_pipeline_for_type("general")

                try:
                    if effective_type == "general":
                        result_pipeline = loop.run_until_complete(
                            pipeline.process_task(task_dict)
                        )
                        final_result_text = result_pipeline["response"]
                    elif effective_type in ("researcher", "analyst", "writer"):
                        final_result_text = loop.run_until_complete(
                            pipeline.process_request(
                                task_type=op,
                                data=task_dict.get("query"),
                                extra_parameters=task_dict,
                            )
                        )
                    else:
                        raise ValueError(f"Unsupported queue type: {effective_type}")

                    processing_duration = time_module.time() - start_time
                    task_processing_duration.observe(processing_duration)
                    task_processing_total.labels(status="success").inc()

                    logger.info(
                        "Task processed (%s): task_id=%s duration=%.2fs",
                        queue_type,
                        task_id,
                        processing_duration,
                    )

                    if task_id:
                        server.send_result(
                            final_result_text,
                            conversation_id,
                            task_id,
                            assigned_agent_id=payload.get("assigned_agent_id"),
                            skill_used=payload.get("skill_used")
                            or payload.get("operation"),
                        )
                except Exception as e:
                    processing_duration = time_module.time() - start_time
                    task_processing_duration.observe(processing_duration)
                    task_processing_total.labels(status="error").inc()
                    agent_errors_total.labels(error_type="task_processing").inc()
                    logger.error(
                        "Task processing failed: task_id=%s error=%s",
                        task_id,
                        str(e),
                        exc_info=True,
                    )
                    # Surface the failure to the UI as an error step. The
                    # inner agents emit their own step on retrieval / reasoning
                    # errors, but tool errors and KS resolution errors only
                    # bubble up here — without this emit those would have no
                    # entry in the thought-process card.
                    try:
                        _emit_step(
                            {
                                "step_type": "error",
                                "title": "Task processing failed",
                                "detail": str(e),
                                "timestamp": None,
                                "metadata": {"phase": "pipeline"},
                            }
                        )
                    except Exception:
                        pass
                    err_msg = f"Agent processing failed: {e}"
                    if task_id:
                        try:
                            server.send_result(
                                err_msg,
                                str(conversation_id),
                                str(task_id),
                                assigned_agent_id=payload.get("assigned_agent_id"),
                                skill_used=payload.get("skill_used")
                                or payload.get("operation"),
                            )
                        except Exception as send_exc:
                            logger.error(
                                "Failed to send error result to MAS: %s", send_exc
                            )
                else:
                    ch.basic_ack(delivery_tag=method.delivery_tag)
                    return
                finally:
                    # Reset the persona binding so it doesn't leak into the
                    # next task on this consumer thread. Runs on both the
                    # success and exception paths.
                    try:
                        current_persona.reset(persona_token)
                        current_agent_name.reset(name_token)
                        current_step_emitter.reset(emitter_token)
                    except (LookupError, ValueError):
                        pass

                # Failed path: ack so the message is not redelivered forever.
                ch.basic_ack(delivery_tag=method.delivery_tag)

            return _on_message

        channel.basic_qos(prefetch_count=1)
        for queue_name, queue_type in queue_to_type.items():
            channel.basic_consume(
                queue=queue_name, on_message_callback=_make_on_message(queue_type)
            )
        logger.info(
            "RabbitMQ consumer started, listening on %d queue(s): %s",
            len(queue_to_type),
            ", ".join(queue_to_type),
        )
        channel.start_consuming()
    except Exception as e:
        logger.error(f"Error in RabbitMQ consumer: {e}", exc_info=True)
        agent_errors_total.labels(error_type="rabbitmq").inc()


def _consume_agent_messages():
    """Consume inter-agent messages from ``agent_comm_{AGENT_ID}`` (delegation)."""
    from agent_server import server
    from agent_server.delegation_bridge import _process_delegation_message

    if not server.AGENT_ID:
        logger.error("Cannot start agent message consumer: AGENT_ID not set")
        return

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
    except Exception as e:
        logger.error(f"Error in agent message consumer: {e}", exc_info=True)
