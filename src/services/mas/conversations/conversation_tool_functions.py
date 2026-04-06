"""
Conversation Tool Functions - Message Management & History Tracking

Provides utility functions for managing conversation history, retrieving user
conversations, and adding messages to conversations. These functions form the
core of the conversation persistence layer.

Functions:
    - get_history(conv_id, db): Retrieve message history for a conversation
    - get_conversations(user_name, db): List all conversations for a user
    - add_messages(author, message, conversation_id, db): Add message to conversation
    - get_full_history(conv_id, db): Retrieve complete history without pagination

Key Features:
    - Message ordering by creation timestamp and ID for consistency
    - Conversation filtering by user ownership
    - Transaction management with savepoint support
    - Error handling with proper rollback on failures
    - Support for multiple message authors (user, assistant, system)
    - Automatic session management for standalone function calls

Message Authors:
    - "user": Human user messages
    - "assistant": Agent/AI generated responses
    - "system": System notifications and status updates

Database Operations:
    - Queries are ordered by creation time for chronological consistency
    - Transactions use savepoints for atomic operations
    - Proper rollback and error handling
    - Sessions are automatically managed when not injected
    - Connection properly closed in all code paths

Usage Examples:
    from conversations.conversation_tool_functions import get_history, add_messages

    # Get conversation history
    messages = get_history(conversation_id=1)
    for msg in messages:
        print(f"{msg.role}: {msg.content}")

    # Add message to conversation
    new_msg = add_messages("user", "Hello, analyze this document", 1)

    # Get all conversations for user
    convs = get_conversations("john_doe")
"""

from typing import Any, Dict, List, Optional

from fastapi import Depends
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from core.logger import get_logger
from db.database import SessionLocal, get_db
from db.models import Conversations, Messages

logger = get_logger("conversations")


def get_history(conv_id: int, db: Session = Depends(get_db)) -> List[Dict[str, Any]]:
    """
    Retrieve all messages from a conversation in chronological order.

    Fetches message history for a given conversation, ordering by creation
    timestamp and ID for consistent, chronological ordering. Ensures proper
    transaction handling and connection cleanup.

    Args:
        conv_id (int): The conversation ID to retrieve history for
        db (Session): Database session (injected by FastAPI dependency or passed directly)

    Returns:
        List[Dict]: List of message dictionaries with id, role, content, created_at
                   Returns empty list if conversation has no messages or doesn't exist

    Raises:
        Exception: Logs error but returns empty list (graceful fallback)

    Example:
        >>> messages = get_history(conv_id=1)
        >>> for msg in messages:
        ...     print(f"{msg['role']}: {msg['content']}")
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

        # Convert to dictionaries for consistency
        return [
            {
                "id": msg.id,
                "role": msg.role,
                "content": msg.content,
                "created_at": msg.created_at.isoformat() if msg.created_at else None,
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


def get_full_history(conv_id: int, db: Session = None) -> List[Dict[str, Any]]:
    """
    Retrieve complete conversation history without pagination.

    Useful for export/archive operations. Same as get_history but explicit.

    Args:
        conv_id (int): Conversation ID
        db (Session): Database session

    Returns:
        List[Dict]: Complete message history
    """
    if db is None:
        db = SessionLocal()
    return get_history(conv_id, db)


def get_conversations(
    user_name: str, db: Session = Depends(get_db)
) -> List[Dict[str, Any]]:
    """
    Retrieve all conversations owned by a specific user.

    Fetches all conversations where the user is the owner, ordered by
    most recent modification time (descending) for UI display.
    Ensures proper transaction handling and connection cleanup.

    Args:
        user_name (str): Username of the conversation owner
        db (Session): Database session (injected by FastAPI dependency or passed directly)

    Returns:
        List[Dict]: List of conversation dictionaries ordered by recency
                   Returns empty list if user has no conversations

    Raises:
        Exception: Logs error but returns empty list (graceful fallback)

    Example:
        >>> conversations = get_conversations("john_doe")
        >>> for conv in conversations:
        ...     print(f"Conversation {conv['id']}: {conv['name']}")
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


def get_all_conversations(db: Session = Depends(get_db)) -> List[Dict[str, Any]]:
    """
    Retrieve all conversations owned by a specific user.

    Fetches all conversations where the user is the owner, ordered by
    most recent modification time (descending) for UI display.
    Ensures proper transaction handling and connection cleanup.

    Args:
        user_name (str): Username of the conversation owner
        db (Session): Database session (injected by FastAPI dependency or passed directly)

    Returns:
        List[Dict]: List of conversation dictionaries ordered by recency
                   Returns empty list if user has no conversations

    Raises:
        Exception: Logs error but returns empty list (graceful fallback)

    Example:
        >>> conversations = get_conversations("john_doe")
        >>> for conv in conversations:
        ...     print(f"Conversation {conv['id']}: {conv['name']}")
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
    author: str, message: str, conversation_id: int, db: Session = Depends(get_db)
) -> Optional[Dict[str, Any]]:
    """
    Add a new message to a conversation with proper transaction management.

    Creates and persists a new message within a conversation. Uses transaction
    management with savepoints for atomicity. The message is immediately committed
    to the database and the object is refreshed to include server-generated fields.

    Args:
        author (str): Message author/role (values: "user", "assistant", "system")
        message (str): Message content/text
        conversation_id (int): ID of the conversation to add message to
        db (Session): Database session (injected by FastAPI dependency or passed directly)

    Returns:
        Dict: Created message object with id, role, content, created_at
             Returns None on error (rollback performed)

    Raises:
        Exception: Logs error, rolls back transaction, returns None

    Example:
        >>> msg = add_messages("user", "Please summarize the document", 1)
        >>> if msg:
        ...     print(f"Message {msg['id']} added at {msg['created_at']}")

    Notes:
        - Author must be one of: "user", "assistant", "system"
        - Message content should be validated by caller if needed
        - Timestamps are generated by database server
        - Transaction is committed immediately for durability
        - Includes savepoint for failure recovery
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

        # Create and add message
        msg = Messages(role=author, content=message, conversation_id=conversation_id)
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
