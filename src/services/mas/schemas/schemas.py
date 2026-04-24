"""Pydantic request/response schemas for the MAS service.

Field-level details are available through FastAPI's auto-generated
OpenAPI docs. See ``docs/architecture/mas_service.md`` for the high-level
API contract.
"""

from typing import Optional

from pydantic import BaseModel

from auth.permissions import Role
from db.models import AgentTypes


class RegistrationForm(BaseModel):
    """Agent registration payload (name, skills, description, type)."""

    name: str
    skills: list[str]
    description: str
    type: Optional[AgentTypes] = None


class TaskForm(BaseModel):
    """Task creation payload (demand, conversation_id, skills_required)."""

    demand: str
    conversation_id: int
    skills_required: list[str]


class TaskResultForm(BaseModel):
    """Agent-submitted task result (result, conversation_id, agent_id, task_id)."""

    result: str
    conversation_id: str
    agent_id: str
    task_id: str


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
