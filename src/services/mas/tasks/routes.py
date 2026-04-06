"""
Task Management Routes - Multi-Agent Task Orchestration & Execution

Provides RESTful endpoints for creating, monitoring, and managing tasks within
the multi-agent system. Tasks represent atomic units of work assigned to agents
for processing.

Endpoints:
    POST   /tasks/new_task/         - Create and dispatch a new task
    POST   /tasks/task-result/      - Submit task result from agent

Task Lifecycle:
    1. CREATED    → Task created, waiting for assignment
    2. ASSIGNED   → Task assigned to agent(s)
    3. EXECUTING  → Agent actively processing task
    4. COMPLETED  → Task execution finished

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

    POST /tasks/task-result/
    {
        "task_id": "task-uuid-1234",
        "result": "Summary content...",
        "conversation_id": 1,
        "agent_id": "8b9f1a3e..."
    }

Task Assignment Strategy:
    - LLM-based agent selection based on skills requirements
    - Load balancing across available agents

Error Codes:
    400 - Bad Request (invalid task definition)
    401 - Unauthorized (authentication required)
    404 - Not Found (task does not exist)
    500 - Internal Server Error
"""

import json
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from auth.auth_tool_functions import (PermissionChecker, get_current_user,
                                      verify_agent_api_key)
from auth.permissions import Permission
from chat.chat_tool_functions import send_messages_via_websockets
from conversations.conversation_tool_functions import add_messages
from core.logger import get_logger, log_agent_operation, log_error
from core.metrics import TASK_ERRORS, TASK_QUEUE_DEPTH
from core.rabbitmq_tool import rabbitmq_instance
from db.database import get_db
from db.models import Task, TaskResult
from schemas.schemas import TaskForm, TaskResultForm
from tasks.status import TaskStatus
from tasks.task_tool_functions import (aggregate_results, decompose_task,
                                       insert_new_task, interrupt_task,
                                       select_agent_for_task,
                                       validating_task_results)

logger = get_logger("task_routes")

router = APIRouter(prefix="/tasks", tags=["Tasks"])


def get_task_queue_stats():
    """Retrieve current task queue statistics."""
    # This is a placeholder that returns stats from metrics/queue system
    # In a real implementation, this would query RabbitMQ or internal counters
    try:
        current_depth = (
            TASK_QUEUE_DEPTH.ephemeral_val()
            if hasattr(TASK_QUEUE_DEPTH, "ephemeral_val")
            else 0
        )
    except:
        current_depth = 0

    return {
        "pending": current_depth,
        "running": 0,
        "completed": 0,
        "failed": 0,
        "cancelled": 0,
        "timeout": 0,
        "total": current_depth,
    }


def update_task_queue_depth(depth: int):
    """Update task queue depth metric."""
    TASK_QUEUE_DEPTH.set(depth)


@router.get(
    "/list",
    summary="List all tasks",
    description="Retrieve all tasks from the database. Requires TASK_READ permission.",
    status_code=200,
    dependencies=[Depends(PermissionChecker(Permission.TASK_READ))],
)
def list_tasks(db: Session = Depends(get_db)):
    tasks = db.query(Task).all()
    logger.info("Listing all tasks", count=len(tasks))
    return tasks


