"""SQLAlchemy ORM models for the MAS service.

Entities: :class:`Users`, :class:`Conversations`, :class:`Messages`,
:class:`Agents`, :class:`Task`, :class:`TaskResult`, :class:`CriticalLogs`.
See ``docs/architecture.md`` for schema, relationships, and
audit conventions.

Each model lives in its own module alongside its SQLAlchemy event listeners.
Everything is re-exported from this package so ``from db.models import X``
continues to work.
"""

from db.models.agent_types import AgentTypes
from db.models.agents import Agents
from db.models.conversations import Conversations
from db.models.critical_logs import CriticalLogs
from db.models.messages import Messages
from db.models.tasks import Task, TaskResult
from db.models.users import Users

__all__ = [
    "AgentTypes",
    "Agents",
    "Conversations",
    "CriticalLogs",
    "Messages",
    "Task",
    "TaskResult",
    "Users",
]
