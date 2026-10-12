"""Conversation persistence helpers.

Read, list, and append conversation messages. See
``docs/architecture.md`` for the message-author convention and
session-management rules.
"""

from typing import Any

from fastapi import Depends
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from core.logger import get_logger
from db.database import SessionLocal, get_db
from db.models import Conversations, Messages

logger = get_logger("conversations")


def get_history(conv_id: int, db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    """Return messages of a conversation in chronological order.

    Args:
        conv_id: Conversation id.
        db: Active session (DI or passed in). When omitted, a session is
            opened and closed internally.

    Returns:
        List of message dicts; empty list on error or missing conversation.
    """
    close_db = False
    try:
        # Handle dependency injection from FastAPI
        if db is None or (hasattr(db, "__class__") and "Depends" in str(db.__class__)):
            db = SessionLocal()
            close_db = True

        # Verify conversation exists
        conversation = (
            db.query(Conversations).filter(Conversations.id == conv_id).first()
        )

        if not conversation:
            logger.warning(f"Conversation {conv_id} not found")
            return []

        # Query messages with explicit ordering
        messages = (
            db.query(Messages)
            .filter(Messages.conversation_id == conv_id)
            .order_by(Messages.created_at.asc(), Messages.id.asc())
            .all()
        )

        if messages:
            logger.debug(
                f"Retrieved {len(messages)} messages - Conversation ID: {conv_id}"
            )

        # Convert to dictionaries for consistency. Attribution fields are
        # included so the chat history endpoint returns enough metadata for
        # the frontend to restore agent chips + Manager violet styling on a
        # full page reload.
        return [
            {
                "id": msg.id,
                "role": msg.role,
                "content": msg.content,
                "created_at": msg.created_at.isoformat() if msg.created_at else None,
                "agent_id": msg.agent_id,
                "agent_name": msg.agent_name,
                "skill_used": msg.skill_used,
                "sources": msg.sources,
                "ai_provider": msg.ai_provider,
            }
            for msg in messages
        ]
    except SQLAlchemyError as e:
        logger.error(
            f"Database error retrieving history - Conversation ID: {conv_id}, Error: {str(e)}",
            exc_info=True,
        )
        return []
    except Exception as e:
        logger.error(
            f"Unexpected error retrieving history - Conversation ID: {conv_id}, Error: {str(e)}",
            exc_info=True,
        )
        return []
    finally:
        if close_db and db:
            db.close()


def get_full_history(conv_id: int, db: Session = None) -> list[dict[str, Any]]:
    """Return the full history of a conversation (no pagination).

    Convenience wrapper around :func:`get_history` for export or archive paths.
    """
    if db is None:
        db = SessionLocal()
    return get_history(conv_id, db)


def get_conversations(
    user_name: str, db: Session = Depends(get_db)
) -> list[dict[str, Any]]:
    """List conversations owned by ``user_name``, most-recent first.

    Args:
        user_name: Owner username.
        db: Active session (DI or passed in).

    Returns:
        Conversation dicts ordered by ``modified_at`` descending; empty on error.
    """
    close_db = False
    try:
        # Handle dependency injection from FastAPI
        if db is None or (hasattr(db, "__class__") and "Depends" in str(db.__class__)):
            db = SessionLocal()
            close_db = True

        conversations = (
            db.query(Conversations)
            .filter(Conversations.owner_username == user_name)
            .order_by(Conversations.modified_at.desc())
            .all()
        )

        if conversations:
            logger.debug(
                f"Retrieved {len(conversations)} conversations - User: {user_name}"
            )

        # Convert to dictionaries
        return [
            {
                "id": conv.id,
                "name": conv.name,
                "owner_username": conv.owner_username,
                "created_at": conv.created_at.isoformat() if conv.created_at else None,
                "modified_at": (
                    conv.modified_at.isoformat() if conv.modified_at else None
                ),
            }
            for conv in conversations
        ]
    except SQLAlchemyError as e:
        logger.error(
            f"Database error retrieving conversations - User: {user_name}, Error: {str(e)}",
            exc_info=True,
        )
        return []
    except Exception as e:
        logger.error(
            f"Unexpected error retrieving conversations - User: {user_name}, Error: {str(e)}",
            exc_info=True,
        )
        return []
    finally:
        if close_db and db:
            db.close()


def get_all_conversations(db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    """List every conversation (admin/audit use), most-recent first.

    Unlike :func:`get_conversations`, not filtered by owner. Intended for
    admin views; callers must enforce RBAC upstream.
    """
    close_db = False
    try:
        # Handle dependency injection from FastAPI
        if db is None or (hasattr(db, "__class__") and "Depends" in str(db.__class__)):
            db = SessionLocal()
            close_db = True

        conversations = (
            db.query(Conversations).order_by(Conversations.modified_at.desc()).all()
        )

        if conversations:
            logger.debug(f"Retrieved {len(conversations)} conversations")

        # Convert to dictionaries
        return [
            {
                "id": conv.id,
                "name": conv.name,
                "owner_username": conv.owner_username,
                "created_at": conv.created_at.isoformat() if conv.created_at else None,
                "modified_at": (
                    conv.modified_at.isoformat() if conv.modified_at else None
                ),
            }
            for conv in conversations
        ]
    except SQLAlchemyError as e:
        logger.error(
            f"Database error retrieving conversations, Error: {str(e)}",
            exc_info=True,
        )
        return []
    except Exception as e:
        logger.error(
            f"Unexpected error retrieving conversations, Error: {str(e)}",
            exc_info=True,
        )
        return []
    finally:
        if close_db and db:
            db.close()


def add_messages(
    author: str,
    message: str,
    conversation_id: int,
    db: Session = Depends(get_db),
    *,
    agent_id: str | None = None,
    agent_name: str | None = None,
    skill_used: str | None = None,
    sources: list[dict[str, Any]] | None = None,
    ai_provider: str | None = None,
) -> dict[str, Any] | None:
    """Append one message to a conversation inside a savepoint.

    Args:
        author: ``"user"``, ``"assistant"``, or ``"system"``.
        message: Message body.
        conversation_id: Target conversation.
        db: Active session (DI or passed in).
        agent_id: Originating agent UUID (kw-only). Persists alongside the
            row so chat-history reload can restore attribution chips +
            Manager violet styling. Pass ``None`` for user messages.
        agent_name: Human-readable agent name (kw-only).
        skill_used: Skill the agent exercised (kw-only).

    Returns:
        The created message dict, or ``None`` if the conversation is missing
        or a database error occurs (transaction rolled back).
    """
    close_db = False
    savepoint = None

    try:
        # Handle dependency injection from FastAPI
        if db is None or (hasattr(db, "__class__") and "Depends" in str(db.__class__)):
            db = SessionLocal()
            close_db = True

        # Verify conversation exists before adding message
        conversation = (
            db.query(Conversations).filter(Conversations.id == conversation_id).first()
        )

        if not conversation:
            logger.warning(
                f"Conversation {conversation_id} not found - cannot add message"
            )
            return None

        # Create savepoint for nested transaction
        savepoint = db.begin_nested()

        # Create and add message (with optional attribution metadata).
        msg = Messages(
            role=author,
            content=message,
            conversation_id=conversation_id,
            agent_id=agent_id,
            agent_name=agent_name,
            skill_used=skill_used,
            sources=sources,
            ai_provider=ai_provider,
        )
        db.add(msg)

        # Commit nested transaction
        savepoint.commit()

        # Commit main transaction
        db.commit()
        db.refresh(msg)

        logger.info(
            f"Message added successfully - Message ID: {msg.id}, "
            f"Author: {author}, Conversation ID: {conversation_id}"
        )

        return {
            "id": msg.id,
            "role": msg.role,
            "content": msg.content,
            "created_at": msg.created_at.isoformat() if msg.created_at else None,
            "agent_id": msg.agent_id,
            "agent_name": msg.agent_name,
            "skill_used": msg.skill_used,
            "sources": msg.sources,
            "ai_provider": msg.ai_provider,
        }

    except SQLAlchemyError as e:
        if savepoint:
            try:
                savepoint.rollback()
            except Exception:
                pass
        try:
            db.rollback()
        except Exception:
            pass
        logger.error(
            f"Database error adding message - Author: {author}, "
            f"Conversation ID: {conversation_id}, Error: {str(e)}",
            exc_info=True,
        )
        return None
    except Exception as e:
        if savepoint:
            try:
                savepoint.rollback()
            except Exception:
                pass
        try:
            db.rollback()
        except Exception:
            pass
        logger.error(
            f"Unexpected error adding message - Author: {author}, "
            f"Conversation ID: {conversation_id}, Error: {str(e)}",
            exc_info=True,
        )
        return None
    finally:
        if close_db and db:
            db.close()
