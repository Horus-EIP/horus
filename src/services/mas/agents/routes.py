from fastapi import APIRouter, HTTPException

from agents.registry_tool_functions import (create_agent, delete_agent,
                                            get_agent_details, get_all_agents,
                                            update_alive_agent_status)
from core.rabbitmq_tool import channel
from schemas.schemas import RegistrationForm

router = APIRouter(prefix="/agents", tags=["Agents"])


@router.post(
    "/register",
    summary="Register a new agent",
    description=(
        "Define a new agent with a new name and a list of skills"
        "In case of success, a RabbitMQ is created for the agent, and the ID of the new agent is returned"
        "The name of the Agent have to be unique."
    ),
    status_code=200,
    tags=["Agents"],
    responses={
        200: {
            "description": "Agent created",
            "content": {
                "application/json": {
                    "examples": {
                        "created": {
                            "summary": "Successfully created",
                            "value": {
                                "message": "agent with name Alice successfully created",
                                "agent_id": "8b9f1a3e-7a2c-4d7c-9b1b-2f4b2e0d2e5a",
                            },
                        },
                    }
                }
            },
        },
        409: {
            "description": "An Agent already has this name.",
            "content": {
                "application/json": {
                    "examples": {
                        "name_conflict": {
                            "summary": "Name Already exists.",
                            "value": {"message": "An agent has already the name Alice"},
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
                            "name": {"type": "string"},
                            "skills": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                        },
                        "required": ["name", "skills"],
                    },
                    "examples": {
                        "basic": {
                            "summary": "Basic example",
                            "value": {
                                "name": "Summarizer Agent",
                                "skills_required": ["nlp", "summarization"],
                            },
                        },
                    },
                }
            },
        }
    },
)
async def handle_agent_creation(agent: RegistrationForm):
    # Enforce name uniqueness across existing agents
    for _agent_id, info in get_all_agents().items():
        if info.get("name") == agent.name:
            raise HTTPException(
                status_code=409, detail=f"An agent already has the name '{agent.name}'"
            )
    agent_id = create_agent(agent.name, agent.skills)
    # Ensure a durable queue exists for this agent
    channel.queue_declare(queue=agent_id, passive=False, durable=True, exclusive=False, auto_delete=False)
    return {
        "message": f"agent with name {agent.name} successfully created",
        "agent_id": agent_id,
    }


@router.delete(
    "/unregister/{agent_id}",
    summary="Unregister an agent",
    description="Delete an agent and its RabbitMQ queue associated.",
    status_code=200,
    tags=["Agents"],
    responses={
        200: {
            "description": "Agent successfully erased",
            "content": {
                "application/json": {
                    "examples": {
                        "ok": {
                            "summary": "Agent deleted.",
                            "value": {
                                "message": "Agent 8b9f1a3e-7a2c-4d7c-9b1b-2f4b2e0d2e5a successfully unregistered"
                            },
                        },
                    }
                }
            },
        },
        404: {
            "description": "Agent not Found",
            "content": {
                "application/json": {
                    "examples": {
                        "not_found": {
                            "summary": "Agent not found.",
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
async def unregister_agent(agent_id: str):
    if delete_agent(agent_id):
        channel.queue_delete(agent_id)
        return {"message": f"Agent {agent_id} successfully unregistered"}
    else:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")


@router.get(
    "/details/{id}",
    summary="Get agent details",
    description="Collect informations of an agent with the help of the ID : name, skills, status ('active'/'inactive') and last heartbeat.",
    status_code=200,
    tags=["Agents"],
    responses={
        200: {
            "description": "Details of the agent.",
            "content": {
                "application/json": {
                    "examples": {
                        "details": {
                            "summary": "Details returned.",
                            "value": {
                                "name": "Alice",
                                "skills": ["nlp", "retrieval"],
                                "status": "active",
                                "last_heartbeat": "2025-08-08T12:34:56.789123",
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
                                "message": "Agent not found for the id: 00000000-0000-0000-0000-000000000000"
                            },
                        },
                    }
                }
            },
        },
    },
)
async def agent_details(id: str):
    agent_id, agent_name, agent_skills, agent_status, agent_heartbeat = (
        get_agent_details(id)
    )
    if agent_id is not None:
        return {
            "name": agent_name,
            "skills": agent_skills,
            "status": agent_status,
            "last_heartbeat": agent_heartbeat,
        }
    else:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")


@router.get(
    "/details/",
    summary="List all agents",
    description="Returned informations of all of the agents registered: agent id, name, skills, status, last heartbeat",
    status_code=200,
    tags=["Agents"],
    responses={
        200: {
            "description": "Agent list",
            "content": {
                "application/json": {
                    "example": {
                        "8b9f1a3e-7a2c-4d7c-9b1b-2f4b2e0d2e5a": {
                            "name": "Alice",
                            "skills": ["nlp", "retrieval"],
                            "status": "active",
                            "last_heartbeat": "2025-08-08T12:34:56.789123",
                        },
                        "3c2c6a7b-0b1a-4a4f-9d6e-1a2b3c4d5e6f": {
                            "name": "Bob",
                            "skills": ["vision"],
                            "status": "inactive",
                            "last_heartbeat": "2025-08-08T12:00:00.000000",
                        },
                    }
                }
            },
        }
    },
)
async def get_all_agents_details():
    return get_all_agents()


@router.post(
    "/heartbeat/{agent_id}",
    summary="Send agent heartbeat",
    description=(
        "Met à jour le statut de l’agent à 'active' et rafraîchit le champ 'last_heartbeat'. "
        "Utilisé par les agents pour signaler qu’ils sont en vie."
    ),
    status_code=200,
    tags=["Agents"],
    responses={
        200: {
            "description": "Confirmation",
            "content": {
                "application/json": {
                    "examples": {
                        "ok": {
                            "summary": "Heartbeat reçu",
                            "value": {
                                "message": "Heartbeat received for the agent 8b9f1a3e-7a2c-4d7c-9b1b-2f4b2e0d2e5a"
                            },
                        },
                    }
                }
            },
        },
        404: {
            "description": "Agent introuvable",
            "content": {
                "application/json": {
                    "examples": {
                        "not_found": {
                            "summary": "Agent introuvable",
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
async def detect_alive_agents(agent_id: str):
    update = update_alive_agent_status(agent_id)
    if update:
        return {"message": f"Heartbeat received for the agent {agent_id}"}
    else:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")
