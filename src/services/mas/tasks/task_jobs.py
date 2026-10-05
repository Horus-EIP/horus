import asyncio
from collections.abc import Coroutine
from typing import Any

from core.logger import get_logger

logger = get_logger("task_jobs")


class TaskJobs:
    def __init__(self) -> None:
        self._running: dict[str, asyncio.Task] = {}

    @property
    def running_count(self) -> int:
        return len(self._running)

    def submit(self, task_id: str, job: Coroutine[Any, Any, Any]) -> asyncio.Task:
        handle = asyncio.create_task(job, name=f"task-job-{task_id}")
        self._running[task_id] = handle
        handle.add_done_callback(lambda done: self._forget(task_id, done))
        return handle

    def _forget(self, task_id: str, handle: asyncio.Task) -> None:
        if self._running.get(task_id) is handle:
            del self._running[task_id]
        if not handle.cancelled() and handle.exception() is not None:
            logger.error(
                "Background job of task %s crashed",
                task_id,
                exc_info=handle.exception(),
            )

    async def drain(self) -> None:
        while self._running:
            await asyncio.gather(*self._running.values(), return_exceptions=True)
            await asyncio.sleep(0)

    async def shutdown(self) -> None:
        handles = list(self._running.values())
        for handle in handles:
            handle.cancel()
        await asyncio.gather(*handles, return_exceptions=True)


task_jobs = TaskJobs()
