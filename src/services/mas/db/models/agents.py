"""``Agents`` ORM model — one row per registered AI agent."""

from sqlalchemy import JSON, Column, DateTime, String
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.sql import func

from db.database import Base
from db.models.agent_types import AgentTypes


class Agents(Base):
    """Agent registered in the MAS directory.

    Heartbeat timestamp + status drive the liveness gauge used by the
    orchestrator when picking a worker.
    """

    __tablename__ = "agents"
    id = Column(String, primary_key=True)
    name = Column(String, unique=True, nullable=False, index=True)
    skills = Column(JSON, default=list, nullable=False)
    status = Column(String, default="inactive", nullable=False)
    description = Column(String, nullable=True)
    last_heartbeat = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
        index=True,
    )
    type: Column = Column(SQLEnum(AgentTypes), nullable=False, default=AgentTypes.GENERAL)
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    api_key = Column(String, unique=True, nullable=False)
