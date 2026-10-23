"""HTTP routes for conversation CRUD and history access.

Endpoints are RBAC-gated; owner-only except for admin reads. See
``docs/architecture.md`` for payloads and error codes.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from auth.auth_tool_functions import PermissionChecker
from auth.permissions import Permission, Role
from chat.chat_tool_functions import active_connections
from conversations.conversation_tool_functions import get_conversations, get_history
from conversations.openapi_docs import (
    CREATE_CONVERSATION_OPENAPI_EXTRA,
    CREATE_CONVERSATION_RESPONSES,
    DELETE_CONVERSATION_RESPONSES,
    GET_HISTORY_RESPONSES,
    LIST_CONVERSATIONS_RESPONSES,
)
from core.logger import get_logger
from db.database import get_db
from db.models import Conversations
from schemas.schemas import ConversationCreation

router = APIRouter(prefix="/conversations", tags=["Conversations"])
logger = get_logger("conversations")


@router.post("/create-conversation", include_in_schema=False)
@router.post(
    "/create-conversation/",
    summary="Create a new conversation",
    description="Create a new conversation channel and return the id of this conversation (`conversation_id`). Requires TASK_CREATE permission.",
    status_code=200,
    tags=["Conversations"],
    dependencies=[Depends(PermissionChecker(Permission.TASK_CREATE))],
    responses=CREATE_CONVERSATION_RESPONSES,
    openapi_extra=CREATE_CONVERSATION_OPENAPI_EXTRA,
)
async def create_new_conversation(
    conv_infos: ConversationCreation,
    user: Annotated[dict, Depends(PermissionChecker(Permission.TASK_CREATE))],
    db: Session = Depends(get_db),
) -> dict[str, int]:
    """Create a conversation owned by the caller. Returns ``{conversation_id}``.

    Raises 400 on integrity error, 500 on unexpected DB error.
    """
    new_conversation = Conversations(
        owner_username=user.get("username"),
        name=conv_infos.name,
    )
    try:
        db.add(new_conversation)
        db.commit()
        db.refresh(new_conversation)
        logger.info(
            "Conversation created",
            conversation_id=new_conversation.id,
            username=user.get("username"),
        )
        return {
            "conversation_id": new_conversation.id,
        }

    except IntegrityError as e:
        db.rollback()
        logger.error("Integrity error creating conversation", error=str(e))
        raise HTTPException(status_code=400, detail="Conversation creation failed")
    except SQLAlchemyError as e:
        db.rollback()
        logger.error("Database error creating conversation", error=str(e))
        raise HTTPException(status_code=500, detail="Error: Database error occurred")
    except Exception as e:
        db.rollback()
        logger.error("Unexpected error creating conversation", error=str(e))
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


@router.get(
    "/get_history/{chat_id:int}",
    summary="Get conversation history",
    description="Retrieve the complete message history of a specific conversation. Each entry contains message metadata including role and content. Returns an empty array if no messages exist. Requires TASK_READ permission.",
    status_code=200,
    dependencies=[Depends(PermissionChecker(Permission.TASK_READ))],
    tags=["Conversations"],
    responses=GET_HISTORY_RESPONSES,
)
async def get_conversation_history(
    chat_id: int,
    user: Annotated[dict, Depends(PermissionChecker(Permission.TASK_READ))],
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    """Return all messages in ``chat_id`` (owner/admin only, TASK_READ)."""
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication Failed")

    # Check ownership
    conversation = db.query(Conversations).filter(Conversations.id == chat_id).first()
    if not conversation:
        raise HTTPException(status_code=404, detail=f"Conversation {chat_id} not found")

    if conversation.owner_username != user.get("username") and user.get("role") != Role.ADMIN.value:
        raise HTTPException(
            status_code=403, detail="Only the conversation's owner or an admin can read it"
        )

    history = get_history(chat_id, db)
    if not history:
        logger.info("No history found for conversation", conversation_id=chat_id)
    else:
        logger.info(
            "Retrieved conversation history",
            conversation_id=chat_id,
            message_count=len(history),
        )
    return history


@router.delete(
    "/delete-conversation/{chat_id}",
    summary="Delete a conversation",
    description="Permanently delete a conversation and all its associated messages. Only the owner of the conversation can delete it. Also closes any active WebSocket connections for this conversation. Cascade delete removes all related messages and tasks. Requires TASK_DELETE permission.",
    status_code=200,
    dependencies=[Depends(PermissionChecker(Permission.TASK_DELETE))],
    tags=["Conversations"],
    responses=DELETE_CONVERSATION_RESPONSES,
)
async def remove_conversation(
    chat_id: int,
    user: Annotated[dict, Depends(PermissionChecker(Permission.TASK_DELETE))],
    db: Session = Depends(get_db),
) -> dict[str, str]:
    """Delete a conversation (cascades messages/tasks, closes live WS).

    Owner/admin only, TASK_DELETE. 409 on FK conflict.
    """
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication failed")

    conv = db.get(Conversations, chat_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    conv_owner = (getattr(conv, "owner_username", "") or "").casefold().strip()
    req_user = (user.get("username") or "").casefold().strip()

    if (not conv_owner or conv_owner != req_user) and user.get("role") != Role.ADMIN.value:
        raise HTTPException(status_code=404, detail="Conversation not found")

    try:
        db.delete(conv)
        db.commit()
        logger.info(
            "Conversation deleted successfully",
            conversation_id=chat_id,
            username=req_user,
        )
    except IntegrityError as e:
        db.rollback()
        logger.error(
            "Delete failed due to FK constraint",
            conversation_id=chat_id,
            error=str(e),
        )
        raise HTTPException(status_code=409, detail="Conversation has dependent records")
    except SQLAlchemyError as e:
        db.rollback()
        logger.error(
            "Database error deleting conversation",
            conversation_id=chat_id,
            error=str(e),
        )
        raise HTTPException(status_code=500, detail="Error: Database error occurred")
    except Exception as e:
        db.rollback()
        logger.error(
            "Unexpected error deleting conversation",
            conversation_id=chat_id,
            error=str(e),
        )
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")

    try:
        conns = active_connections.pop(str(chat_id), None)
        if conns:
            for ws in list(conns):
                try:
                    await ws.close()
                except Exception as e:
                    logger.warning(f"Error closing WebSocket for conversation {chat_id}: {str(e)}")
    except Exception as e:
        logger.warning(f"Error managing WebSocket connections for conversation {chat_id}: {str(e)}")

    return {"message": "Conversation correctly deleted"}


@router.get("/get-conversations", include_in_schema=False)
@router.get(
    "/get-conversations/",
    summary="Get user's conversation list",
    description="Retrieve all conversations owned by the authenticated user. Returns basic information about each conversation including ID, name, and creation details. Empty list if user has no conversations. Requires USER_READ permission.",
    status_code=200,
    dependencies=[Depends(PermissionChecker(Permission.USER_READ))],
    tags=["Conversations"],
    responses=LIST_CONVERSATIONS_RESPONSES,
)
async def get_conversation_list(
    user: Annotated[dict, Depends(PermissionChecker(Permission.USER_READ))],
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    """List the caller's conversations (newest first; USER_READ)."""
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication Failed")

    try:
        convs = get_conversations(user.get("username"), db)
        if not convs:
            logger.debug(f"No conversations found for user {user.get('username')}")
        return convs
    except Exception as e:
        logger.error(f"Error retrieving conversations for user {user.get('username')}: {str(e)}")
        raise HTTPException(status_code=500, detail="Error: Failed to retrieve conversations")
