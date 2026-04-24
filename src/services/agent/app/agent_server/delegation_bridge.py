"""Agent-to-agent delegation handling.

When another agent routes a delegation message to us via RabbitMQ, the consumer
in :mod:`agent_server.consumers` hands the payload off to
:func:`_process_delegation_message`. That helper runs the request through the
local RAG pipeline (delegation is only supported for ``AGENT_TYPE=general``),
then POSTs the answer back to MAS via :func:`_send_delegation_result`.

Uses a lazy ``from agent_server import server`` to read ``AGENT_ID``,
``rag_pipeline``, and ``_build_headers`` so patching ``agent_server.server.X``
from tests still works.
"""

import asyncio
import json

import requests

from config.settings import ORCHESTRATOR_URL
from core.logger import get_logger

logger = get_logger("agent_server.delegation")


def _format_delegation_context(context_entries: list) -> str:
    """Build a readable summary of accumulated delegation context."""
    if not context_entries:
        return ""
    parts = []
    for i, entry in enumerate(context_entries, 1):
        agent_id = entry.get("agent_id", "unknown")
        req = entry.get("request", "")
        data = entry.get("data", {})
        section = f"[Agent {i} — {agent_id}]\n  Request: {req}"
        if data:
            section += f"\n  Data: {json.dumps(data)}"
        parts.append(section)
    return "Prior delegation context:\n" + "\n".join(parts)


def _process_delegation_message(payload: dict):
    """Process a delegation request received from another agent via MAS."""
    from agent_server import server  # lazy: rag_pipeline lives there

    content = payload.get("content", {})
    request_text = content.get("request", "")
    data = content.get("data", {})
    message_id = payload.get("id", "")
    sender = payload.get("sender_agent_id", "")
    delegation_chain = payload.get("delegation_chain", [])
    delegation_context = payload.get("delegation_context", [])

    logger.info(
        f"Processing delegation from {sender}: {request_text[:100]}... "
        f"(chain depth={len(delegation_chain)}, context entries={len(delegation_context)})"
    )

    query = request_text
    if data:
        query = f"{request_text}\n\nData: {json.dumps(data)}"

    context_summary = _format_delegation_context(delegation_context)
    if context_summary:
        query = f"{context_summary}\n\n---\nCurrent request:\n{query}"

    task_dict = {
        "task_id": f"delegation_{message_id}",
        "query": query,
        "mode": "react",
    }

    if not server.rag_pipeline:
        _send_delegation_result(
            message_id,
            "Delegation is only supported when AGENT_TYPE=general (RAG pipeline).",
        )
        return

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    if hasattr(server.rag_pipeline, "react_agent") and server.rag_pipeline.react_agent:
        server.rag_pipeline.react_agent._incoming_delegation_context = delegation_context

    try:
        result_dict = loop.run_until_complete(server.rag_pipeline.process_task(task_dict))
        result_text = result_dict.get("response", "")
        logger.info(f"Delegation {message_id} completed successfully")
    except Exception as e:
        result_text = f"Delegation processing failed: {e}"
        logger.error(f"Delegation {message_id} failed: {e}", exc_info=True)
    finally:
        if hasattr(server.rag_pipeline, "react_agent") and server.rag_pipeline.react_agent:
            server.rag_pipeline.react_agent._incoming_delegation_context = None

    _send_delegation_result(message_id, result_text)


def _send_delegation_result(delegation_id: str, result: str):
    """Send delegation result back to MAS orchestrator."""
    from agent_server import server  # lazy: AGENT_ID + _build_headers live there

    url = f"{ORCHESTRATOR_URL}/rabbitmq/delegation-result"
    payload = {
        "delegation_id": delegation_id,
        "result": result,
        "agent_id": server.AGENT_ID,
    }
    try:
        response = requests.post(
            url, json=payload, headers=server._build_headers(include_api_key=True), timeout=10
        )
        if response.status_code != 200:
            logger.warning(
                f"Failed to send delegation result: {response.status_code} - {response.text}"
            )
        else:
            logger.debug(f"Delegation result sent: {delegation_id}")
    except Exception as e:
        logger.error(f"Error sending delegation result: {e}", exc_info=True)
