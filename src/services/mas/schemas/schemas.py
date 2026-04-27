"""Pydantic request/response schemas for the MAS service.

Field-level details are available through FastAPI's auto-generated
OpenAPI docs. See ``docs/architecture/mas_service.md`` for the high-level
API contract.
"""

from typing import Literal, Optional

from pydantic import BaseModel

from auth.permissions import Role
from db.models import AgentTypes


class RegistrationForm(BaseModel):
    """Agent registration payload (name, skills, description, type)."""

    name: str
    skills: list[str]
    description: str
    type: Optional[AgentTypes] = None


TaskMode = Literal["auto", "specific_agent", "any_with_skill"]


class TaskForm(BaseModel):
    """Task creation payload.

    The dispatcher honours ``mode``:

    - ``auto`` (default) — LLM router picks the agent; ``agent_id`` is ignored.
    - ``specific_agent`` — required ``agent_id`` is used verbatim; the dispatch
      will queue-on-busy if the worker is currently offline.
    - ``any_with_skill`` — first registered agent whose skills include
      ``skills_required[0]`` is selected (live agents preferred, seeded ones
      fall back).

    ``agent_id`` and ``mode`` are optional so older clients keep working.
    """

    demand: str
    conversation_id: int
    skills_required: list[str]
    agent_id: Optional[str] = None
    mode: Optional[TaskMode] = None


class TaskResultForm(BaseModel):
    """Agent-submitted task result.

    ``agent_name`` and ``skill_used`` are optional metadata used by the chat UI
    to render an attribution chip (which agent answered, which skill ran).
    Older agents that don't send them still work.
    """

    result: str
    conversation_id: str
    agent_id: str
    task_id: str
    agent_name: Optional[str] = None
    skill_used: Optional[str] = None


class CreateUserRequest(BaseModel):
    """User registration payload. Password is bcrypt-hashed before storage."""

    username: str
    password: str


class Token(BaseModel):
    """JWT access token response. Use as ``Authorization: Bearer <token>``."""

    access_token: str
    token_type: str


class ConversationCreation(BaseModel):
    """Conversation creation payload (``name`` only)."""

    name: str


class UserPasswordModification(BaseModel):
    old_password: str
    new_password: str


class UpdateRole(BaseModel):
    user_id: str
    new_role: Role


class SubTask(BaseModel):
    id: str
    agent_type: str
    description: str
    depends_on: list[str] = []
    status: str


class CollaborativeTask(BaseModel):
    sub_tasks: list[SubTask]
