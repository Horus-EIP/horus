"""OpenAPI ``responses`` and ``openapi_extra`` dicts for the agents router.

Extracted from ``agents/routes.py`` to keep that file focused on handler
logic. Dict structure follows FastAPI's route decorator parameters.
"""

# --- POST /agents/register -----------------------------------------------

REGISTER_AGENT_RESPONSES = {
    200: {
        "description": "Agent successfully registered",
        "content": {
            "application/json": {
                "examples": {
                    "created": {
                        "summary": "New agent registered successfully",
                        "value": {
                            "message": "agent with name DocumentAnalyzer successfully created",
                            "agent_id": "8b9f1a3e-7a2c-4d7c-9b1b-2f4b2e0d2e5a",
                            "api_key": "generated_api_key_base64_encoded",
                        },
                    },
                    "with_multiple_skills": {
                        "summary": "Agent with multiple skills",
                        "value": {
                            "message": "agent with name MultiSkillAgent successfully created",
                            "agent_id": "550e8400-e29b-41d4-a716-446655440000",
                            "api_key": "generated_api_key_base64_encoded",
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
    403: {
        "description": "Insufficient permissions - Admin role required",
        "content": {
            "application/json": {
                "examples": {
                    "forbidden": {
                        "summary": "User does not have admin permissions",
                        "value": {
                            "detail": "Admin rights required to perform this operation"
                        },
                    },
                }
            }
        },
    },
    409: {
        "description": "Conflict - Agent name already exists",
        "content": {
            "application/json": {
                "examples": {
                    "name_conflict": {
                        "summary": "Name already taken",
                        "value": {
                            "detail": "An agent already has the name 'DocumentAnalyzer'"
                        },
                    },
                }
            }
        },
    },
    500: {
        "description": "Internal Server Error - Database or RabbitMQ error",
        "content": {
            "application/json": {
                "examples": {
                    "agent_creation_failed": {
                        "summary": "Failed to create agent in database",
                        "value": {"detail": "Failed to create agent"},
                    },
                    "rabbitmq_error": {
                        "summary": "Failed to create RabbitMQ queue",
                        "value": {
                            "detail": "Failed to create RabbitMQ queue: Connection refused"
                        },
                    },
                    "database_error": {
                        "summary": "Database transaction error",
                        "value": {
                            "detail": "Failed to create agent: database error"
                        },
                    },
                }
            }
        },
    },
}

REGISTER_AGENT_OPENAPI_EXTRA = {
    "requestBody": {
        "required": True,
        "content": {
            "application/json": {
                "schema": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Unique name for the agent",
                            "minLength": 1,
                            "maxLength": 100,
                        },
                        "skills": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "List of capabilities/skills this agent can perform",
                            "minItems": 1,
                        },
                        "description": {
                            "type": "string",
                            "description": "Detailed description of agent capabilities and purpose",
                        },
                    },
                    "required": ["name", "skills", "description"],
                },
                "examples": {
                    "document_analyzer": {
                        "summary": "Document analysis agent",
                        "value": {
                            "name": "DocumentAnalyzer",
                            "skills": [
                                "pdf_parsing",
                                "text_extraction",
                                "document_analysis",
                                "nlp",
                            ],
                            "description": "Analyzes PDF documents and extracts key information including metadata and content",
                        },
                    },
                    "summarizer": {
                        "summary": "Text summarization agent",
                        "value": {
                            "name": "SummarizerAgent",
                            "skills": ["nlp", "summarization", "text_processing"],
                            "description": "Generates concise summaries from large text documents",
                        },
                    },
                    "code_reviewer": {
                        "summary": "Code review agent",
                        "value": {
                            "name": "CodeReviewer",
                            "skills": [
                                "code_review",
                                "security_analysis",
                                "python",
                                "javascript",
                                "java",
                            ],
                            "description": "Reviews code for security issues, best practices, and performance optimization",
                        },
                    },
                    "translator": {
                        "summary": "Multi-language translator agent",
                        "value": {
                            "name": "Translator",
                            "skills": [
                                "translation",
                                "nlp",
                                "french",
                                "spanish",
                                "english",
                                "german",
                            ],
                            "description": "Translates documents between multiple languages maintaining context and tone",
                        },
                    },
                },
            }
        },
    }
}


# --- DELETE /agents/unregister/{agent_id} --------------------------------

UNREGISTER_AGENT_RESPONSES = {
    200: {
        "description": "Agent successfully unregistered",
        "content": {
            "application/json": {
                "examples": {
                    "success": {
                        "summary": "Agent successfully removed",
                        "value": {
                            "message": "Agent 8b9f1a3e-7a2c-4d7c-9b1b-2f4b2e0d2e5a successfully unregistered"
                        },
                    },
                    "queue_cleanup_warning": {
                        "summary": "Agent removed but queue deletion may have had issues",
                        "value": {
                            "message": "Agent 550e8400-e29b-41d4-a716-446655440000 successfully unregistered"
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
    403: {
        "description": "Insufficient permissions - Admin role required",
        "content": {
            "application/json": {
                "examples": {
                    "forbidden": {
                        "summary": "User does not have admin privileges",
                        "value": {
                            "detail": "Admin rights required to perform this operation"
                        },
                    },
                }
            }
        },
    },
    404: {
        "description": "Agent not found",
        "content": {
            "application/json": {
                "examples": {
                    "not_found": {
                        "summary": "Agent ID does not exist",
                        "value": {
                            "message": "Agent 00000000-0000-0000-0000-000000000000 not found"
                        },
                    },
                    "already_deleted": {
                        "summary": "Agent was already deleted",
                        "value": {
                            "message": "Agent 12345678-1234-1234-1234-123456789012 not found"
                        },
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
                        "summary": "Database transaction error",
                        "value": {
                            "detail": "Error: could not delete agent from database"
                        },
                    },
                }
            }
        },
    },
}


# --- GET /agents/details/{id} --------------------------------------------

AGENT_DETAILS_RESPONSES = {
    200: {
        "description": "Agent details retrieved successfully",
        "content": {
            "application/json": {
                "examples": {
                    "active_agent": {
                        "summary": "Active agent with multiple skills",
                        "value": {
                            "name": "DocumentAnalyzer",
                            "skills": [
                                "pdf_parsing",
                                "text_extraction",
                                "document_analysis",
                                "nlp",
                            ],
                            "status": "active",
                            "last_heartbeat": "2025-09-25T14:32:18.567890",
                            "description": "Analyzes PDF documents and extracts key information including metadata",
                            "created_at": "2025-09-20T10:00:00.000000",
                        },
                    },
                    "inactive_agent": {
                        "summary": "Inactive agent (no recent heartbeat)",
                        "value": {
                            "name": "LegacyAgent",
                            "skills": ["nlp", "retrieval"],
                            "status": "inactive",
                            "last_heartbeat": "2025-09-20T08:15:00.123456",
                            "description": "Legacy agent awaiting reconfiguration",
                            "created_at": "2025-01-15T09:00:00.000000",
                        },
                    },
                    "recently_activated": {
                        "summary": "Recently activated agent",
                        "value": {
                            "name": "NewTranslator",
                            "skills": [
                                "translation",
                                "french",
                                "spanish",
                                "english",
                            ],
                            "status": "active",
                            "last_heartbeat": "2025-09-25T15:10:22.789012",
                            "description": "Multi-language translation service",
                            "created_at": "2025-09-25T15:00:00.000000",
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
        "description": "Agent not found",
        "content": {
            "application/json": {
                "examples": {
                    "not_found": {
                        "summary": "Agent ID does not exist",
                        "value": {
                            "message": "Agent not found for the id: 00000000-0000-0000-0000-000000000000"
                        },
                    },
                    "invalid_id_format": {
                        "summary": "Invalid UUID format",
                        "value": {
                            "message": "Agent not found for the id: invalid-id-format"
                        },
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
                        "summary": "Database query error",
                        "value": {
                            "detail": "Error: could not retrieve agent details from database"
                        },
                    },
                }
            }
        },
    },
}


# --- GET /agents/details/ ------------------------------------------------

LIST_AGENTS_RESPONSES = {
    200: {
        "description": "Agent list",
        "content": {
            "application/json": {
                "example": [
                    {
                        "id": "8b9f1a3e-7a2c-4d7c-9b1b-2f4b2e0d2e5a",
                        "name": "Alice",
                        "skills": ["nlp", "retrieval"],
                        "status": "active",
                        "last_heartbeat": "2025-08-08T12:34:56.789123",
                        "description": "Alice agent will compute and gives result of mathematical operations",
                        "created_at": "2025-08-01T10:00:00.000000",
                    },
                    {
                        "id": "3c2c6a7b-0b1a-4a4f-9d6e-1a2b3c4d5e6f",
                        "name": "Bob",
                        "skills": ["vision"],
                        "status": "inactive",
                        "last_heartbeat": "2025-08-08T12:00:00.000000",
                        "description": "Bob agent handles image processing tasks",
                        "created_at": "2025-08-02T11:00:00.000000",
                    },
                ]
            }
        },
    }
}


# --- POST /agents/heartbeat/{agent_id} -----------------------------------

HEARTBEAT_RESPONSES = {
    200: {
        "description": "Heartbeat confirmation",
        "content": {
            "application/json": {
                "examples": {
                    "ok": {
                        "summary": "Heartbeat received",
                        "value": {
                            "message": "Heartbeat received for the agent 8b9f1a3e-7a2c-4d7c-9b1b-2f4b2e0d2e5a"
                        },
                    },
                }
            }
        },
    },
    404: {
        "description": "Agent not found",
        "content": {
            "application/json": {
                "examples": {
                    "not_found": {
                        "summary": "Agent not found",
                        "value": {
                            "message": "Agent 00000000-0000-0000-0000-000000000000 not found"
                        },
                    },
                }
            }
        },
    },
}
