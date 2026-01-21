"""
Task Management Routes - Multi-Agent Task Orchestration & Execution

Provides RESTful endpoints for creating, monitoring, and managing tasks within
the multi-agent system. Tasks represent atomic units of work assigned to agents
for processing.

Endpoints:
    POST   /tasks/new_task/         - Create and dispatch a new task
    POST   /tasks/task-result/      - Submit task result from agent
    GET    /tasks/{task_id}         - Get task status and details
    PATCH  /tasks/{task_id}/cancel  - Cancel a running task
    GET    /tasks/stats             - Get task queue statistics

Task Lifecycle:
    1. PENDING    → Task created, waiting for assignment
    2. RUNNING    → Task assigned and being processed by agent
    3. COMPLETED  → Task execution finished successfully
    4. FAILED     → Task execution failed
    5. CANCELLED  → Task was cancelled by user
    6. TIMEOUT    → Task exceeded timeout threshold
    
Request/Response Examples:
    POST /tasks/new_task/
    {
        "demand": "Summarize this text",
        "conversation_id": 1,
        "skills_required": ["summarization"]
    }
    
    Response:
    {
        "message": "Task 'Summarize this text' assigned to agent 8b9f1a3e...",
        "conversation_id": 1,
        "task_id": "task-uuid-1234"
    }
    
    PATCH /tasks/{task_id}/cancel
    {
        "reason": "User requested cancellation"
    }

Task Assignment Strategy:
    - LLM-based agent selection based on skills requirements
    - Load balancing across available agents

Error Codes:
    400 - Bad Request (invalid task definition or cannot cancel)
    401 - Unauthorized (authentication required)
    404 - Not Found (task does not exist)
    500 - Internal Server Error
"""

import json
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from auth.auth_tool_functions import get_current_user, PermissionChecker, verify_agent_api_key
from auth.permissions import Permission
from chat.chat_tool_functions import send_messages_via_websockets
from conversations.conversation_tool_functions import add_messages
from core.logger import log_agent_operation, log_error
from core.metrics import record_task_created, update_task_queue_depth
from core.rabbitmq_tool import rabbitmq_instance
from core.structured_logging import log_task_event
from db.database import get_db
from db.models import Task, TaskResult
from schemas.schemas import TaskForm, TaskResultForm
from tasks.task_tool_functions import (
    TaskStatus,
    cancel_task,
    get_task_queue_stats,
    get_task_status,
    insert_new_task,
    select_agent_for_task,
    validating_task_results,
)

router = APIRouter(prefix="/tasks", tags=["Tasks"])


class TaskCancelRequest(BaseModel):
    """Request body for task cancellation."""
    reason: Optional[str] = "User requested cancellation"



