"""``Agents`` ORM model — one row per registered AI agent."""

from datetime import datetime

from sqlalchemy import JSON, DateTime, String
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from db.database import Base
from db.models.agent_types import AgentTypes


class Agents(Base):
    """Agent registered in the MAS directory.

    Heartbeat timestamp + status drive the liveness gauge used by the
    orchestrator when picking a worker.
    """

    __tablename__ = "agents"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    skills: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    status: Mapped[str] = mapped_column(String, default="inactive", nullable=False)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    last_heartbeat: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
        index=True,
    )
    type: Mapped[AgentTypes] = mapped_column(
        SQLEnum(AgentTypes), nullable=False, default=AgentTypes.GENERAL
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    api_key: Mapped[str] = mapped_column(String, unique=True, nullable=False)
