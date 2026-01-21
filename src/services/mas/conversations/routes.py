from typing import Annotated, Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from auth.auth_tool_functions import get_current_user, PermissionChecker
from auth.permissions import Permission
from chat.chat_tool_functions import active_connections
from conversations.conversation_tool_functions import (
    get_history,
    get_conversations,
)
from core.logger import get_logger
from db.database import get_db
from db.models import Conversations
from schemas.schemas import ConversationCreation
from auth.permissions import Role

"""
Conversation Management Routes - Multi-Agent System API

Provides RESTful endpoints for managing conversations, message history, and
multi-agent task orchestration. Conversations represent ongoing interactions
between users and multiple agents working collaboratively.

Endpoints:
    POST   /conversations/create-conversation/  - Create a new conversation
    GET    /conversations/get-conversations/    - List conversations for authenticated user
    GET    /conversations/get_history/{chat_id} - Get conversation history
    DELETE /conversations/delete-conversation/{chat_id} - Delete a conversation

Security:
    - All endpoints require user authentication via JWT token
    - Users can only access their own conversations
    - Conversation ownership is enforced at the database level

Request/Response Examples:
    POST /conversations/create-conversation/
    {
        "name": "PDF Analysis Session"
    }

    Response:
    {
        "conversation_id": 1
    }

    GET /conversations/get_history/1
    Response:
    [
        {
            "id": 1,
            "role": "user",
            "content": "Hello",
            "created_at": "2025-01-15T10:30:00Z"
        }
    ]

Message Flow:
    1. User sends message to conversation
    2. System routes message to appropriate agent(s)
    3. Agent(s) process and return results
    4. Response added to conversation history
    5. User receives aggregated results

Error Codes:
    400 - Bad Request (invalid message format)
    401 - Unauthorized (missing authentication)
    403 - Forbidden (insufficient permissions)
    404 - Not Found (conversation does not exist)
    409 - Conflict (cannot modify completed conversation)
"""

router = APIRouter(prefix="/conversations", tags=["Conversations"])
logger = get_logger("conversations")


