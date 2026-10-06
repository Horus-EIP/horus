"""DB-bound task lifecycle helpers: create, validate, cancel, list."""

import asyncio
import json
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy.orm import Session

from core.logger import get_logger
from core.rabbitmq_tool import rabbitmq_instance
from db.models import Task, TaskResult
from tasks.demo_log import pretty_log
from tasks.status import TaskStatus

logger = get_logger("task_tool_functions")


def insert_new_task(
    conversation_id: int | None,
    agent_id: str,
    query: str,
    history: list,
    future_actions: list,
    db: Session,
    skills_required: list[str] | None = None,
):
    """Create a running ``Task`` + its ``TaskResult`` shell and return the task id."""
    pretty_log(f"SCHEDULING NEW TASK FOR AGENT {agent_id}", "📅")
    new_task_id = str(uuid4())
    task_result_id = str(uuid4())
    try:
        task = Task(
            id=new_task_id,
            conversation_id=conversation_id,
            agent_id=agent_id,
            status=TaskStatus.RUNNING,
            query=query,
            parent_task_id=None,
            order=0,
            skills_required=list(skills_required or []),
        )
        db.add(task)
        db.commit()

        task_result = TaskResult(
            id=task_result_id,
            task_id=new_task_id,
            result_data=None,
            history=history,
            future_actions=future_actions,
        )
        db.add(task_result)
        db.commit()
        return new_task_id
    except Exception as e:
        db.rollback()
        logger.error(
            f"Failed to create agent task - Task ID: {new_task_id}, Error: {str(e)}"
        )
        return None


def insert_queued_task(
    task_id: str,
    conversation_id: int | None,
    agent_id: str,
    query: str,
    owner_username: str | None,
    db: Session,
    skills_required: list[str] | None = None,
) -> Task:
    task = Task(
        id=task_id,
        conversation_id=conversation_id,
        agent_id=agent_id,
        status=TaskStatus.QUEUED,
        query=query,
        parent_task_id=None,
        order=0,
        skills_required=list(skills_required or []),
        owner_username=owner_username,
    )
    try:
        db.add(task)
        db.add(
            TaskResult(
                id=str(uuid4()),
                task_id=task_id,
                result_data=None,
                history=[{"role": "user", "message": query}],
                future_actions=[],
            )
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    return task


def record_skill_used(task: Task, skill_used: str | None) -> None:
    known_skills = list(task.skills_required or [])
    if skill_used and skill_used not in known_skills:
        task.skills_required = [*known_skills, skill_used]


def validating_task_results(
    task_id: str, task_result: str, db: Session, skill_used: str | None = None
):
    """Mark a task completed and persist its result + updated history."""
    pretty_log(f"VALIDATING RESULTS FOR TASK {task_id}", "📥")
    try:
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        current_task_result = task.result
        if not current_task_result:
            raise HTTPException(status_code=404, detail="TaskResult not found")
        history = current_task_result.history or []
        history.append({"role": "assistant", "message": task_result})
        task.status = TaskStatus.COMPLETED
        record_skill_used(task, skill_used)
        current_task_result.result_data = task_result
        current_task_result.history = history
        db.commit()
        pretty_log(f"TASK {task_id} COMPLETED SUCCESSFULLY. RESULT SAVED.", "✅")
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(
            f"Failed to validate task results - Task ID: {task_id}, Error: {str(e)}"
        )
        raise HTTPException(
            status_code=500, detail=f"Error validating task results: {str(e)}"
        )


async def interrupt_task(task_id: str, db: Session, reason: str | None = None):
    """Cancel an in-flight task and notify its agent via RabbitMQ."""
    pretty_log(f"INTERRUPT SIGNAL RECEIVED FOR TASK {task_id}", "🛑")
    cancel_reason = reason or "User requested cancellation"
    try:
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        if task.status in [
            TaskStatus.COMPLETED.value,
            TaskStatus.FAILED.value,
            TaskStatus.CANCELED.value,
        ]:
            raise HTTPException(
                status_code=400, detail="Cannot interrupt a completed task"
            )
        task.status = TaskStatus.CANCELED
        db.commit()
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to cancel task - Task ID: {task_id}, Error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error Canceling task: {str(e)}")

    cancellation_message = json.dumps(
        {
            "type": "cancel",
            "task_id": task_id,
            "conversation_id": task.conversation_id,
            "reason": cancel_reason,
        }
    )
    await asyncio.to_thread(
        rabbitmq_instance.publish,
        queue_name=task.agent_id,
        message=cancellation_message,
        priority_value=10,
    )
    logger.info(f"Cancellation signal sent for task {task_id} to agent {task.agent_id}")
    return True


def _get_all_tasks_internal(
    db: Session,
    status_filter: TaskStatus = None,
    status_in: list[TaskStatus] | None = None,
):
    """Return every task, optionally filtered by status."""
    try:
        query = db.query(Task)
        if status_filter:
            query = query.filter(Task.status == status_filter)
        if status_in:
            query = query.filter(Task.status.in_(status_in))
        tasks = query.all()
        return tasks
    except Exception as e:
        logger.error(f"Failed to retrieve tasks - Error: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error retrieving tasks: {str(e)}")


def get_tasks_in_progress(db: Session):
    """Return tasks that are still queued or running."""
    try:
        tasks_in_progress = _get_all_tasks_internal(
            db, status_in=[TaskStatus.QUEUED, TaskStatus.RUNNING]
        )
        return tasks_in_progress
    except Exception as e:
        logger.error(f"Failed to retrieve tasks in progress - Error: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Error retrieving tasks in progress: {str(e)}"
        )
