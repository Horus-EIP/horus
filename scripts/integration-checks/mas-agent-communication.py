"""
test_agent_communication.py
---------------------------
Unit tests for the AgentCommunicator class, MessageStore, and DelegationRegistry.

Covers:
    - Message sending and persistence
    - Queue management
    - Acknowledgment tracking
    - Delegation orchestration (success, timeout, loop detection, depth limit)
    - Message store operations
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.agent_communication import (
    MAX_DELEGATION_DEPTH,
    AgentCommunicator,
    DelegationRegistry,
    MessageStore,
)
from schemas.agent_message import (
    AgentMessage,
    DelegationContextEntry,
    DelegationRequest,
    MessageStatus,
    MessageType,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_rabbitmq():
    rmq = MagicMock()
    rmq.create_queue = MagicMock()
    rmq.publish = MagicMock()
    return rmq


@pytest.fixture
def communicator(mock_rabbitmq):
    return AgentCommunicator(rabbitmq_instance=mock_rabbitmq)


@pytest.fixture
def communicator_no_rmq():
    return AgentCommunicator(rabbitmq_instance=None)


# ---------------------------------------------------------------------------
# MessageStore tests
# ---------------------------------------------------------------------------

class TestMessageStore:
    def test_store_and_retrieve(self):
        store = MessageStore()
        msg = AgentMessage(
            sender_agent_id="a",
            receiver_agent_id="b",
            message_type=MessageType.REQUEST,
        )
        store.store(msg)
        assert store.get(msg.id) is not None
        assert store.get(msg.id).sender_agent_id == "a"

    def test_get_for_agent(self):
        store = MessageStore()
        for i in range(3):
            msg = AgentMessage(
                sender_agent_id=f"sender-{i}",
                receiver_agent_id="target-agent",
                message_type=MessageType.REQUEST,
            )
            store.store(msg)
        messages = store.get_for_agent("target-agent")
        assert len(messages) == 3

    def test_update_status(self):
        store = MessageStore()
        msg = AgentMessage(
            sender_agent_id="a",
            receiver_agent_id="b",
            message_type=MessageType.REQUEST,
        )
        store.store(msg)
        store.update_status(msg.id, MessageStatus.DELIVERED)
        assert store.get(msg.id).status == "delivered"

    def test_max_messages_eviction(self):
        store = MessageStore(max_messages_per_agent=2)
        for i in range(5):
            msg = AgentMessage(
                sender_agent_id="sender",
                receiver_agent_id="agent-x",
                message_type=MessageType.REQUEST,
                content={"index": i},
            )
            store.store(msg)
        messages = store.get_for_agent("agent-x")
        assert len(messages) == 2
        assert messages[0].content["index"] == 3
        assert messages[1].content["index"] == 4

    def test_get_nonexistent_message(self):
        store = MessageStore()
        assert store.get("nonexistent-id") is None

    def test_get_for_agent_empty(self):
        store = MessageStore()
        assert store.get_for_agent("ghost-agent") == []


# ---------------------------------------------------------------------------
# DelegationRegistry tests
# ---------------------------------------------------------------------------

class TestDelegationRegistry:
    def test_register_and_resolve(self):
        registry = DelegationRegistry()
        event = registry.register("del-1")
        assert not event.is_set()
        resolved = registry.resolve("del-1", {"result": "done"})
        assert resolved is True
        assert event.is_set()
        result = registry.get_result("del-1")
        assert result["result"] == "done"

    def test_resolve_unknown_delegation(self):
        registry = DelegationRegistry()
        assert registry.resolve("unknown", {}) is False

    def test_cancel(self):
        registry = DelegationRegistry()
        event = registry.register("del-2")
        registry.cancel("del-2")
        assert event.is_set()
        result = registry.get_result("del-2")
        assert result["error"] == "cancelled"

    def test_get_result_clears_entry(self):
        registry = DelegationRegistry()
        registry.register("del-3")
        registry.resolve("del-3", {"result": "value"})
        first = registry.get_result("del-3")
        assert first is not None
        second = registry.get_result("del-3")
        assert second is None


# ---------------------------------------------------------------------------
# AgentCommunicator tests
# ---------------------------------------------------------------------------

class TestAgentCommunicator:
    def test_agent_queue_name(self, communicator):
        assert communicator.agent_queue_name("abc-123") == "agent_comm_abc-123"

    def test_ensure_agent_queue(self, communicator, mock_rabbitmq):
        communicator.ensure_agent_queue("agent-1")
        mock_rabbitmq.create_queue.assert_called_once_with("agent_comm_agent-1")

    def test_ensure_queue_without_rabbitmq(self, communicator_no_rmq):
        communicator_no_rmq.ensure_agent_queue("agent-1")

    def test_send_message_success(self, communicator, mock_rabbitmq):
        msg = AgentMessage(
            sender_agent_id="a",
            receiver_agent_id="b",
            message_type=MessageType.REQUEST,
            content={"data": "hello"},
        )
        result = communicator.send_message(msg)
        assert result is True
        mock_rabbitmq.publish.assert_called_once()
        stored = communicator.message_store.get(msg.id)
        assert stored.status == "delivered"

    def test_send_message_without_rabbitmq(self, communicator_no_rmq):
        msg = AgentMessage(
            sender_agent_id="a",
            receiver_agent_id="b",
            message_type=MessageType.REQUEST,
        )
        result = communicator_no_rmq.send_message(msg)
        assert result is False
        stored = communicator_no_rmq.message_store.get(msg.id)
        assert stored is not None

    def test_send_message_publish_failure(self, communicator, mock_rabbitmq):
        mock_rabbitmq.publish.side_effect = Exception("Connection lost")
        msg = AgentMessage(
            sender_agent_id="a",
            receiver_agent_id="b",
            message_type=MessageType.REQUEST,
        )
        result = communicator.send_message(msg)
        assert result is False
        stored = communicator.message_store.get(msg.id)
        assert stored.status == "failed"

    def test_acknowledge_message(self, communicator):
        msg = AgentMessage(
            sender_agent_id="a",
            receiver_agent_id="b",
            message_type=MessageType.REQUEST,
        )
        communicator.message_store.store(msg)
        communicator.acknowledge_message(msg.id)
        assert communicator.message_store.get(msg.id).status == "acknowledged"

    def test_get_messages_for_agent(self, communicator):
        msg = AgentMessage(
            sender_agent_id="a",
            receiver_agent_id="target",
            message_type=MessageType.REQUEST,
        )
        communicator.send_message(msg)
        messages = communicator.get_messages_for_agent("target")
        assert len(messages) == 1
        assert messages[0]["sender_agent_id"] == "a"

    def test_get_message_by_id(self, communicator):
        msg = AgentMessage(
            sender_agent_id="a",
            receiver_agent_id="b",
            message_type=MessageType.REQUEST,
        )
        communicator.send_message(msg)
        result = communicator.get_message(msg.id)
        assert result is not None
        assert result["id"] == msg.id

    def test_get_nonexistent_message(self, communicator):
        assert communicator.get_message("ghost") is None


# ---------------------------------------------------------------------------
# Delegation orchestration tests
# ---------------------------------------------------------------------------

class TestDelegationOrchestration:
    @pytest.mark.asyncio
    async def test_delegation_success(self, communicator, mock_rabbitmq):
        def select_agent(agent_type):
            return "agent-b"

        req = DelegationRequest(
            sender_agent_id="agent-a",
            to_agent_type="analyst",
            request="Calculate totals",
            timeout_seconds=5.0,
        )

        async def _resolve_after_delay():
            await asyncio.sleep(0.1)
            for did, event in list(communicator.delegation_registry._pending.items()):
                communicator.delegation_registry.resolve(did, {"result": "Total: 600"})

        asyncio.create_task(_resolve_after_delay())
        response = await communicator.handle_delegation(req, select_agent)
        assert response.status == "completed"
        assert response.result == "Total: 600"

    @pytest.mark.asyncio
    async def test_delegation_no_agent_found(self, communicator):
        def select_agent(agent_type):
            return None

        req = DelegationRequest(
            sender_agent_id="agent-a",
            to_agent_type="nonexistent",
            request="Do something",
        )
        response = await communicator.handle_delegation(req, select_agent)
        assert response.status == "error"
        assert "No available agent" in response.error

    @pytest.mark.asyncio
    async def test_delegation_depth_limit(self, communicator):
        def select_agent(agent_type):
            return "agent-x"

        req = DelegationRequest(
            sender_agent_id="agent-a",
            to_agent_type="analyst",
            request="Do something",
            delegation_chain=[f"agent-{i}" for i in range(MAX_DELEGATION_DEPTH)],
        )
        response = await communicator.handle_delegation(req, select_agent)
        assert response.status == "error"
        assert "depth" in response.error.lower()

    @pytest.mark.asyncio
    async def test_delegation_loop_detection(self, communicator, mock_rabbitmq):
        def select_agent(agent_type):
            return "agent-a"

        req = DelegationRequest(
            sender_agent_id="agent-b",
            to_agent_type="analyst",
            request="Do something",
            delegation_chain=["agent-a"],
        )
        response = await communicator.handle_delegation(req, select_agent)
        assert response.status == "error"
        assert "loop" in response.error.lower()

    @pytest.mark.asyncio
    async def test_delegation_timeout(self, communicator, mock_rabbitmq):
        def select_agent(agent_type):
            return "agent-b"

        req = DelegationRequest(
            sender_agent_id="agent-a",
            to_agent_type="analyst",
            request="Slow task",
            timeout_seconds=0.2,
        )
        response = await communicator.handle_delegation(req, select_agent)
        assert response.status == "timeout"

    @pytest.mark.asyncio
    async def test_delegation_send_failure(self, communicator, mock_rabbitmq):
        mock_rabbitmq.publish.side_effect = Exception("Connection lost")

        def select_agent(agent_type):
            return "agent-b"

        req = DelegationRequest(
            sender_agent_id="agent-a",
            to_agent_type="analyst",
            request="Task",
            timeout_seconds=1.0,
        )
        response = await communicator.handle_delegation(req, select_agent)
        assert response.status == "error"
        assert "deliver" in response.error.lower() or "Failed" in response.error

    def test_receive_delegation_result(self, communicator):
        event = communicator.delegation_registry.register("del-100")
        resolved = communicator.receive_delegation_result(
            "del-100", "Result text", "agent-b"
        )
        assert resolved is True
        assert event.is_set()

    def test_receive_delegation_result_unknown(self, communicator):
        resolved = communicator.receive_delegation_result(
            "nonexistent", "Result", "agent-b"
        )
        assert resolved is False

    @pytest.mark.asyncio
    async def test_delegation_context_propagated(self, communicator, mock_rabbitmq):
        """The message published to RabbitMQ carries accumulated context."""
        prior_ctx = [
            DelegationContextEntry(agent_id="agent-x", request="Step 1", data={"k": 1}),
        ]

        def select_agent(agent_type):
            return "agent-b"

        req = DelegationRequest(
            sender_agent_id="agent-a",
            to_agent_type="analyst",
            request="Step 2",
            data={"k": 2},
            delegation_context=prior_ctx,
            timeout_seconds=0.3,
        )

        await communicator.handle_delegation(req, select_agent)

        call_args = mock_rabbitmq.publish.call_args
        import json
        published = json.loads(call_args[0][1])

        assert len(published["delegation_context"]) == 2
        assert published["delegation_context"][0]["agent_id"] == "agent-x"
        assert published["delegation_context"][0]["request"] == "Step 1"
        assert published["delegation_context"][1]["agent_id"] == "agent-a"
        assert published["delegation_context"][1]["request"] == "Step 2"
        assert published["delegation_context"][1]["data"] == {"k": 2}
