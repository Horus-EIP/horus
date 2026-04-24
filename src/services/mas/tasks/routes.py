"""HTTP routes for task orchestration.

Task creation, status queries, cancellation, and result ingestion from
agents. See ``docs/architecture/mas_service.md`` for the task lifecycle,
payload shapes, and error codes.
"""

import json
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
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
from tasks.openapi_docs import (CANCEL_TASK_RESPONSES, CREATE_TASK_OPENAPI_EXTRA,
                                CREATE_TASK_RESPONSES, QUEUE_STATS_RESPONSES,
                                SHARE_RESULT_OPENAPI_EXTRA, SHARE_RESULT_RESPONSES)
from tasks.status import TaskStatus
from tasks.task_tool_functions import (aggregate_results, decompose_task,
                                       insert_new_task, interrupt_task,
                                       select_agent_for_task,
                                       validating_task_results)

logger = get_logger("task_routes")

router = APIRouter(prefix="/tasks", tags=["Tasks"])


def get_task_queue_stats(db: Session) -> dict[str, Any]:
    """Aggregate task counts by status from the database."""
    rows = db.query(Task.status, func.count(Task.id)).group_by(Task.status).all()
    counts = {
        "pending": 0,
        "running": 0,
        "completed": 0,
        "failed": 0,
        "cancelled": 0,
        "timeout": 0,
    }
    for status, n in rows:
        sv = status.value if isinstance(status, TaskStatus) else str(status)
        key = {
            TaskStatus.PENDING.value: "pending",
            TaskStatus.RUNNING.value: "running",
            TaskStatus.COMPLETED.value: "completed",
            TaskStatus.FAILED.value: "failed",
            TaskStatus.CANCELED.value: "cancelled",
        }.get(sv)
        if key is not None:
            counts[key] = int(n)
    counts["total"] = sum(counts.values())
    return counts


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
    responses=QUEUE_STATS_RESPONSES,
)
async def get_queue_stats(
    user: Annotated[dict, Depends(PermissionChecker(Permission.VIEW_ANALYTICS))],
    db: Session = Depends(get_db),
):
    """
    Retrieve task statistics from persisted tasks.

    Returns:
        dict: Counts by status and total.
    """
    stats = get_task_queue_stats(db)
    logger.info("Queue statistics retrieved", stats=stats)
    return stats


def _task_status_value(status) -> str:
    v = status.value if hasattr(status, "value") else str(status)
    if v == "canceled":
        return "cancelled"
    return v


@router.get(
    "/{task_id}",
    summary="Get task details",
    description="Returns a task, optional result, and child subtasks. Requires TASK_READ.",
    status_code=200,
    dependencies=[Depends(PermissionChecker(Permission.TASK_READ))],
)
def get_task_detail(task_id: str, db: Session = Depends(get_db)):
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    tr = db.query(TaskResult).filter(TaskResult.task_id == task_id).first()
    children = (
        db.query(Task)
        .filter(Task.parent_task_id == task_id)
        .order_by(Task.created_at.asc())
        .all()
    )

    result_str = None
    if tr and tr.result_data is not None:
        if isinstance(tr.result_data, str):
            result_str = tr.result_data
        else:
            result_str = json.dumps(tr.result_data)

    subtasks_out = [
        {
            "id": c.id,
            "title": (c.query[:200] + "…") if len(c.query) > 200 else c.query,
            "status": _task_status_value(c.status),
            "assignedAgent": c.agent_id,
        }
        for c in children
    ]

    return {
        "task_id": task.id,
        "status": _task_status_value(task.status),
        "agent_id": task.agent_id,
        "conversation_id": task.conversation_id,
        "query": task.query,
        "created_at": task.created_at.isoformat() if task.created_at else "",
        "result": result_str,
        "history": tr.history if tr else [],
        "future_actions": tr.future_actions if tr else [],
        "subtasks": subtasks_out,
    }


