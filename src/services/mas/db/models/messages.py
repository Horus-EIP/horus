"""``Messages`` ORM model + audit listeners."""

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    event,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from core.logger import log_db_operation
from db.database import Base


class Messages(Base):
    """One message in a ``Conversation``.

    ``role`` is one of ``user``, ``assistant``, ``system``. Cascaded delete
    from its parent conversation.
    """

    __tablename__ = "messages"
    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    role = Column(String, nullable=False)
    content = Column(String, nullable=False)
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Agent attribution captured at write time so chat history reloads keep
    # the Manager's violet bubble + each specialist's name chip. Nullable
    # because: (a) user-role messages have no attribution, and (b) older
    # rows pre-dating these columns won't have values.
    agent_id = Column(String, nullable=True)
    agent_name = Column(String, nullable=True)
    skill_used = Column(String, nullable=True)
    sources = Column(JSON, nullable=True)

    conversation_id = Column(
        Integer,
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    conversation = relationship("Conversations", back_populates="messages")

    __table_args__ = (
        Index("idx_messages_conversation_created", "conversation_id", "created_at"),
    )


@event.listens_for(Messages, "after_insert")
def log_message_insert(mapper, connection, target):
    """Log message creation events for conversation auditing."""
    log_db_operation(
        "CREATE",
        "messages",
        f"id: {target.id}, conversation: {target.conversation_id}, role: {target.role}",
    )


@event.listens_for(Messages, "after_update")
def log_message_update(mapper, connection, target):
    """Log message modification events for conversation auditing."""
    log_db_operation("UPDATE", "messages", f"id: {target.id}")


@event.listens_for(Messages, "after_delete")
def log_message_delete(mapper, connection, target):
    """Log message deletion events for conversation auditing."""
    log_db_operation("DELETE", "messages", f"id: {target.id}")
