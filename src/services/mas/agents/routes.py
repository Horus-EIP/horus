"""
Agent Management Routes - Multi-Agent System API

Provides RESTful endpoints for managing agent registration, lifecycle management,
and heartbeat monitoring. All agent operations require proper authentication and
most administrative operations require admin privileges.

Endpoints:
    POST   /agents/register          - Register a new agent with specified skills
    DELETE /agents/unregister/{agent_id} - Unregister an agent
    GET    /agents/details/{id}      - Get details for a specific agent
    GET    /agents/details/          - List all available agents
    POST   /agents/heartbeat/{agent_id} - Update agent heartbeat status

Security:
    - All endpoints require user authentication via JWT token
    - Agent registration and deletion require admin privileges
    - Heartbeat updates are performed by agents themselves
    
Request/Response Examples:
    POST /agents/register
    {
        "name": "DocumentProcessor",
        "skills": ["pdf_parsing", "text_extraction", "ocr"],
        "description": "Processes and extracts information from PDF documents"
    }
    
    Response:
    {
        "message": "agent with name DocumentProcessor successfully created",
        "agent_id": "8b9f1a3e-7a2c-4d7c-9b1b-2f4b2e0d2e5a"
    }

Error Codes:
    401 - Unauthorized (invalid or missing JWT token)
    403 - Forbidden (insufficient privileges)
    409 - Conflict (duplicate agent name)
    404 - Not Found (agent does not exist)
    500 - Internal Server Error
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from agents.registry_tool_functions import (create_agent, delete_agent,
                                            get_agent_details, get_agent_id,
                                            get_all_agents,
                                            update_alive_agent_status)
from auth.auth_tool_functions import get_current_user, PermissionChecker, verify_agent_api_key
from auth.permissions import Permission
from core.logger import log_agent_operation, log_error
from core.rabbitmq_tool import rabbitmq_instance
from db.database import get_db
from schemas.schemas import RegistrationForm

router = APIRouter(prefix="/agents", tags=["Agents"])

@router.post(
    "/register",
    summary="Register a new agent",
    description="Register a new agent with specified skills and capabilities. Agent name must be unique. Creates a dedicated RabbitMQ queue for task assignment.",
    status_code=200,
    dependencies=[Depends(PermissionChecker(Permission.AGENT_CREATE))],
    tags=["Agents"],
    responses={
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
                                "api_key": "generated_api_key_base64_encoded"
                            },
                        },
                        "with_multiple_skills": {
                            "summary": "Agent with multiple skills",
                            "value": {
                                "message": "agent with name MultiSkillAgent successfully created",
                                "agent_id": "550e8400-e29b-41d4-a716-446655440000",
                                "api_key": "generated_api_key_base64_encoded"
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
    },
)
async def handle_agent_creation(
    agent: RegistrationForm, user: Annotated[dict, Depends(PermissionChecker(Permission.AGENT_CREATE))], db: Session = Depends(get_db)
):
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication Failed")

    agent_exists = get_agent_id(agent.name, db)

    if agent_exists is not None:
        raise HTTPException(
            status_code=409, detail=f"An agent already has the name '{agent.name}'"
        )

    agent_id, api_key = create_agent(agent.name, agent.skills, agent.description, db)

    if agent_id is None:
        log_error("AGENT", f"Failed to create agent {agent.name}")
        raise HTTPException(status_code=500, detail="Failed to create agent")

    try:
        rabbitmq_instance.create_queue(agent_id)
    except Exception as e:
        log_error("AGENT", f"Failed to create RabbitMQ queue for {agent.name}: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Failed to create RabbitMQ queue: {str(e)}"
        )

    log_agent_operation(agent.name, "REGISTER", f"ID: {agent_id}, Skills: {agent.skills}")

    return {
        "message": f"agent with name {agent.name} successfully created",
        "agent_id": agent_id,
        "api_key": api_key,
    }


@router.delete(
    "/unregister/{agent_id}",
    summary="Unregister an agent",
    description="Remove an agent from the system and delete its associated RabbitMQ queue. This operation cannot be undone. Only admin users can perform this operation.",
    status_code=200,
    dependencies=[Depends(PermissionChecker(Permission.AGENT_DELETE))],
    tags=["Agents"],
    responses={
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
    },
)
async def unregister_agent(
    agent_id: str, user: Annotated[dict, Depends(PermissionChecker(Permission.AGENT_DELETE))], db: Session = Depends(get_db)
):
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication Failed")
    if delete_agent(agent_id, db):
        try:
            rabbitmq_instance.delete_queue(agent_id)
        except Exception as e:
            log_error("AGENT", f"Failed to delete queue for {agent_id}: {str(e)}")
            pass  # Log but don't fail if queue deletion fails
        
        log_agent_operation(agent_id, "UNREGISTER", "Agent deleted")
        return {"message": f"Agent {agent_id} successfully unregistered"}
    else:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")


@router.get(
    "/details/{id}",
    summary="Get agent details",
    description="Retrieve detailed information about a specific agent including name, skills, current status (active/inactive), and last heartbeat timestamp. Requires AGENT_READ permission.",
    status_code=200,
    tags=["Agents"],
    dependencies=[Depends(PermissionChecker(Permission.AGENT_READ))],
    responses={
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
    },
)
async def agent_details(id: str, user: Annotated[dict, Depends(PermissionChecker(Permission.AGENT_READ))], db: Session = Depends(get_db)):
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication Failed")
    (
        agent_id,
        agent_name,
        agent_skills,
        agent_status,
        agent_heartbeat,
        agent_description,
        agent_creation_date,
    ) = get_agent_details(id, db)
    if agent_id is not None:
        return {
            "name": agent_name,
            "skills": agent_skills,
            "status": agent_status,
            "last_heartbeat": agent_heartbeat,
            "description": agent_description,
            "created_at": agent_creation_date,
        }
    else:
        raise HTTPException(status_code=404, detail=f"Agent {id} not found")


@router.get(
    "/details/",
    summary="List all agents",
    description="Returned informations of all of the agents registered: agent id, name, skills, status, last heartbeat. Requires AGENT_READ permission.",
    status_code=200,
    dependencies=[Depends(PermissionChecker(Permission.AGENT_READ))],
    tags=["Agents"],
    responses={
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
    },
)
async def get_all_agents_details(user: Annotated[dict, Depends(PermissionChecker(Permission.AGENT_READ))], db: Session = Depends(get_db)):
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication Failed")
    return get_all_agents(db)


@router.post(
    "/heartbeat/{agent_id}",
    summary="Send agent heartbeat",
    description=(
        "Updates the agent status to 'active' and refreshes the 'last_heartbeat' field. "
        "Used by agents to signal that they are alive and operational. Requires AGENT_EXECUTE permission. "
        "Requires 'X-API-Key' and 'Agent-ID' headers for authentication."
    ),
    status_code=200,
    dependencies=[Depends(PermissionChecker(Permission.AGENT_EXECUTE))],
    tags=["Agents"],
    responses={
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
    },
)
async def detect_alive_agents(
    agent_id: str,
    verified_agent: Annotated[tuple[str, str], Depends(verify_agent_api_key)],
    db: Session = Depends(get_db),
):
    verified_agent_id, _ = verified_agent
    if verified_agent_id != agent_id:
        raise HTTPException(status_code=403, detail="Agent ID mismatch")

    update = update_alive_agent_status(agent_id, db)
    if update:
        return {"message": f"Heartbeat received for the agent {agent_id}"}
    else:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")