@router.post("/new_task", include_in_schema=False)
@router.post(
    "/new_task/",
    summary="Create and dispatch a new task",
    description="Attribute a task to the best agent based on the skills required. Publishes the request to the RabbitMQ queue and returns confirmation with task and conversation IDs. Requires TASK_CREATE permission.",
    status_code=200,
    tags=["Tasks"],
    dependencies=[Depends(PermissionChecker(Permission.TASK_CREATE))],
    responses=CREATE_TASK_RESPONSES,
    openapi_extra=CREATE_TASK_OPENAPI_EXTRA,
)
async def create_new_task(
    task: TaskForm,
    user: Annotated[dict, Depends(PermissionChecker(Permission.TASK_CREATE))],
    db: Session = Depends(get_db),
):
    """Create and dispatch a new task.

    Selects an agent for ``task.demand``, either returns a direct answer or
    creates a ``Task`` row and publishes to RabbitMQ.

    Raises:
        HTTPException: 401 if unauthenticated, 500 on DB/messaging failure.
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
        # Push to chat WebSocket clients (same as agent task-result path); otherwise UI stays "loading".
        await send_messages_via_websockets(str(task.conversation_id), direct_response)
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
                # Agent consumer expects "demand" (or "query"); omitting it left the worker idle / empty.
                "demand": user_demand,
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
        fallback = "No agent registered to assign a task"
        add_messages("assistant", fallback, task.conversation_id, db)
        await send_messages_via_websockets(str(task.conversation_id), fallback)
        return {"message": fallback}

    agent_id, user_demand = first_action

    history = [{"role": "user", "message": task.demand}]

    task_id = insert_new_task(
        task.conversation_id, agent_id, user_demand, history, actions_list, db
    )
    message = json.dumps(
        {
            "conversation_id": task.conversation_id,
            "task_id": task_id,
            "demand": user_demand,
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
    responses=SHARE_RESULT_RESPONSES,
    openapi_extra=SHARE_RESULT_OPENAPI_EXTRA,
)
async def sharing_agent_result(
    task_result: TaskResultForm,
    verified_agent: Annotated[tuple[str, str], Depends(verify_agent_api_key)],
    db: Session = Depends(get_db),
):
    """Ingest an agent's task result.

    Verifies the agent, updates task status to COMPLETED, stores the result,
    chains any follow-up actions, and notifies the UI over WebSocket.

    Args:
        task_result: Result payload (output, status, suggestions).
        verified_agent: Authenticated agent ``(id, api_key)``.
        db: Active database session.

    Raises:
        HTTPException: 403 on id mismatch, 404 if task missing, 500 on
            internal failure (e.g. recursion guard).
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
                    "demand": new_action_context,
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
    "/{task_id}/cancel",
    summary="Cancel a running task (alternate path)",
    description="Same as /task-cancel/{task_id}; provided for API client compatibility.",
    status_code=200,
    tags=["Tasks"],
    dependencies=[Depends(PermissionChecker(Permission.TASK_DELETE))],
    include_in_schema=False,
)
@router.patch(
    "/task-cancel/{task_id}",
    summary="Cancel a running task",
    description="Interrupts a running task by updating its status to CANCELED and sending a high-priority cancellation signal to the assigned agent via RabbitMQ. Requires TASK_DELETE permission.",
    status_code=200,
    tags=["Tasks"],
    dependencies=[Depends(PermissionChecker(Permission.TASK_DELETE))],
    responses=CANCEL_TASK_RESPONSES,
)
async def cancel_task(
    task_id: str,
    user: Annotated[dict, Depends(PermissionChecker(Permission.TASK_DELETE))],
    db: Session = Depends(get_db),
):
    """Cancel an active task and interrupt its executing agent.

    Marks ``task_id`` CANCELLED, publishes a high-priority interrupt to the
    assigned agent, and writes an audit log entry.

    Raises:
        HTTPException: 401 unauthenticated, 404 task missing, 500 on failure.
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
