import asyncio
import datetime
import time

from fastapi import HTTPException
from starlette.concurrency import run_in_threadpool

from chat.chat_tool_functions import connected_conversation_ids
from core.config import settings
from core.logger import get_logger
from core.task_events import (
    TaskEventType,
    TaskStage,
    current_task_stage,
    publish_agent_message,
    publish_heartbeat,
)
from db.database import SessionLocal
from db.models import Task
from tasks.status import IN_PROGRESS_STATUSES, TaskStatus
from tasks.task_tool_functions import get_tasks_in_progress, interrupt_task

logger = get_logger("task_controller")

HEARTBEAT_INTERVAL_S = 5.0

INTERRUPTED_ROUTING_TEXT = (
    "The orchestrator restarted before this request reached an agent, so it was "
    "not processed. Please send it again."
)


def _task_runtime_seconds(task, now: datetime.datetime) -> float:
    """Wall time since the task row was created (RUNNING tasks rarely get DB updates during LLM work)."""
    start = task.created_at
    if start is None:
        return 0.0
    if start.tzinfo is None:
        start = start.replace(tzinfo=datetime.UTC)
    return max(0.0, (now - start).total_seconds())


def _utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


def _timeout_notice(limit_s: int) -> str:
    return (
        f"This request exceeded the maximum processing time ({limit_s}s) and was stopped. "
        "Try a shorter or simpler question, or ask an administrator to raise TASK_TIMEOUT "
        "for long-running models."
    )


async def _report_timeout(task, user_text: str, db) -> None:
    if task.result is not None and not task.result.result_data:
        task.result.result_data = user_text
        db.commit()
    await publish_agent_message(
        task.id,
        task.conversation_id,
        user_text,
        event_type=TaskEventType.ERROR,
        status="cancelled",
        reason="timeout",
    )


async def check_task_timeout(test_mode=False):
    """Cancel RUNNING tasks that exceed TASK_TIMEOUT (wall-clock since task creation)."""
    logger.info("Starting task runtime (TASK_TIMEOUT) monitoring...")

    while True:
        try:
            db = SessionLocal()
            try:
                current_time = datetime.datetime.now(datetime.UTC)
                limit_s = settings.task_timeout
                tasks_in_progress = get_tasks_in_progress(db)

                if not tasks_in_progress:
                    logger.debug("No tasks in progress for timeout monitoring")
                    await asyncio.sleep(2)
                    continue

                for task in tasks_in_progress:
                    elapsed = _task_runtime_seconds(task, current_time)
                    if elapsed <= limit_s:
                        continue

                    logger.warning(
                        "Task %s exceeded TASK_TIMEOUT (running %.0fs > %ss); cancelling.",
                        task.id,
                        elapsed,
                        limit_s,
                    )
                    try:
                        interrupt_task(
                            task.id,
                            db,
                            reason=f"Exceeded maximum runtime ({limit_s}s, TASK_TIMEOUT)",
                        )
                    except HTTPException as exc:
                        logger.info(
                            "Timeout cancel skipped for task %s: %s",
                            task.id,
                            exc.detail,
                        )
                        continue

                    if task.parent_task_id is not None:
                        continue
                    try:
                        await _report_timeout(task, _timeout_notice(limit_s), db)
                    except Exception:
                        logger.exception(
                            "Failed to report the timeout of task %s", task.id
                        )

                await asyncio.sleep(5 if not test_mode else 1)
            finally:
                db.close()
        except Exception as e:
            logger.error(f"Error during task heartbeat monitoring: {str(e)}")
            await asyncio.sleep(5)


def _default_stage(task) -> str:
    if getattr(task.status, "value", task.status) == TaskStatus.QUEUED.value:
        return TaskStage.QUEUED.value
    return TaskStage.GENERATION.value


async def emit_task_heartbeats(db, now: datetime.datetime) -> int:
    conversation_ids = [
        int(conv_id) for conv_id in connected_conversation_ids() if conv_id.isdigit()
    ]
    if not conversation_ids:
        return 0
    running = (
        db.query(Task)
        .filter(
            Task.parent_task_id.is_(None),
            Task.status.in_(sorted(IN_PROGRESS_STATUSES)),
            Task.conversation_id.in_(conversation_ids),
        )
        .all()
    )
    for task in running:
        stage = await run_in_threadpool(current_task_stage, task.id)
        await publish_heartbeat(
            task.id,
            task.conversation_id,
            stage=stage or _default_stage(task),
            elapsed_s=round(_task_runtime_seconds(task, now), 1),
        )
    return len(running)


async def run_task_heartbeats(
    *,
    interval_s: float = HEARTBEAT_INTERVAL_S,
    session_factory=SessionLocal,
    clock=time.monotonic,
    now=_utc_now,
    sleep=asyncio.sleep,
):
    logger.info("Starting task heartbeats every %ss", interval_s)
    deadline = clock() + interval_s
    while True:
        await sleep(max(0.0, deadline - clock()))
        db = session_factory()
        try:
            await emit_task_heartbeats(db, now())
        except Exception:
            logger.warning("Task heartbeat round failed", exc_info=True)
        finally:
            db.close()
        deadline = max(deadline + interval_s, clock())


async def fail_interrupted_routing(session_factory=SessionLocal) -> int:
    db = session_factory()
    try:
        stranded = db.query(Task).filter(Task.status == TaskStatus.QUEUED.value).all()
        for task in stranded:
            task.status = TaskStatus.FAILED.value
            if task.result is not None:
                task.result.result_data = INTERRUPTED_ROUTING_TEXT
        db.commit()
        for task in stranded:
            if task.parent_task_id is not None:
                continue
            await publish_agent_message(
                task.id,
                task.conversation_id,
                INTERRUPTED_ROUTING_TEXT,
                event_type=TaskEventType.ERROR,
                status=TaskStatus.FAILED.value,
                route="none",
            )
        if stranded:
            logger.warning(
                "Marked %s task(s) failed: MAS restarted before they were routed",
                len(stranded),
            )
        return len(stranded)
    except Exception:
        logger.warning("Could not fail the tasks stranded in the queue", exc_info=True)
        db.rollback()
        return 0
    finally:
        db.close()
