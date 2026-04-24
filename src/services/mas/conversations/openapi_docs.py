"""OpenAPI ``responses`` and ``openapi_extra`` dicts for the conversations router.

Extracted from ``conversations/routes.py`` to keep that file focused on
handler logic. Dict structure follows FastAPI's route decorator parameters.
"""

# --- POST /conversations/create-conversation/ ----------------------------

CREATE_CONVERSATION_RESPONSES = {
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
}

CREATE_CONVERSATION_OPENAPI_EXTRA = {
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
}


# --- GET /conversations/get_history/{chat_id} ----------------------------

GET_HISTORY_RESPONSES = {
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
}


# --- DELETE /conversations/delete-conversation/{chat_id} -----------------

DELETE_CONVERSATION_RESPONSES = {
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
}


# --- GET /conversations/get-conversations/ -------------------------------

LIST_CONVERSATIONS_RESPONSES = {
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
}
