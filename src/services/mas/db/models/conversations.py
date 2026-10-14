"""``Conversations`` ORM model + audit listeners."""

from core.logger import log_db_operation
from db.database import Base
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, event
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func


class Conversations(Base):
    """Chat session owned by a ``User``.

    Deleting a conversation cascades to its messages and tasks. Deleting the
    owner sets ``owner_username`` to ``NULL`` (soft orphan).
    """

    __tablename__ = "conversations"
    id = Column(Integer, primary_key=True, autoincrement=True)

    owner_username = Column(
        String,
        ForeignKey("users.username", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    name = Column(String, nullable=True)

    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    modified_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    owner = relationship(
        "Users",
        back_populates="conversations",
        foreign_keys=[owner_username],
        cascade="save-update",
        viewonly=False,
    )

    messages = relationship(
        "Messages",
        back_populates="conversation",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    tasks = relationship(
        "Task",
        back_populates="conversation",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


@event.listens_for(Conversations, "after_insert")
def log_conversation_insert(mapper, connection, target):
    """Log conversation creation events for usage tracking."""
    log_db_operation(
        "CREATE", "conversations", f"id: {target.id}, owner: {target.owner_username}"
    )


@event.listens_for(Conversations, "after_update")
def log_conversation_update(mapper, connection, target):
    """Log conversation modification events for usage tracking."""
    log_db_operation("UPDATE", "conversations", f"id: {target.id}")


@event.listens_for(Conversations, "after_delete")
def log_conversation_delete(mapper, connection, target):
    """Log conversation deletion events for usage tracking."""
    log_db_operation("DELETE", "conversations", f"id: {target.id}")
