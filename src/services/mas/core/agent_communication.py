"""
Agent Communication Module
--------------------------
Implements the AgentCommunicator class that enables agent-to-agent messaging
through RabbitMQ. Provides message routing, persistence for debugging,
acknowledgment tracking, and timeout handling.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Callable
from typing import Any

from core.logger import get_logger
from schemas.agent_message import (
    AgentMessage,
    DelegationContextEntry,
    DelegationRequest,
    DelegationResponse,
    MessageStatus,
    MessageType,
)

logger = get_logger("agent_communication")

MAX_DELEGATION_DEPTH = 5
DEFAULT_DELEGATION_TIMEOUT = 30.0


class MessageStore:
    """In-memory message store for debugging and audit trails."""

    def __init__(self, max_messages_per_agent: int = 1000):
        self._messages: dict[str, list[AgentMessage]] = defaultdict(list)
        self._by_id: dict[str, AgentMessage] = {}
        self._max = max_messages_per_agent

    def store(self, message: AgentMessage) -> None:
        self._by_id[message.id] = message
        bucket = self._messages[message.receiver_agent_id]
        bucket.append(message)
        if len(bucket) > self._max:
            removed = bucket.pop(0)
            self._by_id.pop(removed.id, None)

    def get(self, message_id: str) -> AgentMessage | None:
        return self._by_id.get(message_id)

    def get_for_agent(self, agent_id: str) -> list[AgentMessage]:
        return list(self._messages.get(agent_id, []))

    def update_status(self, message_id: str, status: MessageStatus) -> None:
        msg = self._by_id.get(message_id)
        if msg:
            msg.status = status


class DelegationRegistry:
    """
    Tracks in-flight delegations so that the orchestrator can match
    delegation results back to the waiting caller.
    """

    def __init__(self):
        self._pending: dict[str, asyncio.Event] = {}
        self._results: dict[str, dict[str, Any]] = {}

    def register(self, delegation_id: str) -> asyncio.Event:
        event = asyncio.Event()
        self._pending[delegation_id] = event
        return event

    def resolve(self, delegation_id: str, result: dict[str, Any]) -> bool:
        event = self._pending.pop(delegation_id, None)
        if event is None:
            return False
        self._results[delegation_id] = result
        event.set()
        return True

    def get_result(self, delegation_id: str) -> dict[str, Any] | None:
        return self._results.pop(delegation_id, None)

    def cancel(self, delegation_id: str) -> None:
        event = self._pending.pop(delegation_id, None)
        if event:
            self._results[delegation_id] = {"error": "cancelled"}
            event.set()


class AgentCommunicator:
    """
    Central communication hub for agent-to-agent messaging.

    Responsibilities:
        - Build and manage per-agent communication queues on RabbitMQ
        - Route messages between agents
        - Track message acknowledgments
        - Enforce delegation depth limits
        - Persist messages for debugging
    """

    QUEUE_PREFIX = "agent_comm_"

    def __init__(self, rabbitmq_instance=None):
        self.rabbitmq = rabbitmq_instance
        self.message_store = MessageStore()
        self.delegation_registry = DelegationRegistry()
        self._handlers: dict[str, Callable] = {}

    # ------------------------------------------------------------------
    # Queue management
    # ------------------------------------------------------------------

    def agent_queue_name(self, agent_id: str) -> str:
        return f"{self.QUEUE_PREFIX}{agent_id}"

    def ensure_agent_queue(self, agent_id: str) -> None:
        if self.rabbitmq is None:
            logger.warning("RabbitMQ not connected — skipping queue creation")
            return
        queue_name = self.agent_queue_name(agent_id)
        try:
            self.rabbitmq.create_queue(queue_name)
            logger.info(f"Ensured communication queue: {queue_name}")
        except Exception as exc:
            logger.error(f"Failed to create queue {queue_name}: {exc}")

    # ------------------------------------------------------------------
    # Sending
    # ------------------------------------------------------------------

    def send_message(self, message: AgentMessage) -> bool:
        self.message_store.store(message)

        if self.rabbitmq is None:
            logger.warning("RabbitMQ not connected — message stored but not sent")
            return False

        queue_name = self.agent_queue_name(message.receiver_agent_id)
        try:
            payload = message.model_dump_json()
            self.rabbitmq.publish(queue_name, payload)
            self.message_store.update_status(message.id, MessageStatus.DELIVERED)
            logger.info(
                f"Message {message.id} sent: {message.sender_agent_id} → "
                f"{message.receiver_agent_id} (type={message.message_type})"
            )
            return True
        except Exception as exc:
            self.message_store.update_status(message.id, MessageStatus.FAILED)
            logger.error(f"Failed to send message {message.id}: {exc}")
            return False

    def acknowledge_message(self, message_id: str) -> None:
        self.message_store.update_status(message_id, MessageStatus.ACKNOWLEDGED)
        logger.debug(f"Message {message_id} acknowledged")

    # ------------------------------------------------------------------
    # Delegation orchestration
    # ------------------------------------------------------------------

    async def handle_delegation(
        self,
        request: DelegationRequest,
        select_agent_fn: Callable,
    ) -> DelegationResponse:
        """
        Route a delegation request to a suitable agent and wait for the result.

        Args:
            request: The delegation request from the calling agent.
            select_agent_fn: A callable(agent_type) → agent_id that picks the
                             best agent for the requested type.
        """
        chain = list(request.delegation_chain)
        if len(chain) >= MAX_DELEGATION_DEPTH:
            logger.warning(
                f"Delegation depth limit reached ({MAX_DELEGATION_DEPTH}). Chain: {chain}"
            )
            return DelegationResponse(
                delegation_id="",
                status="error",
                error=f"Maximum delegation depth ({MAX_DELEGATION_DEPTH}) exceeded",
            )

        target_agent_id = select_agent_fn(request.to_agent_type)
        if not target_agent_id:
            return DelegationResponse(
                delegation_id="",
                status="error",
                error=f"No available agent for type '{request.to_agent_type}'",
            )

        if target_agent_id in chain:
            return DelegationResponse(
                delegation_id="",
                status="error",
                error=f"Delegation loop detected: agent {target_agent_id} already in chain",
            )

        chain.append(request.sender_agent_id)

        context = list(request.delegation_context)
        context.append(
            DelegationContextEntry(
                agent_id=request.sender_agent_id,
                request=request.request,
                data=request.data,
            )
        )

        message = AgentMessage(
            sender_agent_id=request.sender_agent_id,
            receiver_agent_id=target_agent_id,
            message_type=MessageType.DELEGATION,
            content={
                "request": request.request,
                "data": request.data,
            },
            conversation_id=request.conversation_id,
            requires_response=True,
            delegation_chain=chain,
            delegation_context=context,
            timeout_seconds=request.timeout_seconds,
        )

        event = self.delegation_registry.register(message.id)
        sent = await asyncio.to_thread(self.send_message, message)

        if not sent:
            self.delegation_registry.cancel(message.id)
            return DelegationResponse(
                delegation_id=message.id,
                status="error",
                error="Failed to deliver delegation message",
            )

        timeout = request.timeout_seconds or DEFAULT_DELEGATION_TIMEOUT
        try:
            await asyncio.wait_for(event.wait(), timeout=timeout)
        except TimeoutError:
            self.message_store.update_status(message.id, MessageStatus.TIMEOUT)
            self.delegation_registry.cancel(message.id)
            logger.warning(f"Delegation {message.id} timed out after {timeout}s")
            return DelegationResponse(
                delegation_id=message.id,
                status="timeout",
                error=f"Delegation timed out after {timeout}s",
            )

        result = self.delegation_registry.get_result(message.id)
        if result and "error" not in result:
            self.acknowledge_message(message.id)
            return DelegationResponse(
                delegation_id=message.id,
                status="completed",
                result=result.get("result", ""),
                agent_id=target_agent_id,
            )

        return DelegationResponse(
            delegation_id=message.id,
            status="error",
            error=result.get("error", "Unknown delegation error") if result else "No result",
        )

    def receive_delegation_result(self, delegation_id: str, result: str, agent_id: str) -> bool:
        """Called when a delegate agent posts its result back."""
        return self.delegation_registry.resolve(
            delegation_id, {"result": result, "agent_id": agent_id}
        )

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def get_messages_for_agent(self, agent_id: str) -> list[dict[str, Any]]:
        messages = self.message_store.get_for_agent(agent_id)
        return [m.model_dump() for m in messages]

    def get_message(self, message_id: str) -> dict[str, Any] | None:
        msg = self.message_store.get(message_id)
        return msg.model_dump() if msg else None
