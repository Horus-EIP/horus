import asyncio
import json
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from chat.chat_tool_functions import (agent_message_payload,
                                      broadcast_to_conversation,
                                      task_step_payload)
from core.logger import get_logger
from db.redis_client import redis_db
from starlette.concurrency import run_in_threadpool

logger = get_logger("task_events")

TASK_EVENTS_TTL_SECONDS = 24 * 60 * 60
TASK_SEQ_TTL_SECONDS = TASK_EVENTS_TTL_SECONDS + 60 * 60
TASK_EVENTS_MAX_LEN = 10_000


class TaskEventType(str, Enum):
    PROGRESS = "progress"
    TOKEN = "token"
    HEARTBEAT = "heartbeat"
    RESULT = "result"
    ERROR = "error"


class TaskStage(str, Enum):
    QUEUED = "queued"
    ROUTING = "routing"
    RETRIEVAL = "retrieval"
    GENERATION = "generation"
    AGGREGATION = "aggregation"


TERMINAL_EVENT_TYPES = frozenset({TaskEventType.RESULT, TaskEventType.ERROR})

TOKEN_STEP_TYPE = "reasoning.delta"

_STAGE_BY_STEP_FAMILY = {
    "retrieval": TaskStage.RETRIEVAL,
    "reasoning": TaskStage.GENERATION,
    "tool": TaskStage.GENERATION,
}

_publish_locks: dict[str, asyncio.Lock] = {}


def task_events_key(task_id: str) -> str:
    return f"horus:task:{task_id}:events"


def task_seq_key(task_id: str) -> str:
    return f"horus:task:{task_id}:seq"


def task_stage_key(task_id: str) -> str:
    return f"horus:task:{task_id}:stage"


def utc_timestamp(moment: datetime | None = None) -> str:
    return (moment or datetime.now(UTC)).strftime("%Y-%m-%dT%H:%M:%SZ")


def stage_for_step(step_type: str | None) -> TaskStage | None:
    family = (step_type or "").split(".", 1)[0]
    return _STAGE_BY_STEP_FAMILY.get(family)


def task_frame(event: dict) -> dict:
    return {
        **event["data"],
        "task_id": event["task_id"],
        "seq": event["seq"],
        "event": event["type"],
        "stage": event["stage"],
        "ts": event["ts"],
    }


def _store_event(task_id: str, event: dict) -> dict:
    seq = int(redis_db.incr(task_seq_key(task_id)))
    stored = {**event, "seq": seq}
    pipe = redis_db.pipeline()
    pipe.expire(task_seq_key(task_id), TASK_SEQ_TTL_SECONDS)
    pipe.xadd(
        task_events_key(task_id),
        {"event": json.dumps(stored, default=str)},
        id=f"{seq}-0",
        maxlen=TASK_EVENTS_MAX_LEN,
        approximate=True,
    )
    pipe.expire(task_events_key(task_id), TASK_EVENTS_TTL_SECONDS)
    if stored["stage"]:
        pipe.set(task_stage_key(task_id), stored["stage"], ex=TASK_EVENTS_TTL_SECONDS)
    pipe.execute()
    return stored


def read_task_events(task_id: str, since: int = 0, limit: int = 1000) -> list[dict]:
    entries = redis_db.xrange(
        task_events_key(task_id), min=f"{since + 1}-0", max="+", count=limit
    )
    return [json.loads(fields["event"]) for _entry_id, fields in entries]


def current_task_stage(task_id: str) -> str | None:
    try:
        return redis_db.get(task_stage_key(task_id))
    except Exception:
        logger.warning("Could not read the stage of task %s", task_id, exc_info=True)
        return None


async def publish_task_event(
    task_id: str,
    event_type: TaskEventType | str,
    *,
    conversation_id: int | str | None,
    data: dict[str, Any],
    stage: TaskStage | str | None = None,
) -> dict:
    kind = TaskEventType(event_type)
    event = {
        "task_id": task_id,
        "seq": None,
        "type": kind.value,
        "stage": TaskStage(stage).value if stage else None,
        "data": data,
        "ts": utc_timestamp(),
    }
    lock = _publish_locks.setdefault(task_id, asyncio.Lock())
    async with lock:
        try:
            event = await run_in_threadpool(_store_event, task_id, event)
        except Exception:
            logger.warning(
                "Task event store unavailable; %s event of task %s is sent live only",
                kind.value,
                task_id,
                exc_info=True,
            )
        if conversation_id is not None:
            await broadcast_to_conversation(str(conversation_id), task_frame(event))
    if kind in TERMINAL_EVENT_TYPES:
        _publish_locks.pop(task_id, None)
    return event


async def publish_agent_message(
    task_id: str,
    conversation_id: int | str | None,
    content: str,
    *,
    event_type: TaskEventType | str = TaskEventType.PROGRESS,
    stage: TaskStage | str | None = None,
    agent_id: str | None = None,
    agent_name: str | None = None,
    skill_used: str | None = None,
    **fields: Any,
) -> dict:
    data = {
        **agent_message_payload(
            content, agent_id=agent_id, agent_name=agent_name, skill_used=skill_used
        ),
        **fields,
    }
    return await publish_task_event(
        task_id, event_type, conversation_id=conversation_id, data=data, stage=stage
    )


async def publish_task_step(
    task_id: str, conversation_id: int | str | None, step: dict
) -> dict:
    data = task_step_payload({**step, "task_id": task_id})
    event_type = (
        TaskEventType.TOKEN
        if data["step_type"] == TOKEN_STEP_TYPE
        else TaskEventType.PROGRESS
    )
    return await publish_task_event(
        task_id,
        event_type,
        conversation_id=conversation_id,
        data=data,
        stage=stage_for_step(data["step_type"]),
    )


async def publish_task_status(
    task_id: str,
    conversation_id: int | str | None,
    status: str,
    *,
    stage: TaskStage | str | None,
    detail: str | None = None,
    **fields: Any,
) -> dict:
    data: dict[str, Any] = {"type": "task_status", "status": status, **fields}
    if detail:
        data["detail"] = detail
    return await publish_task_event(
        task_id,
        TaskEventType.PROGRESS,
        conversation_id=conversation_id,
        data=data,
        stage=stage,
    )


async def publish_heartbeat(
    task_id: str,
    conversation_id: int | str | None,
    *,
    stage: TaskStage | str,
    elapsed_s: float,
) -> dict:
    return await publish_task_event(
        task_id,
        TaskEventType.HEARTBEAT,
        conversation_id=conversation_id,
        data={"type": "heartbeat", "elapsed_s": elapsed_s},
        stage=stage,
    )
