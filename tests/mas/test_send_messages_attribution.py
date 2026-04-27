"""Tests for the WebSocket broadcaster's attribution branch."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from chat.chat_tool_functions import send_messages_via_websockets


def _ws_capture():
    ws = MagicMock()
    ws.send_json = AsyncMock()
    return ws


def test_legacy_agent_event_when_no_metadata():
    ws = _ws_capture()
    with patch.dict(
        "chat.chat_tool_functions.active_connections",
        {"42": [ws]},
        clear=True,
    ):
        asyncio.run(send_messages_via_websockets("42", "hello"))

    ws.send_json.assert_awaited_once()
    payload = ws.send_json.await_args.args[0]
    assert payload["type"] == "agent"
    assert payload["content"] == "hello"
    assert "agent_id" not in payload
    assert "agent_name" not in payload
    assert "skill_used" not in payload


def test_task_complete_event_when_metadata_present():
    ws = _ws_capture()
    with patch.dict(
        "chat.chat_tool_functions.active_connections",
        {"42": [ws]},
        clear=True,
    ):
        asyncio.run(
            send_messages_via_websockets(
                "42",
                "the answer",
                agent_id="a-uuid",
                agent_name="Finance-Analyst",
                skill_used="financial_analysis",
            )
        )

    ws.send_json.assert_awaited_once()
    payload = ws.send_json.await_args.args[0]
    assert payload["type"] == "task_complete"
    assert payload["content"] == "the answer"
    assert payload["agent_id"] == "a-uuid"
    assert payload["agent_name"] == "Finance-Analyst"
    assert payload["skill_used"] == "financial_analysis"


def test_partial_metadata_still_promotes_to_task_complete():
    ws = _ws_capture()
    with patch.dict(
        "chat.chat_tool_functions.active_connections",
        {"7": [ws]},
        clear=True,
    ):
        asyncio.run(
            send_messages_via_websockets("7", "ack", agent_name="Researcher")
        )

    payload = ws.send_json.await_args.args[0]
    assert payload["type"] == "task_complete"
    assert payload["agent_name"] == "Researcher"
    assert payload["agent_id"] is None
    assert payload["skill_used"] is None


def test_no_clients_no_op():
    with patch.dict(
        "chat.chat_tool_functions.active_connections", {}, clear=True
    ):
        # Must not raise even with zero subscribers.
        asyncio.run(send_messages_via_websockets("nope", "drop"))


def test_disconnected_client_pruned_silently():
    ws = MagicMock()
    ws.send_json = AsyncMock(side_effect=RuntimeError("closed"))
    conns = [ws]
    with patch.dict(
        "chat.chat_tool_functions.active_connections",
        {"99": conns},
        clear=True,
    ):
        asyncio.run(send_messages_via_websockets("99", "x"))

    assert ws not in conns
