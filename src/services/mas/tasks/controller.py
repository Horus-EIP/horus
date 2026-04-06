import asyncio
import datetime
from datetime import timezone

from core.config import settings
from core.logger import get_logger
from db.database import SessionLocal
from tasks.task_tool_functions import get_tasks_in_progress, interrupt_task

logger = get_logger("task_controller")


async def check_task_timeout(test_mode=False):
    """Monitor agent heartbeats and update their status"""
    logger.info("Starting agent heartbeat monitoring...")

    while True:
        try:
            db = SessionLocal()
            try:
                current_time = datetime.datetime.now(timezone.utc)
                inactivity_period = settings.task_timeout
                tasks_in_progress = get_tasks_in_progress(db)

                if not tasks_in_progress:
                    logger.debug("No tasks in progress for heartbeat monitoring")
                    await asyncio.sleep(2)
                    continue

                for task in tasks_in_progress:
                    if task.updated_at is None:
                        time_since_last_update = float("inf")
                    else:
                        time_since_last_update = (
                            current_time - task.updated_at
                        ).total_seconds()

                    if time_since_last_update > inactivity_period:
                        logger.warning(
                            f"Task {task.id} has been inactive for {time_since_last_update} seconds. Interrupting task."
                        )
                        interrupt_task(task.id, db)

                await asyncio.sleep(5 if not test_mode else 1)
            finally:
                db.close()
        except Exception as e:
            logger.error(f"Error during task heartbeat monitoring: {str(e)}")
            await asyncio.sleep(5)
