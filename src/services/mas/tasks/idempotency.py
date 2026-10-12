from core.logger import get_logger
from db.redis_client import redis_db

logger = get_logger("task_idempotency")

IDEMPOTENCY_TTL_SECONDS = 24 * 60 * 60
IDEMPOTENCY_KEY_MAX_LENGTH = 200


def idempotency_record_key(user_id: int | str, key: str) -> str:
    return f"horus:idempotency:{user_id}:{key}"


def claim_task_id(user_id: int | str, key: str, task_id: str) -> str:
    record = idempotency_record_key(user_id, key)
    try:
        for _attempt in range(2):
            if redis_db.set(record, task_id, nx=True, ex=IDEMPOTENCY_TTL_SECONDS):
                return task_id
            existing = redis_db.get(record)
            if existing:
                return existing
    except Exception:
        logger.warning(
            "Idempotency store unavailable; accepting the task without a replay guard",
            exc_info=True,
        )
    return task_id


def release_task_id(user_id: int | str, key: str, task_id: str) -> None:
    record = idempotency_record_key(user_id, key)
    try:
        if redis_db.get(record) == task_id:
            redis_db.delete(record)
    except Exception:
        logger.warning("Could not release idempotency key %s", record, exc_info=True)