@router.get(
    "/stats/queue",
    summary="Get task queue statistics",
    description="Retrieve current statistics about the task queue including pending, running, and completed tasks. Requires VIEW_ANALYTICS permission.",
    status_code=200,
    dependencies=[Depends(PermissionChecker(Permission.VIEW_ANALYTICS))],
    responses={
        200: {
            "description": "Queue statistics retrieved successfully",
            "content": {
                "application/json": {
                    "examples": {
                        "stats": {
                            "summary": "Current queue stats",
                            "value": {
                                "pending": 5,
                                "running": 2,
                                "completed": 150,
                                "failed": 1,
                                "total": 158,
                            },
                        }
                    }
                }
            },
        },
        403: {
            "description": "Forbidden",
            "content": {
                "application/json": {"example": {"detail": "Insufficient permissions"}}
            },
        },
    },
)
async def get_queue_stats(
    user: Annotated[dict, Depends(PermissionChecker(Permission.VIEW_ANALYTICS))],
):
    """
    Retrieve real-time task statistics from the message queue.

    Returns:
        dict: A dictionary of queue statistics (depth, processed count, error rate).
    """
    stats = get_task_queue_stats()
    logger.info("Queue statistics retrieved", stats=stats)
    return stats


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
    task: TaskForm,
    user: Annotated[dict, Depends(PermissionChecker(Permission.TASK_CREATE))],
    db: Session = Depends(get_db),
):
    """
    Create and dispatch a new task to the most suitable agent.

    This endpoint orchestrates the task creation process:
    1. Selects the best agent based on the demand and required skills (via LLM).
    2. If no agent is found, attempts to decompose the task or returns an error.
    3. If an immediate answer is available (e.g. from cache/LLM), returns it.
    4. Otherwise, creates a Task record in the DB and publishes a message to RabbitMQ.

    Args:
        task (TaskForm): The task definition payload containing demand and requirements.
        user (dict): The authenticated user making the request (injected dependency).
        db (Session): Database session (injected dependency).

    Returns:
        dict: A dictionary containing the assigned agent ID, task ID, and confirmation message.

    Raises:
        HTTPException:
            - 401: If user authentication fails.
            - 500: If there are database or messaging errors.
    """
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication Failed")

    logger.info(
        "Starting agent selection process for new task",
        demand=task.demand[:50],
        conversation_id=task.conversation_id,
    )

    # 1. Selection Phase
    agent_id, user_demand, direct_response, future_actions = select_agent_for_task(
        task.demand, db
    )

    # 2. Direct Answer Handling
    if direct_response:
        add_messages("user", task.demand, task.conversation_id, db)
        add_messages("assistant", direct_response, task.conversation_id, db)
        # We don't create a task, just return the answer
        return {
            "message": "Processing complete",
            "conversation_id": task.conversation_id,
            "result": direct_response,
        }

    # 3. Single Agent Assignment
    if agent_id:
        logger.info("Agent selected for task", agent_id=agent_id)

        history = [{"role": "user", "message": task.demand}]

        task_id = insert_new_task(
            task.conversation_id, agent_id, user_demand, history, future_actions, db
        )

        if not task_id:
            raise HTTPException(status_code=500, detail="Failed to create task")

        message = json.dumps(
            {
                "conversation_id": task.conversation_id,
                "task_id": task_id,
            }
        )
        rabbitmq_instance.publish(agent_id, message)
        TASK_QUEUE_DEPTH.inc()
        log_agent_operation(
            agent_id, "TASK", f"Assigned task {task_id}: {task.demand[:50]}..."
        )

        add_messages("user", task.demand, task.conversation_id, db)
        return {
            "message": f"Task '{task.demand}' assigned to agent {agent_id}",
            "conversation_id": task.conversation_id,
            "task_id": task_id,
        }

    # 4. Decomposition Fallback
    logger.info(
        "No single agent found or COMPLEX_TASK classified. Attempting decomposition."
    )

    first_action, actions_list = await run_in_threadpool(
        decompose_task, task.demand, db
    )

    if not first_action:
        add_messages(
            "assistant",
            "No agent registered to assign a task",
            task.conversation_id,
            db,
        )
        return {"message": "No agent registered to assign a task"}

    agent_id, user_demand = first_action

    history = [{"role": "user", "message": task.demand}]

    task_id = insert_new_task(
        task.conversation_id, agent_id, user_demand, history, actions_list, db
    )
    message = json.dumps(
        {
            "conversation_id": task.conversation_id,
            "task_id": task_id,
        }
    )
    rabbitmq_instance.publish(agent_id, message)

    TASK_QUEUE_DEPTH.inc()
    log_agent_operation(
        agent_id, "TASK", f"Assigned task {task_id}: {task.demand[:50]}..."
    )

    add_messages("user", task.demand, task.conversation_id, db)
    return {
        "message": f"Task '{task.demand}' decomposed and assigned to agent {agent_id}",
        "conversation_id": task.conversation_id,
        "task_id": task_id,
    }


