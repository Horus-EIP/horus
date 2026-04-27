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
import json
import os
import time as time_module
import uuid

import pika

from config.settings import AGENT_TYPE, RABBITMQ_PORT
from core.logger import get_correlation_id, get_logger, set_correlation_id
from core.metrics import (agent_errors_total, task_processing_duration,
                          task_processing_total)

logger = get_logger("agent_server.consumers")


def _consume_messages():
    """Consume tasks from this agent's RabbitMQ queue and run them through the pipeline.

    Each message is a JSON payload with at least ``demand`` and
    ``conversation_id``. Result is POSTed back via ``send_result``.
    """
    from agent_server import server  # lazy: state + send_result live there

    if not server.AGENT_ID:
        logger.error("Cannot start consumer: AGENT_ID not set")
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
        # Declare a durable queue to avoid RabbitMQ 'transient_nonexcl_queues' deprecation
        channel.queue_declare(
            queue=server.WORK_QUEUE_NAME,
            passive=False,
            durable=True,
            exclusive=False,
            auto_delete=False,
            arguments={"x-max-priority": 10},
        )

        def _on_message(ch, method, properties, body):
            try:
                payload = json.loads(body.decode("utf-8")) if body else {}
            except Exception:
                # Fallback: treat body as plain text demand
                payload = {"demand": body.decode("utf-8")}

            # Cancel control messages are routed through the same queue. They have no
            # demand/conversation_id; just ack and move on so RabbitMQ doesn't redeliver.
            if payload.get("type") == "cancel":
                logger.info(
                    "Received cancel control message on work queue (task_id=%s)",
                    payload.get("task_id"),
                )
                ch.basic_ack(delivery_tag=method.delivery_tag)
                return

            demand = payload.get("demand", "")
            conversation_id = payload.get("conversation_id", "")
            task_id = payload.get("task_id") or ("task_" + uuid.uuid4().hex)
            if not (demand or payload.get("query")):
                logger.warning(
                    "RabbitMQ task message has no demand/query (task_id=%s). "
                    "MAS must publish the task text in the message body.",
                    task_id,
                )
                ch.basic_ack(delivery_tag=method.delivery_tag)
                return

            # Extract correlation ID from message properties if available
            corr_id = properties.headers.get("X-Request-ID") if properties.headers else None
            if corr_id:
                set_correlation_id(corr_id)

            logger.info(
                f"Received task: task_id={task_id}, conversation_id={conversation_id}, "
                f"demand_length={len(demand)}, correlation_id={get_correlation_id()}"
            )

            # Adapt to pipeline expected schema; include optional utility fields
            task_dict = {
                "task_id": task_id,
                "query": demand or payload.get("query", ""),
                "operation": payload.get("operation"),
                "expression": payload.get("expression"),
                "file_url": payload.get("file_url"),
                "file_content": payload.get("file_content"),
                "file_type": payload.get("file_type"),
                "filename": payload.get("filename"),
                "text": payload.get("text"),
                "max_sentences": payload.get("max_sentences"),
                "format": payload.get("format"),
                "extraction_type": payload.get("extraction_type"),
                "analysis_type": payload.get("analysis_type"),
            }

            # Process task asynchronously (pika is sync, but pipeline is async)
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)

            # Run async pipeline processing with metrics
            start_time = time_module.time()
            try:
                if AGENT_TYPE == "general":
                    result_pipeline = loop.run_until_complete(
                        server.active_agent.process_task(task_dict)
                    )
                    final_result_text = result_pipeline["response"]
                elif AGENT_TYPE in ["researcher", "analyst", "writer"]:
                    final_result_text = loop.run_until_complete(
                        server.active_agent.process_request(
                            task_type=task_dict.get("operation"),
                            data=task_dict.get("query"),
                            extra_parameters=task_dict,
                        )
                    )
                else:
                    raise ValueError(f"Unsupported AGENT_TYPE: {AGENT_TYPE}")

                processing_duration = time_module.time() - start_time

                task_processing_duration.observe(processing_duration)
                task_processing_total.labels(status="success").inc()

                logger.info(
                    f"Task processed successfully: task_id={task_id}, "
                    f"duration={processing_duration:.2f}s, correlation_id={get_correlation_id()}"
                )

                # Send result back to MAS (requires conversation_id and task_id).
                # ``assigned_agent_id`` is forwarded so MAS can match Task.agent_id
                # even when this pooled worker isn't the originally-assigned instance.
                if conversation_id and task_id:
                    server.send_result(
                        final_result_text,
                        conversation_id,
                        task_id,
                        assigned_agent_id=payload.get("assigned_agent_id"),
                    )
            except Exception as e:
                processing_duration = time_module.time() - start_time
                task_processing_duration.observe(processing_duration)
                task_processing_total.labels(status="error").inc()
                agent_errors_total.labels(error_type="task_processing").inc()
                logger.error(
                    f"Task processing failed: task_id={task_id}, error={str(e)}, "
                    f"correlation_id={get_correlation_id()}",
                    exc_info=True
                )
                err_msg = f"Agent processing failed: {e}"
                if conversation_id and task_id:
                    try:
                        server.send_result(
                            err_msg,
                            str(conversation_id),
                            str(task_id),
                            assigned_agent_id=payload.get("assigned_agent_id"),
                        )
                    except Exception as send_exc:
                        logger.error(f"Failed to send error result to MAS: {send_exc}")
            else:
                # Acknowledge only after successful processing
                ch.basic_ack(delivery_tag=method.delivery_tag)
                return

            # Failed path: ack so the message is not redelivered forever
            ch.basic_ack(delivery_tag=method.delivery_tag)

        channel.basic_qos(prefetch_count=1)
        channel.basic_consume(queue=server.AGENT_ID, on_message_callback=_on_message)
        logger.info(f"RabbitMQ consumer started, listening on queue '{server.AGENT_ID}'")
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
