"""Pydantic models for the agent's HTTP API.

``Task`` is the payload accepted by ``POST /task``; ``Result`` is the
response. Optional fields let callers pass extraction/tool parameters
without defining a separate schema per operation.
"""

from pydantic import BaseModel


class Task(BaseModel):
    """Task payload received from the MAS Orchestrator."""

    task_id: str = None  # Auto-generated if not provided
    query: str | None = None
    conversation_id: str
    assigned_agent_id: str | None = None  # Task assignee in DB; result payload must use this when pooled.
    operation: str | None = None
    expression: str | None = None
    file_url: str | None = None
    file_content: str | None = None  # base64/utf-8 text; small files only
    file_type: str | None = None
    filename: str | None = None
    text: str | None = None
    max_sentences: int | None = None


class Result(BaseModel):
    """Task result sent back to the MAS Orchestrator."""

    agent_id: str
    result: str
