"""
Agent Message Schema
--------------------
Defines the AgentMessage model used for agent-to-agent communication
within the multi-agent system.

Message Types:
    - request:    Agent-to-agent task request
    - response:   Reply to a request
    - delegation: Delegation of work to another agent
    - result:     Final result of a delegated task
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class DelegationContextEntry(BaseModel):
    """One hop in the delegation chain: what was asked and what data was sent."""

    agent_id: str
    request: str
    data: Dict[str, Any] = Field(default_factory=dict)


class MessageType(str, Enum):
    REQUEST = "request"
    RESPONSE = "response"
    DELEGATION = "delegation"
    RESULT = "result"


class MessageStatus(str, Enum):
    PENDING = "pending"
    DELIVERED = "delivered"
    ACKNOWLEDGED = "acknowledged"
    TIMEOUT = "timeout"
    FAILED = "failed"


class AgentMessage(BaseModel):
    """
    Canonical message format for agent-to-agent communication.

    Every message travelling through the communication layer — whether it is a
    simple request, a delegation, or a result callback — uses this schema.
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    sender_agent_id: str
    receiver_agent_id: str
    message_type: MessageType
    content: Dict[str, Any] = Field(default_factory=dict)
    conversation_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    requires_response: bool = False
    status: MessageStatus = MessageStatus.PENDING

    # Delegation-specific fields
    delegation_chain: list[str] = Field(default_factory=list)
    delegation_context: list[DelegationContextEntry] = Field(default_factory=list)
    parent_message_id: Optional[str] = None
    timeout_seconds: float = 30.0

    class Config:
        use_enum_values = True


class DelegationRequest(BaseModel):
    """Schema for incoming delegation requests to the MAS orchestrator."""

    sender_agent_id: str
    to_agent_type: str
    request: str
    data: Dict[str, Any] = Field(default_factory=dict)
    conversation_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    delegation_chain: list[str] = Field(default_factory=list)
    delegation_context: list[DelegationContextEntry] = Field(default_factory=list)
    timeout_seconds: float = 30.0


class DelegationResponse(BaseModel):
    """Schema for delegation result returned by the MAS orchestrator."""

    delegation_id: str
    status: str
    result: Optional[str] = None
    error: Optional[str] = None
    agent_id: Optional[str] = None
