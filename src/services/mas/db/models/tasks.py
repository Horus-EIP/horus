"""``Task`` + ``TaskResult`` ORM models with audit listeners."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Integer, String, event
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from core.logger import log_db_operation
from db.database import Base
from tasks.status import TaskStatus, is_final_status


class Task(Base):
    __tablename__ = "tasks"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    conversation_id = Column(
        Integer,
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    parent_task_id = Column(String, ForeignKey("tasks.id"), nullable=True)
    agent_id = Column(String, nullable=False)
    status = Column(
        SQLEnum(TaskStatus, values_callable=lambda obj: [e.value for e in obj]),
        default=TaskStatus.PENDING.value,
    )
    query = Column(String, nullable=False)
    order = Column(Integer, nullable=True)
    skills_required = Column(JSON, nullable=True)
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    completed_at = Column(DateTime(timezone=True), nullable=True)

    conversation = relationship(
        "Conversations", back_populates="tasks", passive_deletes=True
    )
    parent_task = relationship("Task", remote_side=[id], backref="subtasks")
    result = relationship(
        "TaskResult", back_populates="task", uselist=False, cascade="all, delete-orphan"
    )


class TaskResult(Base):
    __tablename__ = "task_results"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    task_id = Column(
        String, ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    result_data = Column(JSON, nullable=True)
    history = Column(JSON, nullable=True)
    future_actions = Column(JSON, nullable=True)
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    task = relationship("Task", back_populates="result")


@event.listens_for(Task.status, "set")
def stamp_completed_at_on_final_status(target, value, oldvalue, initiator):
    if is_final_status(value) and target.completed_at is None:
        target.completed_at = datetime.now(UTC)


@event.listens_for(Task, "after_insert")
def log_task_insert(mapper, connection, target):
    """Log task creation events for task tracking."""
    log_db_operation(
        "CREATE",
        "tasks",
        f"id: {target.id}, conversation: {target.conversation_id}, agent: {target.agent_id}, status: {target.status}",
    )


@event.listens_for(Task, "after_update")
def log_task_update(mapper, connection, target):
    """Log task modification events for task tracking."""
    log_db_operation("UPDATE", "tasks", f"id: {target.id}, status: {target.status}")


@event.listens_for(Task, "after_delete")
def log_task_delete(mapper, connection, target):
    """Log task deletion events for task tracking."""
    log_db_operation(
        "DELETE", "tasks", f"id: {target.id}, conversation: {target.conversation_id}"
    )


@event.listens_for(TaskResult, "after_insert")
def log_task_result_insert(mapper, connection, target):
    """Log task result creation events."""
    log_db_operation(
        "CREATE", "task_results", f"id: {target.id}, task: {target.task_id}"
    )


@event.listens_for(TaskResult, "after_update")
def log_task_result_update(mapper, connection, target):
    """Log task result modification events."""
    log_db_operation(
        "UPDATE", "task_results", f"id: {target.id}, task: {target.task_id}"
    )
