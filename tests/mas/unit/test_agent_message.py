"""
test_agent_message.py
---------------------
Unit tests for the AgentMessage schema and related models.
"""

from datetime import datetime, timezone

import pytest

from schemas.agent_message import (
    AgentMessage,
    DelegationContextEntry,
    DelegationRequest,
    DelegationResponse,
    MessageStatus,
    MessageType,
)


class TestAgentMessage:
    """Tests for the AgentMessage Pydantic model."""

    def test_create_minimal_message(self):
        msg = AgentMessage(
            sender_agent_id="agent-a",
            receiver_agent_id="agent-b",
            message_type=MessageType.REQUEST,
        )
        assert msg.sender_agent_id == "agent-a"
        assert msg.receiver_agent_id == "agent-b"
        assert msg.message_type == "request"
        assert msg.id  # auto-generated UUID
        assert msg.status == "pending"
        assert msg.requires_response is False
        assert msg.delegation_chain == []
        assert msg.content == {}

    def test_create_delegation_message(self):
        ctx = [
            DelegationContextEntry(agent_id="agent-x", request="Find data", data={"q": 1}),
        ]
        msg = AgentMessage(
            sender_agent_id="agent-a",
            receiver_agent_id="agent-b",
            message_type=MessageType.DELEGATION,
            content={"request": "Calculate totals", "data": {"amount": 100}},
            conversation_id="conv-123",
            requires_response=True,
            delegation_chain=["agent-a"],
            delegation_context=ctx,
            timeout_seconds=15.0,
        )
        assert msg.message_type == "delegation"
        assert msg.requires_response is True
        assert msg.content["request"] == "Calculate totals"
        assert msg.delegation_chain == ["agent-a"]
        assert len(msg.delegation_context) == 1
        assert msg.delegation_context[0].agent_id == "agent-x"
        assert msg.timeout_seconds == 15.0

    def test_delegation_context_defaults_empty(self):
        msg = AgentMessage(
            sender_agent_id="a",
            receiver_agent_id="b",
            message_type=MessageType.REQUEST,
        )
        assert msg.delegation_context == []

    def test_auto_generated_fields(self):
        msg = AgentMessage(
            sender_agent_id="a",
            receiver_agent_id="b",
            message_type=MessageType.RESPONSE,
        )
        assert len(msg.id) == 36  # UUID format
        assert msg.conversation_id  # auto-generated
        assert isinstance(msg.timestamp, datetime)

    def test_message_serialization(self):
        msg = AgentMessage(
            sender_agent_id="a",
            receiver_agent_id="b",
            message_type=MessageType.RESULT,
            content={"result": "42"},
        )
        data = msg.model_dump()
        assert data["sender_agent_id"] == "a"
        assert data["message_type"] == "result"
        assert data["content"]["result"] == "42"

    def test_message_json_roundtrip(self):
        msg = AgentMessage(
            sender_agent_id="a",
            receiver_agent_id="b",
            message_type=MessageType.DELEGATION,
            content={"key": "value"},
        )
        json_str = msg.model_dump_json()
        restored = AgentMessage.model_validate_json(json_str)
        assert restored.sender_agent_id == msg.sender_agent_id
        assert restored.id == msg.id
        assert restored.content == msg.content

    def test_all_message_types(self):
        for mtype in MessageType:
            msg = AgentMessage(
                sender_agent_id="a",
                receiver_agent_id="b",
                message_type=mtype,
            )
            assert msg.message_type == mtype.value

    def test_all_message_statuses(self):
        for mstatus in MessageStatus:
            msg = AgentMessage(
                sender_agent_id="a",
                receiver_agent_id="b",
                message_type=MessageType.REQUEST,
                status=mstatus,
            )
            assert msg.status == mstatus.value


class TestDelegationRequest:
    """Tests for the DelegationRequest model."""

    def test_create_delegation_request(self):
        req = DelegationRequest(
            sender_agent_id="agent-a",
            to_agent_type="analyst",
            request="Calculate total payments",
            data={"payments": [100, 200, 300]},
        )
        assert req.sender_agent_id == "agent-a"
        assert req.to_agent_type == "analyst"
        assert req.request == "Calculate total payments"
        assert req.data["payments"] == [100, 200, 300]
        assert req.delegation_chain == []
        assert req.timeout_seconds == 30.0

    def test_delegation_request_with_chain(self):
        req = DelegationRequest(
            sender_agent_id="agent-c",
            to_agent_type="researcher",
            request="Find data",
            delegation_chain=["agent-a", "agent-b"],
        )
        assert len(req.delegation_chain) == 2

    def test_delegation_request_with_context(self):
        ctx = [
            DelegationContextEntry(agent_id="agent-a", request="Search web", data={"url": "x"}),
            DelegationContextEntry(agent_id="agent-b", request="Analyze", data={}),
        ]
        req = DelegationRequest(
            sender_agent_id="agent-c",
            to_agent_type="analyst",
            request="Summarise results",
            delegation_context=ctx,
        )
        assert len(req.delegation_context) == 2
        assert req.delegation_context[0].request == "Search web"
        assert req.delegation_context[1].agent_id == "agent-b"


class TestDelegationResponse:
    """Tests for the DelegationResponse model."""

    def test_successful_response(self):
        resp = DelegationResponse(
            delegation_id="del-123",
            status="completed",
            result="Total: $600",
            agent_id="agent-b",
        )
        assert resp.status == "completed"
        assert resp.result == "Total: $600"

    def test_error_response(self):
        resp = DelegationResponse(
            delegation_id="del-456",
            status="error",
            error="No agent available",
        )
        assert resp.status == "error"
        assert resp.error == "No agent available"
        assert resp.result is None

    def test_timeout_response(self):
        resp = DelegationResponse(
            delegation_id="del-789",
            status="timeout",
            error="Timed out after 30s",
        )
        assert resp.status == "timeout"
