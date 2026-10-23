"""OpenAPI ``responses`` and ``openapi_extra`` dicts for the tasks router.

Extracted from ``tasks/routes.py`` to keep that file focused on handler
logic. Dict structure follows FastAPI's route decorator parameters.
"""

# --- /tasks/stats/queue --------------------------------------------------

QUEUE_STATS_RESPONSES = {
    200: {
        "description": "Queue statistics retrieved successfully",
        "content": {
            "application/json": {
                "examples": {
                    "stats": {
                        "summary": "Current queue stats",
                        "value": {
                            "queued": 1,
                            "pending": 5,
                            "running": 2,
                            "completed": 150,
                            "failed": 1,
                            "cancelled": 0,
                            "total": 159,
                        },
                    }
                }
            }
        },
    },
    403: {
        "description": "Forbidden",
        "content": {"application/json": {"example": {"detail": "Insufficient permissions"}}},
    },
}


# --- POST /tasks/new_task ------------------------------------------------

CREATE_TASK_RESPONSES = {
    202: {
        "description": (
            "Task stored with status queued. Routing runs in the background; "
            "the outcome arrives as task events. A replayed Idempotency-Key "
            "returns the original task with the header Idempotent-Replayed: true."
        ),
        "content": {
            "application/json": {
                "examples": {
                    "queued": {
                        "summary": "Task queued for routing",
                        "value": {
                            "task_id": "3f6c2a9e-1b7d-4c8e-9a51-6e0b2d4f8c13",
                            "status": "queued",
                            "conversation_id": 1,
                        },
                    },
                    "replayed": {
                        "summary": "Retry with the same Idempotency-Key",
                        "value": {
                            "task_id": "3f6c2a9e-1b7d-4c8e-9a51-6e0b2d4f8c13",
                            "status": "running",
                            "conversation_id": 1,
                        },
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
    404: {
        "description": "Conversation not found",
        "content": {
            "application/json": {
                "examples": {
                    "conversation_not_found": {
                        "summary": "Conversation ID does not exist",
                        "value": {"detail": "Conversation not found"},
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
                        "summary": "Missing required fields",
                        "value": {
                            "detail": [
                                {
                                    "loc": ["body", "demand"],
                                    "msg": "field required",
                                    "type": "value_error.missing",
                                }
                            ]
                        },
                    },
                    "invalid_array": {
                        "summary": "Skills_required is not array",
                        "value": {
                            "detail": [
                                {
                                    "loc": ["body", "skills_required"],
                                    "msg": "value is not a valid list",
                                    "type": "type_error.list",
                                }
                            ]
                        },
                    },
                }
            }
        },
    },
    500: {
        "description": "Internal Server Error - the task could not be stored",
        "content": {
            "application/json": {
                "examples": {
                    "database_error": {
                        "summary": "The queued task could not be stored",
                        "value": {"detail": "Failed to create task"},
                    },
                }
            }
        },
    },
}

CREATE_TASK_OPENAPI_EXTRA = {
    "requestBody": {
        "required": True,
        "content": {
            "application/json": {
                "schema": {
                    "type": "object",
                    "properties": {
                        "demand": {
                            "type": "string",
                            "description": "The task request/question for the agent(s)",
                            "minLength": 1,
                        },
                        "conversation_id": {
                            "type": ["integer", "null"],
                            "description": "Optional conversation this task belongs to. Omit (or null) for standalone tasks created from the Tasks page.",
                        },
                        "skills_required": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Array of skill tags for agent matching",
                            "minItems": 1,
                        },
                        "attached_files": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "filename": {"type": "string"},
                                    "doc_id": {"type": "string"},
                                },
                                "required": ["filename"],
                            },
                            "description": (
                                "Files already stored in the knowledge store, "
                                "referenced by filename and, optionally, by "
                                "knowledge-store document id (doc_id), which "
                                "tells apart documents that share a filename. "
                                "The worker resolves their text on demand."
                            ),
                        },
                        "inline_files": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "filename": {"type": "string"},
                                    "mime": {"type": "string"},
                                    "content_b64": {"type": "string"},
                                },
                                "required": ["filename", "content_b64"],
                            },
                            "description": (
                                "One-shot files attached without persisting to "
                                "the knowledge store. Capped at ~2 MB each."
                            ),
                        },
                    },
                    "required": ["demand", "skills_required"],
                },
                "examples": {
                    "document_analysis": {
                        "summary": "Document analysis task",
                        "value": {
                            "demand": "Analyze the quarterly financial report and extract key metrics",
                            "conversation_id": 1,
                            "skills_required": [
                                "nlp",
                                "document_analysis",
                                "financial_analysis",
                            ],
                        },
                    },
                    "text_summarization": {
                        "summary": "Text summarization task",
                        "value": {
                            "demand": "Summarize this text in 100 words",
                            "conversation_id": 2,
                            "skills_required": ["nlp", "summarization"],
                        },
                    },
                    "code_review": {
                        "summary": "Code review task",
                        "value": {
                            "demand": "Review this Python code for security issues and best practices",
                            "conversation_id": 3,
                            "skills_required": [
                                "code_review",
                                "security",
                                "python",
                            ],
                        },
                    },
                    "data_extraction": {
                        "summary": "Data extraction with multiple skills",
                        "value": {
                            "demand": "Extract all customer names and email addresses from the provided document",
                            "conversation_id": 4,
                            "skills_required": [
                                "data_extraction",
                                "nlp",
                                "pattern_matching",
                            ],
                        },
                    },
                },
            }
        },
    }
}


