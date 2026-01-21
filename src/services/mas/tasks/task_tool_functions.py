"""
Task Tool Functions - Task Management and Orchestration Logic

This module provides core functionality for task lifecycle management:
- Task creation and assignment
- Task cancellation and timeout handling
- Agent selection via LLM-based routing
- Task result validation

Task Status Flow:
    pending -> running -> completed
                      -> failed
                      -> cancelled (via cancellation)
                      -> timeout (via timeout check)
"""

import json
import os
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import List, Optional, Tuple
from uuid import uuid4

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from agents.registry_tool_functions import get_agent_id, get_available_agents
from core.llm_setup import ask_llm
from core.logger import get_logger
from core.rabbitmq_tool import rabbitmq_instance
from core.structured_logging import get_structured_logger, log_task_event
from db.database import SessionLocal, get_db
from db.models import Task, TaskResult

logger = get_logger("task_tool_functions")
structured_logger = get_structured_logger("task")


class TaskStatus(str, Enum):
    """Task status enumeration."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"


# Task timeout configuration (in seconds)
TASK_TIMEOUT_SECONDS = int(os.getenv("TASK_TIMEOUT_SECONDS", "300"))  # 5 minutes default


def get_prompt(user_input, suitable_agents):

    response_format = """{
      "next_action": "respond_to_user" | "run_agents",
      "actions": [
        {"agent": "<agent_name>", "input": "<rewritten_input_for_that_agent>"}
      ],
      "final_answer": "<string | empty when run_agents>"
    }"""

    agents_block = "\n".join(f"- {name}: {desc}" for _, name, desc in suitable_agents)
    schema_literal = response_format.replace("{", "{{").replace("}", "}}")

    messages = [
        {
            "role": "system",
            "content": "You are an expert intent router. Read USER INPUT. Either: "
            " - select one or more AGENTS with rewritten inputs, or"
            "- conclude and respond to the user.",
        },
        {
            "role": "user",
            "content": f"""        AVAILABLE AGENTS (name: description):
    {agents_block}

    USER INPUT:
    {user_input}

    OUTPUT RULES (CRITICAL):
    - Return ONLY a valid JSON object matching exactly this schema:


    {schema_literal}


    - If you need to call any agent(s), set "next_action": "run_agents" and fill "actions" with 1..N items.
    - If no action is needed, set "next_action": "respond_to_user", put the reply in "final_answer", and make "actions" an empty list.
    - No text outside the JSON. No code fences, no explanations.
    - If you can't execute the user demand with agents available , set "next_action": "respond_to_user" and put an explanation in "final_answer", and make "actions" an empty list.

    Consistency constraints:
    - When "next_action" = "run_agents": "final_answer" MUST be an empty string.
    - When "next_action" = "respond_to_user": "actions" MUST be an empty list."
        """,
        },
    ]

    return messages


def build_action_list(actions_dict, agents_available, db: Session = None):
    action_list = []

    if db is None:
        db = SessionLocal()

    for dict in actions_dict:
        agent_id = ""
        question = ""
        for key, value in dict.items():

            if key == "agent":
                if value == "":
                    raise ValueError(
                        f"Agent name to attribute agent tasks must not be empty"
                    )
                agent_id = get_agent_id(value, db)
                if agent_id is None:
                    raise ValueError(
                        f"Agent mentionned by orchestrator doesn't exists: {value}"
                    )

            elif key == "input":
                if value == "":
                    raise ValueError(f"Input for the agents task must not be empty")
                question = value

        action_list.append((agent_id, question))

        rabbitmq_instance.create_queue(agent_id)
    return action_list


def clean_json_output(json_input):
    output = json_input.strip()
    if output.startswith("```"):
        output = output.strip("`")
        if "\n" in output:
            output = output.split("\n", 1)[1]
        output = output.strip()
    return output


def select_agent_for_task(user_input: str, db: Session = None):
    if db is None:
        from db.database import SessionLocal

        db = SessionLocal()

    available_agents = get_available_agents(db)

    if not available_agents:
        return None, None, None, []

    prompt = get_prompt(user_input, available_agents)
    # Convert available_agents to list of dicts for ask_llm mock
    agents_for_llm = [{"name": name, "description": desc} for _, name, desc in available_agents]
    output = ask_llm(prompt, available_agents=agents_for_llm)

    output = clean_json_output(output)

    json_output = json.loads(output)

    if json_output["next_action"] not in ("respond_to_user", "run_agents"):
        raise ValueError("next_action must be 'respond_to_user' or 'run_agents'.")

    if json_output["next_action"] == "respond_to_user":
        return None, None, f"Response for user : {json_output["final_answer"]}", []
    action_key = json_output["actions"]
    if not action_key:
        raise ValueError("No actions provided for run_agents")

    action_list = build_action_list(action_key, available_agents, db)

    first_agent_to_use = action_list[0][0]
    first_action_to_do = action_list[0][1]

    action_list.pop(0)

    return first_agent_to_use, first_action_to_do, None, action_list


def insert_new_task(
    conversation_id: int,
    agent_id: str,
    query: str,
    history: list,
    future_actions: list,
    db: Session,
):
    new_task_id = str(uuid4())
    task_result_id = str(uuid4())
    try:
        task = Task(
            id=new_task_id,
            conversation_id=conversation_id,
            agent_id=agent_id,
            status="running",
            query=query,
            parent_task_id=None,
            order=0,
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


def validating_task_results(task_id: str, task_result: str, db: Session):
    try:
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        current_task_result = task.result
        if not current_task_result:
            raise HTTPException(status_code=404, detail="TaskResult not found")
        history = current_task_result.history or []
        history.append({"role": "assistant", "message": task_result})
        task.status = "completed"
        current_task_result.result_data = task_result
        current_task_result.history = history
        db.commit()
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


# =============================================================================
# Task Cancellation Functions
# =============================================================================

def cancel_task(task_id: str, reason: str, db: Session) -> dict:
    """
    Cancel a task and optionally notify the assigned agent.
    
    Args:
        task_id: ID of the task to cancel
        reason: Reason for cancellation
        db: Database session
    
    Returns:
        Dictionary with cancellation result
    
    Raises:
        HTTPException: If task not found or already completed
    """
    try:
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        
        # Check if task can be cancelled
        if task.status in [TaskStatus.COMPLETED.value, TaskStatus.CANCELLED.value]:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot cancel task with status: {task.status}"
            )
        
        previous_status = task.status
        task.status = TaskStatus.CANCELLED.value
        
        # Update task result if exists
        if task.result:
            task.result.result_data = {
                "cancelled": True,
                "reason": reason,
                "previous_status": previous_status,
            }
        
        db.commit()
        
        # Log the cancellation
        log_task_event(
            task_id=task_id,
            event="cancelled",
            agent_id=task.agent_id,
            conversation_id=task.conversation_id,
            reason=reason,
            previous_status=previous_status,
        )
        
        # Send cancellation message to agent via RabbitMQ
        try:
            cancellation_message = json.dumps({
                "type": "cancel",
                "task_id": task_id,
                "reason": reason,
            })
            rabbitmq_instance.publish(task.agent_id, cancellation_message)
            logger.info(f"Cancellation signal sent to agent {task.agent_id} for task {task_id}")
        except Exception as e:
            logger.warning(f"Failed to send cancellation signal to agent: {e}")
        
        return {
            "task_id": task_id,
            "status": TaskStatus.CANCELLED.value,
            "previous_status": previous_status,
            "reason": reason,
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to cancel task {task_id}: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Error cancelling task: {str(e)}"
        )


def get_task_status(task_id: str, db: Session) -> dict:
    """
    Get detailed status information for a task.
    
    Args:
        task_id: ID of the task
        db: Database session
    
    Returns:
        Dictionary with task status details
    """
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    result_data = None
    if task.result:
        result_data = task.result.result_data
    
    return {
        "task_id": task.id,
        "status": task.status,
        "agent_id": task.agent_id,
        "conversation_id": task.conversation_id,
        "query": task.query,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "result": result_data,
        "parent_task_id": task.parent_task_id,
        "order": task.order,
    }


def check_task_timeout(task_id: str, db: Session, timeout_seconds: int = None) -> bool:
    """
    Check if a task has timed out and update its status if so.
    
    Args:
        task_id: ID of the task to check
        db: Database session
        timeout_seconds: Optional custom timeout (uses TASK_TIMEOUT_SECONDS by default)
    
    Returns:
        True if task timed out, False otherwise
    """
    timeout = timeout_seconds or TASK_TIMEOUT_SECONDS
    
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        return False
    
    # Only check running tasks
    if task.status != TaskStatus.RUNNING.value:
        return False
    
    # Check if task has exceeded timeout
    if task.created_at:
        elapsed = datetime.now(timezone.utc) - task.created_at.replace(tzinfo=timezone.utc)
        if elapsed.total_seconds() > timeout:
            task.status = TaskStatus.TIMEOUT.value
            if task.result:
                task.result.result_data = {
                    "timeout": True,
                    "elapsed_seconds": elapsed.total_seconds(),
                    "timeout_threshold": timeout,
                }
            db.commit()
            
            log_task_event(
                task_id=task_id,
                event="timeout",
                agent_id=task.agent_id,
                conversation_id=task.conversation_id,
                elapsed_seconds=elapsed.total_seconds(),
            )
            
            logger.warning(f"Task {task_id} timed out after {elapsed.total_seconds():.2f}s")
            return True
    
    return False


def check_all_running_tasks_timeout(db: Session) -> List[str]:
    """
    Check all running tasks for timeout and update their status.
    
    Args:
        db: Database session
    
    Returns:
        List of task IDs that timed out
    """
    timed_out_tasks = []
    
    running_tasks = db.query(Task).filter(Task.status == TaskStatus.RUNNING.value).all()
    
    for task in running_tasks:
        if check_task_timeout(task.id, db):
            timed_out_tasks.append(task.id)
    
    if timed_out_tasks:
        logger.info(f"Marked {len(timed_out_tasks)} tasks as timed out")
    
    return timed_out_tasks


def get_task_queue_stats(db: Session) -> dict:
    """
    Get statistics about the task queue.
    
    Args:
        db: Database session
    
    Returns:
        Dictionary with queue statistics
    """
    from sqlalchemy import func
    
    stats = {}
    
    # Count tasks by status
    status_counts = db.query(
        Task.status,
        func.count(Task.id)
    ).group_by(Task.status).all()
    
    for status, count in status_counts:
        stats[status] = count
    
    # Ensure all statuses are represented
    for status in TaskStatus:
        if status.value not in stats:
            stats[status.value] = 0
    
    # Add total count
    stats["total"] = sum(stats.values())
    
    return stats