@router.post(
    "/create-conversation/",
    summary="Create a new conversation",
    description="Create a new conversation channel and return the id of this conversation (`conversation_id`). Requires TASK_CREATE permission.",
    status_code=200,
    tags=["Conversations"],
    dependencies=[Depends(PermissionChecker(Permission.TASK_CREATE))],
    responses={
        200: {
            "description": "Conversation created successfully",
            "content": {
                "application/json": {
                    "examples": {
                        "success": {
                            "summary": "Conversation successfully created",
                            "value": {"conversation_id": 1},
                        }
                    }
                }
            },
        },
        400: {
            "description": "Bad Request - Conversation creation failed",
            "content": {
                "application/json": {
                    "examples": {
                        "integrity_error": {
                            "summary": "Database integrity error",
                            "value": {"detail": "Conversation creation failed"},
                        },
                    }
                }
            },
        },
        401: {
            "description": "Authentication Failed",
            "content": {
                "application/json": {
                    "examples": {
                        "auth_failed": {
                            "summary": "Missing or invalid authentication token",
                            "value": {"detail": "Authentication Failed"},
                        },
                        "expired_token": {
                            "summary": "Token expired",
                            "value": {"detail": "Token has expired"},
                        },
                    }
                }
            },
        },
        403: {
            "description": "Forbidden - Insufficient permissions",
            "content": {
                "application/json": {
                    "examples": {
                        "forbidden": {
                            "summary": "User lacks TASK_CREATE permission",
                            "value": {"detail": "Insufficient permissions"},
                        },
                    }
                }
            },
        },
        422: {
            "description": "Request body validation error",
            "content": {
                "application/json": {
                    "examples": {
                        "validation_error": {
                            "summary": "Invalid request body",
                            "value": {
                                "detail": [
                                    {
                                        "loc": ["body", "name"],
                                        "msg": "field required",
                                        "type": "value_error.missing",
                                    }
                                ]
                            },
                        },
                        "invalid_type": {
                            "summary": "Invalid field type",
                            "value": {
                                "detail": [
                                    {
                                        "loc": ["body", "name"],
                                        "msg": "str type expected",
                                        "type": "type_error.str",
                                    }
                                ]
                            },
                        },
                    }
                }
            },
        },
        500: {
            "description": "Internal Server Error - Database or system error",
            "content": {
                "application/json": {
                    "examples": {
                        "database_error": {
                            "summary": "Database connection error",
                            "value": {"detail": "Error: could not connect to database"},
                        },
                        "unexpected_error": {
                            "summary": "Unexpected system error",
                            "value": {
                                "detail": "Error: Internal server error occurred"
                            },
                        },
                    }
                }
            },
        },
    },
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {
                        "type": "object",
                        "properties": {
                            "name": {
                                "type": "string",
                                "description": "The name/title for the new conversation",
                                "minLength": 1,
                                "maxLength": 255,
                            },
                        },
                        "required": ["name"],
                    },
                    "examples": {
                        "basic": {
                            "summary": "Basic conversation creation",
                            "value": {"name": "Chat with AI Assistant"},
                        },
                        "support": {
                            "summary": "Support conversation",
                            "value": {"name": "Technical Support Request"},
                        },
                        "project": {
                            "summary": "Project discussion with special characters",
                            "value": {
                                "name": "Project Planning (Q1/Q2) Discussion 2025"
                            },
                        },
                        "long_title": {
                            "summary": "Conversation with longer descriptive title",
                            "value": {
                                "name": "Quarterly Financial Analysis & Strategic Planning Meeting"
                            },
                        },
                        "minimal": {
                            "summary": "Minimal title",
                            "value": {"name": "Chat"},
                        },
                    },
                }
            },
        }
    },
)
async def create_new_conversation(
    conv_infos: ConversationCreation,
    user: Annotated[dict, Depends(PermissionChecker(Permission.TASK_CREATE))],
    db: Session = Depends(get_db),
) -> Dict[str, int]:
    """Create a new conversation in the database.

    Creates a new conversation owned by the authenticated user. The conversation ID
    is auto-generated by the database and returned to the client.
    Requires TASK_CREATE permission.

    Returns:
        Dict with conversation_id (int) for newly created conversation

    Raises:
        HTTPException 401: If user is not authenticated
        HTTPException 403: If user lacks TASK_CREATE permission
        HTTPException 400: If conversation creation fails due to integrity error
        HTTPException 500: If unexpected database error occurs
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
            f"Conversation {new_conversation.id} created for user {user.get('username')}"
        )
        return {
            "conversation_id": new_conversation.id,
        }

    except IntegrityError as e:
        db.rollback()
        logger.error(f"Integrity error creating conversation: {str(e)}")
        raise HTTPException(status_code=400, detail="Conversation creation failed")
    except SQLAlchemyError as e:
        db.rollback()
        logger.error(f"Database error creating conversation: {str(e)}")
        raise HTTPException(status_code=500, detail="Error: Database error occurred")
    except Exception as e:
        db.rollback()
        logger.error(f"Unexpected error creating conversation: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


@router.get(
    "/get_history/{chat_id:int}",
    summary="Get conversation history",
    description="Retrieve the complete message history of a specific conversation. Each entry contains message metadata including role and content. Returns an empty array if no messages exist. Requires TASK_READ permission.",
    status_code=200,
    dependencies=[Depends(PermissionChecker(Permission.TASK_READ))],
    tags=["Conversations"],
    responses={
        200: {
            "description": "Conversation history retrieved successfully",
            "content": {
                "application/json": {
                    "examples": {
                        "with_messages": {
                            "summary": "Conversation with multiple messages",
                            "value": [
                                {
                                    "id": 1,
                                    "role": "user",
                                    "content": "Hello, can you help me?",
                                    "created_at": "2025-09-25T10:30:00Z",
                                },
                                {
                                    "id": 2,
                                    "role": "assistant",
                                    "content": "Hello! How can I help you?",
                                    "created_at": "2025-09-25T10:30:05Z",
                                },
                                {
                                    "id": 3,
                                    "role": "user",
                                    "content": "I need analysis of this document",
                                    "created_at": "2025-09-25T10:31:00Z",
                                },
                                {
                                    "id": 4,
                                    "role": "assistant",
                                    "content": "I'll analyze the document for you...",
                                    "created_at": "2025-09-25T10:31:05Z",
                                },
                            ],
                        },
                        "empty_history": {
                            "summary": "Newly created conversation with no messages",
                            "value": [],
                        },
                        "single_message": {
                            "summary": "Conversation with only user message",
                            "value": [
                                {
                                    "id": 1,
                                    "role": "user",
                                    "content": "Please start analyzing...",
                                    "created_at": "2025-09-25T10:30:00Z",
                                }
                            ],
                        },
                    }
                }
            },
        },
        401: {
            "description": "Authentication Failed",
            "content": {
                "application/json": {
                    "examples": {
                        "auth_failed": {
                            "summary": "Missing or invalid authentication",
                            "value": {"detail": "Authentication Failed"},
                        },
                    }
                }
            },
        },
        403: {
            "description": "Forbidden - Insufficient permissions",
            "content": {
                "application/json": {
                    "examples": {
                        "forbidden": {
                            "summary": "User lacks TASK_READ permission",
                            "value": {"detail": "Insufficient permissions"},
                        },
                    }
                }
            },
        },
        404: {
            "description": "Conversation not found",
            "content": {
                "application/json": {
                    "examples": {
                        "not_found": {
                            "summary": "Conversation ID does not exist",
                            "value": {"detail": "Conversation 123 not found"},
                        }
                    }
                }
            },
        },
        500: {
            "description": "Internal Server Error - Database error",
            "content": {
                "application/json": {
                    "examples": {
                        "database_error": {
                            "summary": "Database connection error",
                            "value": {
                                "detail": "Error: could not retrieve history from database"
                            },
                        },
                    }
                }
            },
        },
    },
)
async def get_conversation_history(
    chat_id: int,
    user: Annotated[dict, Depends(PermissionChecker(Permission.TASK_READ))],
    db: Session = Depends(get_db),
) -> List[Dict[str, Any]]:
    """Retrieve conversation history from database.

    Fetches all messages in a conversation ordered by creation time.
    Only the conversation owner or an admin can retrieve their history.
    Requires TASK_READ permission.

    Args:
        chat_id (int): Conversation ID to retrieve history for
        user: Current authenticated user
        db: Database session

    Returns:
        List of message dictionaries with id, role, content, created_at

    Raises:
        HTTPException 401: If user is not authenticated
        HTTPException 403: If user lacks TASK_READ permission
        HTTPException 404: If conversation doesn't exist
    """
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication Failed")

    # Check ownership
    conversation = db.query(Conversations).filter(Conversations.id == chat_id).first()
    if not conversation:
        raise HTTPException(status_code=404, detail=f"Conversation {chat_id} not found")
    
    if conversation.owner_username != user.get("username") and user.get("role") != Role.ADMIN.value:
        raise HTTPException(status_code=404, detail=f"Conversation {chat_id} not found")

    history = get_history(chat_id, db)
    if not history:
        logger.warning(f"No history found for conversation {chat_id}")
    return history


@router.delete(
    "/delete-conversation/{chat_id}",
    summary="Delete a conversation",
    description="Permanently delete a conversation and all its associated messages. Only the owner of the conversation can delete it. Also closes any active WebSocket connections for this conversation. Cascade delete removes all related messages and tasks. Requires TASK_DELETE permission.",
    status_code=200,
    dependencies=[Depends(PermissionChecker(Permission.TASK_DELETE))],
    tags=["Conversations"],
    responses={
        200: {
            "description": "Conversation successfully deleted",
            "content": {
                "application/json": {
                    "examples": {
                        "success": {
                            "summary": "Conversation deleted successfully",
                            "value": {"message": "Conversation correctly deleted"},
                        },
                        "with_websocket_closed": {
                            "summary": "Conversation deleted and WebSocket connections closed",
                            "value": {"message": "Conversation correctly deleted"},
                        },
                    }
                }
            },
        },
        401: {
            "description": "Authentication Failed",
            "content": {
                "application/json": {
                    "examples": {
                        "auth_failed": {
                            "summary": "Missing or invalid authentication",
                            "value": {"detail": "Authentication failed"},
                        },
                        "expired_token": {
                            "summary": "Token expired",
                            "value": {"detail": "Authentication failed"},
                        },
                    }
                }
            },
        },
        403: {
            "description": "Forbidden - Insufficient permissions or not owner",
            "content": {
                "application/json": {
                    "examples": {
                        "forbidden": {
                            "summary": "User lacks TASK_DELETE permission",
                            "value": {"detail": "Insufficient permissions"},
                        },
                        "not_owner": {
                            "summary": "Attempting to delete conversation owned by another user",
                            "value": {"detail": "Conversation not found"},
                        },
                    }
                }
            },
        },
        404: {
            "description": "Conversation not found",
            "content": {
                "application/json": {
                    "examples": {
                        "not_found": {
                            "summary": "Conversation ID does not exist",
                            "value": {"detail": "Conversation not found"},
                        },
                        "already_deleted": {
                            "summary": "Conversation was already deleted",
                            "value": {"detail": "Conversation not found"},
                        },
                    }
                }
            },
        },
        409: {
            "description": "Conflict - Conversation has dependent records",
            "content": {
                "application/json": {
                    "examples": {
                        "constraint_error": {
                            "summary": "Cannot delete due to foreign key constraints",
                            "value": {"detail": "Conversation has dependent records"},
                        },
                        "active_tasks": {
                            "summary": "Conversation has active tasks",
                            "value": {"detail": "Conversation has dependent records"},
                        },
                    }
                }
            },
        },
        500: {
            "description": "Internal Server Error - Database or WebSocket error",
            "content": {
                "application/json": {
                    "examples": {
                        "database_error": {
                            "summary": "Database transaction error",
                            "value": {
                                "detail": "Error: could not delete conversation from database"
                            },
                        },
                        "websocket_error": {
                            "summary": "Error closing WebSocket connections",
                            "value": {
                                "detail": "Error: error closing active connections"
                            },
                        },
                    }
                }
            },
        },
    },
)
async def remove_conversation(
    chat_id: int,
    user: Annotated[dict, Depends(PermissionChecker(Permission.TASK_DELETE))],
    db: Session = Depends(get_db),
) -> Dict[str, str]:
    """Delete a conversation and all its associated messages.

    Permanently deletes a conversation. Cascade delete removes all related
    messages and tasks. Also closes any active WebSocket connections.
    Only the conversation owner or an admin can delete it.
    Requires TASK_DELETE permission.

    Args:
        chat_id (int): ID of conversation to delete
        user: Current authenticated user
        db: Database session

    Returns:
        Dict with success message

    Raises:
        HTTPException 401: If user is not authenticated
        HTTPException 403: If user lacks TASK_DELETE permission
        HTTPException 404: If conversation not found or user not owner
        HTTPException 409: If conversation has dependent records that can't be deleted
        HTTPException 500: If database or websocket error occurs
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
        logger.info(f"Conversation {chat_id} deleted successfully for user {req_user}")
    except IntegrityError as e:
        db.rollback()
        logger.error(
            f"Delete failed due to FK constraint for conversation_id={chat_id}, Error: {str(e)}"
        )
        raise HTTPException(
            status_code=409, detail="Conversation has dependent records"
        )
    except SQLAlchemyError as e:
        db.rollback()
        logger.error(f"Database error deleting conversation {chat_id}: {str(e)}")
        raise HTTPException(status_code=500, detail="Error: Database error occurred")
    except Exception as e:
        db.rollback()
        logger.error(f"Unexpected error deleting conversation {chat_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")

    try:
        conns = active_connections.pop(str(chat_id), None)
        if conns:
            for ws in list(conns):
                try:
                    await ws.close()
                except Exception as e:
                    logger.warning(
                        f"Error closing WebSocket for conversation {chat_id}: {str(e)}"
                    )
    except Exception as e:
        logger.warning(
            f"Error managing WebSocket connections for conversation {chat_id}: {str(e)}"
        )

    return {"message": "Conversation correctly deleted"}


