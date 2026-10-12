from enum import Enum


class TaskStatus(str, Enum):
    QUEUED = "queued"
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    CANCELED = "canceled"
    FAILED = "failed"


FINAL_STATUSES = frozenset(
    {TaskStatus.COMPLETED.value, TaskStatus.CANCELED.value, TaskStatus.FAILED.value}
)

IN_PROGRESS_STATUSES = frozenset(
    {TaskStatus.QUEUED.value, TaskStatus.PENDING.value, TaskStatus.RUNNING.value}
)


def is_final_status(status) -> bool:
    return getattr(status, "value", status) in FINAL_STATUSES
