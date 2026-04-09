import asyncio
import datetime
from datetime import timezone

from fastapi import HTTPException

from chat.chat_tool_functions import send_messages_via_websockets
from core.config import settings
from core.logger import get_logger
from db.database import SessionLocal
from tasks.task_tool_functions import get_tasks_in_progress, interrupt_task

logger = get_logger("task_controller")


def _task_runtime_seconds(task, now: datetime.datetime) -> float:
    """Wall time since the task row was created (RUNNING tasks rarely get DB updates during LLM work)."""
    start = task.created_at
    if start is None:
        return 0.0
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    return max(0.0, (now - start).total_seconds())


async def check_task_timeout(test_mode=False):
    """Cancel RUNNING tasks that exceed TASK_TIMEOUT (wall-clock since task creation)."""
    logger.info("Starting task runtime (TASK_TIMEOUT) monitoring...")

    while True:
        try:
            db = SessionLocal()
            try:
                current_time = datetime.datetime.now(timezone.utc)
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

                    conv_id = str(task.conversation_id)
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

                    user_text = (
                        f"This request exceeded the maximum processing time ({limit_s}s) and was stopped. "
                        "Try a shorter or simpler question, or ask an administrator to raise TASK_TIMEOUT "
                        "for long-running models."
                    )
                    try:
                        await send_messages_via_websockets(conv_id, user_text)
                    except Exception:
                        logger.exception(
                            "Failed to push timeout notice to WebSocket for conversation %s",
                            conv_id,
                        )

                await asyncio.sleep(5 if not test_mode else 1)
            finally:
                db.close()
        except Exception as e:
            logger.error(f"Error during task heartbeat monitoring: {str(e)}")
            await asyncio.sleep(5)
