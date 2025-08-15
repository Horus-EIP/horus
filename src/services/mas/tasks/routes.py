from fastapi import APIRouter
import json

from chat.chat_tool_functions import send_messages_via_websockets
from conversations.conversation_tool_functions import add_messages
from core.rabbitmq_tool import channel
from schemas.schemas import TaskForm, TaskResultForm
from tasks.task_tool_functions import select_agent_for_task

router = APIRouter(prefix="/tasks", tags=["Tasks"])


@router.post(
    "/new_task/",
    summary="Create and dispatch a new task",
    description="Attribute a task to the best agent in function of the skills required for this question, publish the request to the RabbitMQ queue and return a confirmation message and the id of the conversation.",
    status_code=200,
    tags=["Tasks"],
    responses={
        200: {
            "description": "Task successfully assigned",
            "content": {
                "application/json": {
                    "examples": {
                        "assigned": {
                            "summary": "Task successfully assigned",
                            "value": {
                                "message": "Task 'Summarize this text' assigned to agent 8b9f1a3e-7a2c-4d7c-9b1b-2f4b2e0d2e5a",
                                "conversation_id": "3c2c6a7b-0b1a-4a4f-9d6e-1a2b3c4d5e6f",
                            },
                        },
                    }
                }
            },
        },
        404: {
            "description": "No agent found",
            "content": {
                "application/json": {
                    "examples": {
                        "no_agent": {
                            "summary": "Aucun agent available",
                            "value": {
                                "message": "No agent available to execute this task"
                            },
                        },
                    }
                }
            },
        },
        422: {"description": "Erreur de validation du corps de requête"},
    },
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {  # déduit de TaskForm, on montre aussi des exemples
                        "type": "object",
                        "properties": {
                            "demand": {"type": "string"},
                            "conversation_id": {"type": "string"},
                            "skills_required": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                        },
                        "required": ["demand", "conversation_id", "skills_required"],
                    },
                    "examples": {
                        "basic": {
                            "summary": "Exemple basique",
                            "value": {
                                "demand": "Résumer ce texte : ...",
                                "conversation_id": "3c2c6a7b-0b1a-4a4f-9d6e-1a2b3c4d5e6f",
                                "skills_required": ["nlp", "summarization"],
                            },
                        },
                    },
                }
            },
        }
    },
)
async def create_new_task(task: TaskForm):
    agent_id = select_agent_for_task(task.skills_required)
    if agent_id == "":
        return {"message": "No agent registered to assign a task"}
    # Send a structured JSON message so the Agent can parse demand and conversation_id
    message = json.dumps(
        {
            "demand": task.demand,
            "conversation_id": task.conversation_id,
        }
    )
    channel.basic_publish(exchange="", routing_key=agent_id, body=message)

    add_messages("user", task.demand, task.conversation_id)
    return {
        "message": f"Task '{task.demand}' assigned to agent {agent_id}",
        "conversation_id": task.conversation_id,
    }


@router.post(
    "/task-result/",
    summary="Submit task result from agent",
    description=(
        "Receive the result furnished by the agent, add this result to the conversation's history and diffuse the answer by Websocket."
    ),
    status_code=200,
    tags=["Tasks"],
    responses={
        200: {
            "description": "Result received",
            "content": {
                "application/json": {
                    "examples": {
                        "received": {
                            "summary": "Résultat received",
                            "value": {
                                "message": "Result received from agent 8b9f1a3e-7a2c-4d7c-9b1b-2f4b2e0d2e5a"
                            },
                        }
                    }
                }
            },
        },
        422: {"description": "Erreur de validation du corps de requête"},
    },
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {
                        "type": "object",
                        "properties": {
                            "result": {"type": "string"},
                            "conversation_id": {"type": "string"},
                            "agent_id": {"type": "string"},
                        },
                        "required": ["result", "conversation_id", "agent_id"],
                    },
                    "examples": {
                        "ok": {
                            "summary": "Exemple de résultat",
                            "value": {
                                "result": "Voici le résumé demandé : ...",
                                "conversation_id": "3c2c6a7b-0b1a-4a4f-9d6e-1a2b3c4d5e6f",
                                "agent_id": "8b9f1a3e-7a2c-4d7c-9b1b-2f4b2e0d2e5a",
                            },
                        }
                    },
                }
            },
        }
    },
)
async def sharing_agent_result(task_result: TaskResultForm):
    add_messages("assistant", task_result.result, task_result.conversation_id)
    await send_messages_via_websockets(task_result.conversation_id, task_result.result)
    return {"message": f"Result received from agent {task_result.agent_id}"}