@router.post(
    "/task-result/",
    summary="Submit task result from agent",
    description="Receive the result from an agent, add to conversation history, distribute via WebSocket. Handles subtasks and future actions if defined. Requires TASK_EXECUTE permission. Requires 'X-API-Key' and 'Agent-ID' headers for authentication.",
    status_code=200,
    tags=["Tasks"],
    dependencies=[Depends(verify_agent_api_key)],
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
    """
    Process the result submitted by an agent upon task completion.

    This endpoint handles the final step of a task execution:
    1. Validates the submission and verifies the agent's identity.
    2. Updates the task status to COMPLETED and stores the result.
    3. Handles potential future actions/subtasks (task chaining).
    4. If no further actions, aggregates history and notifies the user via WebSocket.

    Args:
        task_result (TaskResultForm): The task result payload (output, status, suggestions).
        verified_agent (tuple[str, str]): Authenticated agent identifier (unpacked).
        db (Session): Database session (injected dependency).

    Returns:
        dict: Confirmation message on success.

    Raises:
        HTTPException:
            - 403: If agent ID mismatches or lacks permission.
            - 404: If the task or associated result record does not exist.
            - 500: If there is an internal error processing the result (e.g., recursive loop).
    """
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

        task.status = TaskStatus.COMPLETED.value

        history.append({"role": "assistant", "message": task_result.result})

        current_task_result.result_data = task_result.result
        current_task_result.history = history
        db.commit()

        TASK_QUEUE_DEPTH.dec()
        log_agent_operation(
            task_result.agent_id, "TASK", f"Completed task {task_result.task_id}"
        )

        if len(action_list) > 0:
            new_agent = action_list[0][0]
            new_action = action_list[0][1]
            remaining_actions = action_list[1:]

            new_action_context = (
                f"Previous task result: {task_result.result}\n\n Action: {new_action}"
            )

            new_subtask_id = insert_new_task(
                task_result.conversation_id,
                new_agent,
                new_action_context,
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
            TASK_QUEUE_DEPTH.inc()
            logger.info(
                f"Chained to next task: {new_subtask_id} assigned to agent {new_agent}"
            )
            return {"message": f"Result received from agent {task_result.agent_id}"}

        final_answer = aggregate_results(history, task_result.result)
        add_messages("assistant", final_answer, task_result.conversation_id, db)
        await send_messages_via_websockets(task_result.conversation_id, final_answer)
        return {"message": f"Result received from agent {task_result.agent_id}"}
    except HTTPException:
        raise
    except Exception as e:
        TASK_ERRORS.labels(
            agent_id=task_result.agent_id, error_type="processing_error"
        ).inc()
        db.rollback()
        raise HTTPException(
            status_code=500, detail=f"Error processing task result: {str(e)}"
        )


@router.patch(
    "/task-cancel/{task_id}",
    summary="Cancel a running task",
    description="Interrupts a running task by updating its status to CANCELED and sending a high-priority cancellation signal to the assigned agent via RabbitMQ. Requires TASK_DELETE permission.",
    status_code=200,
    tags=["Tasks"],
    dependencies=[Depends(PermissionChecker(Permission.TASK_DELETE))],
    responses={
        200: {
            "description": "Task successfully canceled",
            "content": {
                "application/json": {
                    "examples": {
                        "success": {
                            "summary": "Task canceled",
                            "value": {
                                "message": "Task task-uuid-1234 has been canceled successfully."
                            },
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
    },
)
async def cancel_task(
    task_id: str,
    user: Annotated[dict, Depends(PermissionChecker(Permission.TASK_DELETE))],
    db: Session = Depends(get_db),
):
    """
    Cancel an active task and interrupt its execution.

    This endpoint requests immediate cancellation of a task.
    1. Updates the task status to CANCELLED in the database.
    2. Sends a high-priority cancellation event to the assigned agent via RabbitMQ.
    3. Logs the cancellation (auditable action).

    Args:
        task_id (str): The unique identifier (UUID) of the task to be canceled.
        user (dict): The authenticated user requesting cancellation.
        db (Session): Database session (injected dependency).

    Returns:
        dict: Confirmation message if successfully canceled.

    Raises:
        HTTPException:
            - 401: If user authentication fails.
            - 404: If the task ID is not found.
            - 500: If the cancellation process fails (e.g., agent unreachable or DB lock).
    """
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication Failed")
    try:
        if interrupt_task(task_id, db):
            log_agent_operation(
                "system",
                "TASK_CANCEL",
                f"User {user.get('username')} canceled task {task_id}",
            )
            return {"message": f"Task {task_id} has been canceled successfully."}
    except HTTPException:
        raise
    except Exception as e:
        TASK_ERRORS.labels(agent_id="system", error_type="cancellation_error").inc()
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error Canceling task: {str(e)}")