@router.get(
    "/get-conversations/",
    summary="Get user's conversation list",
    description="Retrieve all conversations owned by the authenticated user. Returns basic information about each conversation including ID, name, and creation details. Empty list if user has no conversations. Requires USER_READ permission.",
    status_code=200,
    dependencies=[Depends(PermissionChecker(Permission.USER_READ))],
    tags=["Conversations"],
    responses={
        200: {
            "description": "List of user's conversations retrieved successfully",
            "content": {
                "application/json": {
                    "examples": {
                        "multiple_conversations": {
                            "summary": "User with multiple conversations",
                            "value": [
                                {
                                    "id": 1,
                                    "name": "Chat with AI Assistant",
                                    "created_at": "2025-09-25T10:30:00Z",
                                    "modified_at": "2025-09-25T10:35:00Z",
                                    "owner_username": "user123",
                                },
                                {
                                    "id": 2,
                                    "name": "Technical Support Request",
                                    "created_at": "2025-09-24T15:45:00Z",
                                    "modified_at": "2025-09-24T16:00:00Z",
                                    "owner_username": "user123",
                                },
                                {
                                    "id": 3,
                                    "name": "Project Planning Session",
                                    "created_at": "2025-09-20T08:15:00Z",
                                    "modified_at": "2025-09-20T09:30:00Z",
                                    "owner_username": "user123",
                                },
                            ],
                        },
                        "single_conversation": {
                            "summary": "User with one conversation",
                            "value": [
                                {
                                    "id": 1,
                                    "name": "Initial Chat",
                                    "created_at": "2025-09-25T10:30:00Z",
                                    "modified_at": "2025-09-25T10:30:00Z",
                                    "owner_username": "user123",
                                }
                            ],
                        },
                        "no_conversations": {
                            "summary": "New user with no conversations",
                            "value": [],
                        },
                    }
                }
            },
        },
        401: {
            "description": "Authentication Failed",
            "content": {
                "application/json": {
                    "examples": {
                        "auth_failed": {
                            "summary": "Missing or invalid authentication token",
                            "value": {"detail": "Authentication Failed"},
                        },
                        "expired_token": {
                            "summary": "Token has expired",
                            "value": {"detail": "Authentication Failed"},
                        },
                    }
                }
            },
        },
        403: {
            "description": "Forbidden - Insufficient permissions",
            "content": {
                "application/json": {
                    "examples": {
                        "forbidden": {
                            "summary": "User lacks USER_READ permission",
                            "value": {"detail": "Insufficient permissions"},
                        },
                    }
                }
            },
        },
        500: {
            "description": "Internal Server Error - Database error",
            "content": {
                "application/json": {
                    "examples": {
                        "database_error": {
                            "summary": "Database connection error",
                            "value": {
                                "detail": "Error: could not retrieve conversations from database"
                            },
                        },
                    }
                }
            },
        },
    },
)
async def get_conversation_list(
    user: Annotated[dict, Depends(PermissionChecker(Permission.USER_READ))],
    db: Session = Depends(get_db),
) -> List[Dict[str, Any]]:
    """Retrieve all conversations for the authenticated user.

    Returns a list of all conversations owned by the user, sorted by most recent.
    Each conversation includes id, name, owner_username, created_at, modified_at.
    Requires USER_READ permission.

    Args:
        user: Current authenticated user
        db: Database session

    Returns:
        List of conversation dictionaries sorted by modification time (newest first)

    Raises:
        HTTPException 401: If user is not authenticated
        HTTPException 403: If user lacks USER_READ permission
    """
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication Failed")

    try:
        convs = get_conversations(user.get("username"), db)
        if not convs:
            logger.debug(f"No conversations found for user {user.get('username')}")
        return convs
    except Exception as e:
        logger.error(
            f"Error retrieving conversations for user {user.get('username')}: {str(e)}"
        )
        raise HTTPException(
            status_code=500, detail="Error: Failed to retrieve conversations"
        )