@router.post(
    "/new_task/",
    summary="Create and dispatch a new task",
    description="Attribute a task to the best agent based on the skills required. Publishes the request to the RabbitMQ queue and returns confirmation with task and conversation IDs. Requires TASK_CREATE permission.",
    status_code=200,
    tags=["Tasks"],
    dependencies=[Depends(PermissionChecker(Permission.TASK_CREATE))],
    responses={
        200: {
            "description": "Task successfully created and assigned to an agent",
            "content": {
                "application/json": {
                    "examples": {
                        "assigned": {
                            "summary": "Task assigned to suitable agent",
                            "value": {
                                "message": "Task 'Summarize this text' assigned to agent 8b9f1a3e-7a2c-4d7c-9b1b-2f4b2e0d2e5a",
                                "conversation_id": 1,
                                "task_id": "task-uuid-1234",
                            },
                        },
                        "no_suitable_agent": {
                            "summary": "No agent with required skills but auto-response generated",
                            "value": {
                                "message": "No agent registered to assign a task",
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
            "description": "Internal Server Error - Database or messaging error",
            "content": {
                "application/json": {
                    "examples": {
                        "database_error": {
                            "summary": "Database transaction error",
                            "value": {"detail": "Error: could not create task"},
                        },
                        "rabbitmq_error": {
                            "summary": "Failed to publish task to queue",
                            "value": {"detail": "Error: could not publish to RabbitMQ"},
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
                            "demand": {
                                "type": "string",
                                "description": "The task request/question for the agent(s)",
                                "minLength": 1,
                            },
                            "conversation_id": {
                                "type": "string",
                                "description": "ID of the conversation this task belongs to",
                            },
                            "skills_required": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Array of skill tags for agent matching",
                                "minItems": 1,
                            },
                        },
                        "required": ["demand", "conversation_id", "skills_required"],
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
    },
)
async def create_new_task(
    task: TaskForm, user: Annotated[dict, Depends(PermissionChecker(Permission.TASK_CREATE))], db: Session = Depends(get_db)
):
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication Failed")

    agent_id, user_demand, anticipated_answer, future_actions = select_agent_for_task(
        task.demand, db
    )

    if agent_id is None and anticipated_answer is None:
        add_messages(
            "assistant",
            "No agent registered to assign a task",
            task.conversation_id,
            db,
        )
        return {"message": "No agent registered to assign a task"}

    if anticipated_answer is not None and "Response for user" in anticipated_answer:
        add_messages("assistant", anticipated_answer, task.conversation_id, db)
        return {"message": anticipated_answer}

    history = [{"role": "user", "message": user_demand}]

    task_id = insert_new_task(
        task.conversation_id, agent_id, user_demand, history, future_actions, db
    )
    message = json.dumps(
        {
            "conversation_id": task.conversation_id,
            "task_id": task_id,
        }
    )
    rabbitmq_instance.publish(agent_id, message)

    log_agent_operation(agent_id, "TASK", f"Assigned task {task_id}: {task.demand[:50]}...")

    add_messages("user", task.demand, task.conversation_id, db)
    return {
        "message": f"Task '{task.demand}' assigned to agent {agent_id}",
        "conversation_id": task.conversation_id,
        "task_id": task_id,
    }


@router.post(
    "/task-result/",
    summary="Submit task result from agent",
    description="Receive the result from an agent, add to conversation history, distribute via WebSocket. Handles subtasks and future actions if defined. Requires TASK_EXECUTE permission. Requires 'X-API-Key' and 'Agent-ID' headers for authentication.",
    status_code=200,
    tags=["Tasks"],
    dependencies=[Depends(PermissionChecker(Permission.TASK_EXECUTE))],
    responses={
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
    },
    openapi_extra={
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
                                "type": "string",
                                "description": "Conversation ID this task belongs to",
                            },
                            "agent_id": {
                                "type": "string",
                                "description": "ID of the agent that executed the task",
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
                            "conversation_id",
                            "agent_id",
                        ],
                    },
                    "examples": {
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
    },
)
async def sharing_agent_result(
    task_result: TaskResultForm,
    verified_agent: Annotated[tuple[str, str], Depends(verify_agent_api_key)],
    db: Session = Depends(get_db),
):
    verified_agent_id, _ = verified_agent
    if verified_agent_id != task_result.agent_id:
        raise HTTPException(
            status_code=403,
            detail="Agent ID mismatch: You cannot submit results for another agent",
        )

    try:
        validating_task_results(task_result.task_id, task_result.result, db)
        task = db.query(Task).filter(Task.id == task_result.task_id).first()
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        current_task_result = task.result
        if not current_task_result:
            raise HTTPException(status_code=404, detail="TaskResult not found")

        action_list = current_task_result.future_actions or []
        history = current_task_result.history or []

        task.status = "completed"

        history.append({"role": "assistant", "message": task_result.result})

        current_task_result.result_data = task_result.result
        current_task_result.history = history
        db.commit()

        log_agent_operation(task_result.agent_id, "TASK", f"Completed task {task_result.task_id}")

        if len(action_list) > 0:
            new_agent = action_list[0][0]
            new_action = action_list[0][1]
            remaining_actions = action_list[1:]

            new_subtask_id = insert_new_task(
                task_result.conversation_id,
                new_agent,
                new_action,
                history,
                remaining_actions,
                db,
            )

            subtask = db.query(Task).filter(Task.id == new_subtask_id).first()
            subtask.parent_task_id = task.id
            subtask.order = task.order + 1
            db.commit()

            message = json.dumps(
                {
                    "conversation_id": task.conversation_id,
                    "task_id": new_subtask_id,
                }
            )
            rabbitmq_instance.publish(new_agent, message)
            return {"message": f"Result received from agent {task_result.agent_id}"}

        add_messages("assistant", task_result.result, task_result.conversation_id, db)
        await send_messages_via_websockets(
            task_result.conversation_id, task_result.result
        )
        return {"message": f"Result received from agent {task_result.agent_id}"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=500, detail=f"Error processing task result: {str(e)}"
        )


@router.get(
    "/{task_id}",
    summary="Get task status and details",
    description="Retrieve the current status and details of a specific task. Requires TASK_READ permission.",
    status_code=200,
    tags=["Tasks"],
    dependencies=[Depends(PermissionChecker(Permission.TASK_READ))],
    responses={
        200: {
            "description": "Task details retrieved successfully",
            "content": {
                "application/json": {
                    "example": {
                        "task_id": "task-uuid-1234",
                        "status": "running",
                        "agent_id": "8b9f1a3e-7a2c-4d7c-9b1b-2f4b2e0d2e5a",
                        "conversation_id": 1,
                        "query": "Summarize this document",
                        "created_at": "2025-01-12T10:30:00Z",
                        "result": None,
                    }
                }
            },
        },
        404: {"description": "Task not found"},
    },
)
async def get_task(
    task_id: str,
    user: Annotated[dict, Depends(PermissionChecker(Permission.TASK_READ))],
    db: Session = Depends(get_db),
):
    """Get the status and details of a specific task."""
    return get_task_status(task_id, db)


@router.patch(
    "/{task_id}/cancel",
    summary="Cancel a running task",
    description="Cancel a task that is currently pending or running. Sends a cancellation signal to the assigned agent. Requires TASK_CANCEL permission.",
    status_code=200,
    tags=["Tasks"],
    dependencies=[Depends(PermissionChecker(Permission.TASK_CANCEL))],
    responses={
        200: {
            "description": "Task cancelled successfully",
            "content": {
                "application/json": {
                    "example": {
                        "task_id": "task-uuid-1234",
                        "status": "cancelled",
                        "previous_status": "running",
                        "reason": "User requested cancellation",
                    }
                }
            },
        },
        400: {
            "description": "Task cannot be cancelled (already completed or cancelled)",
            "content": {
                "application/json": {
                    "example": {"detail": "Cannot cancel task with status: completed"}
                }
            },
        },
        404: {"description": "Task not found"},
    },
)
async def cancel_task_endpoint(
    task_id: str,
    cancel_request: TaskCancelRequest,
    user: Annotated[dict, Depends(PermissionChecker(Permission.TASK_CANCEL))],
    db: Session = Depends(get_db),
):
    """Cancel a pending or running task."""
    result = cancel_task(task_id, cancel_request.reason, db)
    
    # Update metrics
    stats = get_task_queue_stats(db)
    update_task_queue_depth(
        pending=stats.get("pending", 0),
        running=stats.get("running", 0),
        completed=stats.get("completed", 0),
        failed=stats.get("failed", 0) + stats.get("cancelled", 0) + stats.get("timeout", 0),
    )
    
    return result


@router.get(
    "/stats/queue",
    summary="Get task queue statistics",
    description="Get statistics about the task queue including counts by status. Requires TASK_READ permission.",
    status_code=200,
    tags=["Tasks"],
    dependencies=[Depends(PermissionChecker(Permission.TASK_READ))],
    responses={
        200: {
            "description": "Task queue statistics",
            "content": {
                "application/json": {
                    "example": {
                        "pending": 5,
                        "running": 3,
                        "completed": 150,
                        "failed": 2,
                        "cancelled": 1,
                        "timeout": 0,
                        "total": 161,
                    }
                }
            },
        },
    },
)
async def get_queue_stats(
    user: Annotated[dict, Depends(PermissionChecker(Permission.TASK_READ))],
    db: Session = Depends(get_db),
):
    """Get task queue statistics."""
    stats = get_task_queue_stats(db)
    
    # Update Prometheus metrics
    update_task_queue_depth(
        pending=stats.get("pending", 0),
        running=stats.get("running", 0),
        completed=stats.get("completed", 0),
        failed=stats.get("failed", 0) + stats.get("cancelled", 0) + stats.get("timeout", 0),
    )
    
    return stats
