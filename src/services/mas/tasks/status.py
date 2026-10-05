from enum import Enum


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    CANCELED = "canceled"
    FAILED = "failed"


FINAL_STATUSES = frozenset(
    {TaskStatus.COMPLETED.value, TaskStatus.CANCELED.value, TaskStatus.FAILED.value}
)


def is_final_status(status) -> bool:
    return getattr(status, "value", status) in FINAL_STATUSES
