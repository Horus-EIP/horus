"""Pydantic request/response schemas for the MAS service.

Field-level details are available through FastAPI's auto-generated
OpenAPI docs. See ``docs/architecture/mas_service.md`` for the high-level
API contract.
"""

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from auth.permissions import Role
from db.models import AgentTypes


class RegistrationForm(BaseModel):
    """Agent registration payload (name, skills, description, type)."""

    name: str
    skills: list[str]
    description: str
    type: Optional[AgentTypes] = None


TaskMode = Literal["auto", "specific_agent", "any_with_skill", "decompose"]


class KnowledgeStoreFileRef(BaseModel):
    """Reference to a file already stored in the knowledge-store service.

    The agent worker resolves ``filename`` via the knowledge-store
    ``/file/resolve`` endpoint when the task runs — no content is shipped
    through MAS or RabbitMQ for these refs.
    """

    filename: str


class InlineFile(BaseModel):
    """A one-shot file attached to a task without persisting to the KS.

    ``content_b64`` is base64-encoded file bytes. Capped at ~2 MB per file
    server-side to keep RabbitMQ messages bounded; larger files should go
    through the knowledge store instead.
    """

    filename: str
    mime: Optional[str] = None
    content_b64: str


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
    ``attached_files`` and ``inline_files`` are forwarded to the worker as a
    unified ``files`` array; both default to empty for backward compatibility.
    """

    demand: str
    conversation_id: Optional[int] = None
    skills_required: list[str]
    agent_id: Optional[str] = None
    mode: Optional[TaskMode] = None
    attached_files: list[KnowledgeStoreFileRef] = []
    inline_files: list[InlineFile] = []


class TaskStepForm(BaseModel):
    """Agent-emitted "thought process" step.

    Steps are coarse phase boundaries fired by the agent worker as a task
    progresses (retrieval start/end, reasoning start/end, tool invocation,
    errors). They're broadcast over the chat WebSocket as ``task_step``
    events so the UI can render a live thought-process card.

    All fields except ``task_id``, ``agent_id``, and ``step_type`` are
    optional so older agents that ship a thinner step shape keep working.
    """

    task_id: str
    agent_id: str
    step_type: str
    title: Optional[str] = None
    detail: Optional[str] = None
    timestamp: Optional[str] = None
    conversation_id: Optional[str] = None
    agent_name: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class TaskResultForm(BaseModel):
    """Agent-submitted task result.

    ``agent_name`` and ``skill_used`` are optional metadata used by the chat UI
    to render an attribution chip (which agent answered, which skill ran).
    Older agents that don't send them still work.
    """

    result: str
    conversation_id: Optional[str] = None
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
