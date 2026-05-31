"""Chat WebSocket routes.

Real-time bidirectional channel between clients and the MAS orchestrator.
See ``docs/architecture.md`` for the wire protocol, error codes,
and client examples.
"""

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Query, WebSocket, status
from sqlalchemy.orm import Session

from auth.auth_tool_functions import (PermissionChecker,
                                      get_current_user_from_token)
from auth.permissions import Permission, Role, check_permission
from chat.chat_tool_functions import (_extract_token_from_ws, delete_client,
                                      save_new_client)
from core.logger import get_logger
from db.dependency import get_db
from db.models import Conversations

logger = get_logger("chat")

router = APIRouter(prefix="/chat", tags=["Chat"])


@router.websocket("/{conversation_id}/")
async def chat_websocket(
    websocket: WebSocket,
    conversation_id: str,
    token: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
):
    """Handle a chat WebSocket connection.

    Validates the JWT (query param or ``Authorization`` header), registers the
    client in Redis, then loops on inbound messages until disconnect. Close
    code ``1008`` is used for auth failures. Protocol details in
    ``docs/architecture.md``.

    Args:
        websocket: Inbound WebSocket connection.
        conversation_id: Conversation this socket is bound to.
        token: Optional JWT; falls back to the ``Authorization`` header.
        db: Active database session (DI).
    """
    session_id = None
    try:
        token_str = _extract_token_from_ws(websocket, token)
        user = get_current_user_from_token(token_str)
        user_id = user.get("id")
        username = user.get("username")
        user_role = user.get("payload", {}).get("role")

        if not check_permission(user_role, Permission.TASK_READ):
            logger.warning(
                f"WebSocket authentication failed: Insufficient permissions for user {user_id}"
            )
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        try:
            conv_id_int = int(conversation_id)
        except ValueError:
            logger.warning(f"Invalid conversation ID format: {conversation_id}")
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        conversation = (
            db.query(Conversations).filter(Conversations.id == conv_id_int).first()
        )

        if not conversation:
            logger.warning(f"Conversation not found: {conversation_id}")
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        if conversation.owner_username != username and user_role != Role.ADMIN.value:
            logger.warning(
                f"Unauthorized access to conversation {conversation_id} by user {username}"
            )
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

    except Exception as e:
        logger.warning(
            f"WebSocket authentication failed for conversation: {conversation_id}. Error: {str(e)}"
        )
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await websocket.accept()

    session_id = save_new_client(
        conversation_id, websocket, user_id, token_str, username, user_role
    )
    logger.info(
        f"WebSocket session created: {session_id} for user {user_id} in conversation {conversation_id}"
    )

    try:
        while True:
            await websocket.receive_text()
    except Exception as e:
        logger.debug(f"WebSocket error for session {session_id}: {str(e)}")
    finally:
        if session_id:
            delete_client(conversation_id, websocket, session_id)
            logger.info(f"WebSocket session closed: {session_id}")