# --- POST /tasks/task-result/ --------------------------------------------

SHARE_RESULT_RESPONSES = {
    200: {
        "description": "Task result received and processed successfully",
        "content": {
            "application/json": {
                "examples": {
                    "single_result": {
                        "summary": "Result received, no follow-up tasks",
                        "value": {
                            "message": "Result received from agent 8b9f1a3e-7a2c-4d7c-9b1b-2f4b2e0d2e5a"
                        },
                    },
                    "with_subtask": {
                        "summary": "Result received with follow-up subtask",
                        "value": {
                            "message": "Result received from agent 8b9f1a3e-7a2c-4d7c-9b1b-2f4b2e0d2e5a"
                        },
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
    404: {
        "description": "Task or TaskResult not found",
        "content": {
            "application/json": {
                "examples": {
                    "task_not_found": {
                        "summary": "Task ID does not exist",
                        "value": {"detail": "Task not found"},
                    },
                    "result_not_found": {
                        "summary": "No result record for task",
                        "value": {"detail": "TaskResult not found"},
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
                        "summary": "Missing required fields",
                        "value": {
                            "detail": [
                                {
                                    "loc": ["body", "task_id"],
                                    "msg": "field required",
                                    "type": "value_error.missing",
                                }
                            ]
                        },
                    },
                    "invalid_result_type": {
                        "summary": "Result field has wrong type",
                        "value": {
                            "detail": [
                                {
                                    "loc": ["body", "result"],
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
        "description": "Internal Server Error - Database or messaging error",
        "content": {
            "application/json": {
                "examples": {
                    "database_error": {
                        "summary": "Database transaction error",
                        "value": {"detail": "Error: could not update task result"},
                    },
                    "websocket_error": {
                        "summary": "Failed to send result via WebSocket",
                        "value": {"detail": "Error: could not broadcast result"},
                    },
                }
            }
        },
    },
}

SHARE_RESULT_OPENAPI_EXTRA = {
    "requestBody": {
        "required": True,
        "content": {
            "application/json": {
                "schema": {
                    "type": "object",
                    "properties": {
                        "task_id": {
                            "type": "string",
                            "description": "ID of the task being completed",
                        },
                        "result": {
                            "type": "string",
                            "description": "The result/output from task execution",
                            "minLength": 1,
                        },
                        "conversation_id": {
                            "type": ["string", "null"],
                            "description": "Conversation ID this task belongs to. Empty/omitted for standalone tasks.",
                        },
                        "agent_id": {
                            "type": "string",
                            "description": "ID of the agent that executed the task",
                        },
                        "status": {
                            "type": "string",
                            "enum": ["completed", "not_found", "failed"],
                            "default": "completed",
                            "description": (
                                "completed: an answer. not_found: the documents do not "
                                "contain it. failed: no answer. A first not_found or failed "
                                "answer is asked for once more (not after a timeout)."
                            ),
                        },
                        "reason": {
                            "type": ["string", "null"],
                            "maxLength": 64,
                            "description": (
                                "Why the answer is not completed: not_in_documents, "
                                "invalid_output, degenerate_output, retrieval_error, "
                                "timeout or error"
                            ),
                        },
                        "sources": {
                            "type": ["array", "null"],
                            "maxItems": 100,
                            "description": "The retrieved passages the answer cites",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "doc_id": {"type": ["string", "null"]},
                                    "chunk_id": {"type": ["string", "null"]},
                                    "title": {"type": ["string", "null"]},
                                    "page": {"type": ["integer", "null"]},
                                },
                            },
                        },
                        "history": {
                            "type": "array",
                            "description": "Message history for context (optional)",
                        },
                        "future_actions": {
                            "type": "array",
                            "description": "List of follow-up tasks (optional)",
                        },
                    },
                    "required": [
                        "task_id",
                        "result",
                        "agent_id",
                    ],
                },
                "examples": {
                    "answer_with_sources": {
                        "summary": "Answer citing the passages it used",
                        "value": {
                            "task_id": "task_004",
                            "result": "Q4 2025 revenue was $4.2M.",
                            "conversation_id": "1",
                            "agent_id": "8b9f1a3e-7a2c-4d7c-9b1b-2f4b2e0d2e5a",
                            "status": "completed",
                            "sources": [
                                {
                                    "doc_id": "6d0e2f1a",
                                    "chunk_id": "6d0e2f1a:3",
                                    "title": "1_Q4_2025_Financial_Report.md",
                                    "page": None,
                                }
                            ],
                        },
                    },
                    "not_found": {
                        "summary": "The documents do not contain the answer",
                        "value": {
                            "task_id": "task_005",
                            "result": "The documents do not give the 2027 budget.",
                            "conversation_id": "1",
                            "agent_id": "8b9f1a3e-7a2c-4d7c-9b1b-2f4b2e0d2e5a",
                            "status": "not_found",
                            "reason": "not_in_documents",
                            "sources": [],
                        },
                    },
                    "simple_result": {
                        "summary": "Simple task result",
                        "value": {
                            "task_id": "task_001",
                            "result": "The summary is: Document contains quarterly results showing 15% growth.",
                            "conversation_id": 1,
                            "agent_id": "8b9f1a3e-7a2c-4d7c-9b1b-2f4b2e0d2e5a",
                        },
                    },
                    "with_history": {
                        "summary": "Result with conversation history",
                        "value": {
                            "task_id": "task_002",
                            "result": "Translation: The quarterly report shows significant growth.",
                            "conversation_id": 2,
                            "agent_id": "9a8c1d2e-3f4g-5h6i-7j8k-9l0m1n2o3p4q",
                            "history": [
                                {
                                    "role": "user",
                                    "message": "Analyze this quarterly report",
                                },
                                {
                                    "role": "assistant",
                                    "message": "Analysis: Growth metrics indicate positive trend...",
                                },
                            ],
                        },
                    },
                    "with_subtasks": {
                        "summary": "Result with follow-up subtasks",
                        "value": {
                            "task_id": "task_003",
                            "result": "Initial analysis complete. Key metrics extracted.",
                            "conversation_id": 3,
                            "agent_id": "8b9f1a3e-7a2c-4d7c-9b1b-2f4b2e0d2e5a",
                            "future_actions": [
                                [
                                    "9a8c1d2e-3f4g-5h6i-7j8k-9l0m1n2o3p4q",
                                    "Translate results to French",
                                ],
                                [
                                    "agent-003",
                                    "Format results as PDF report",
                                ],
                            ],
                        },
                    },
                },
            }
        },
    }
}


# --- PATCH /tasks/task-cancel/{task_id} ----------------------------------

CANCEL_TASK_RESPONSES = {
    200: {
        "description": "Task successfully canceled",
        "content": {
            "application/json": {
                "examples": {
                    "success": {
                        "summary": "Task canceled",
                        "value": {"message": "Task task-uuid-1234 has been canceled successfully."},
                    }
                }
            }
        },
    },
    400: {
        "description": "Bad Request - Task cannot be canceled",
        "content": {
            "application/json": {
                "examples": {
                    "already_completed": {
                        "summary": "Task already finished",
                        "value": {"detail": "Cannot interrupt a completed task"},
                    }
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
    404: {
        "description": "Task not found",
        "content": {
            "application/json": {
                "examples": {
                    "task_not_found": {
                        "summary": "Task ID does not exist",
                        "value": {"detail": "Task not found"},
                    },
                }
            }
        },
    },
    500: {
        "description": "Internal Server Error",
        "content": {
            "application/json": {
                "examples": {
                    "cancellation_error": {
                        "summary": "Failed to cancel task",
                        "value": {"detail": "Error Canceling task: Database error"},
                    }
                }
            }
        },
    },
}
