"""HTTP routes for task orchestration.

Task creation, status queries, cancellation, and result ingestion from
agents. See ``docs/architecture.md`` for the task lifecycle,
payload shapes, and error codes.
"""

import asyncio
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import JSONResponse
from licensing.access import require_active_license
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from agents.registry_tool_functions import create_agent
from auth.auth_tool_functions import PermissionChecker, verify_agent_api_key
from auth.permissions import Permission
from conversations.conversation_tool_functions import add_messages
from core import ai_mode
from core.logger import get_logger, log_agent_operation
from core.memory_usage import peak_rss_mb
from core.metrics import TASK_ERRORS, TASK_QUEUE_DEPTH, observe_task_processing_time
from core.rabbitmq_manager import WorkQueueFull
from core.rabbitmq_tool import rabbitmq_instance
from core.skill_cache import rank_skills
from core.task_events import (
    TaskEventType,
    TaskStage,
    publish_agent_message,
    publish_task_status,
    publish_task_step,
    read_task_events,
)
from core.work_queues import agent_may_submit_task_result, resolve_work_queue_for_agent_id
from db.database import SessionLocal, get_db
from db.models import Agents, Conversations, Task, TaskResult
from db.models.agent_types import AgentTypes
from schemas.schemas import (
    TaskClaimForm,
    TaskForm,
    TaskResultForm,
    TaskResultStatus,
    TaskStepForm,
    WorkerRunForm,
)
from tasks.agent_answers import (
    NOT_IN_DOCUMENTS_TEXT,
    RETRYING_STATUS,
    merge_sources,
    recall_dispatch,
    remember_dispatch,
    retry_plan,
)
from tasks.decomposition import get_manager_agent, manager_announce_plan, manager_review_step
from tasks.idempotency import IDEMPOTENCY_KEY_MAX_LENGTH, claim_task_id, release_task_id
from tasks.openapi_docs import (
    CANCEL_TASK_RESPONSES,
    CREATE_TASK_OPENAPI_EXTRA,
    CREATE_TASK_RESPONSES,
    QUEUE_STATS_RESPONSES,
    SHARE_RESULT_OPENAPI_EXTRA,
    SHARE_RESULT_RESPONSES,
)
from tasks.router import route_task
from tasks.status import IN_PROGRESS_STATUSES, TaskStatus, is_final_status
from tasks.task_access import (
    NEW_TASK_REFUSED,
    RUNNING_TASKS_REFUSED,
    TASK_EVENTS_REFUSED,
    TASK_READ_REFUSED,
    may_add_task_to,
    may_read_conversation_tasks,
    may_read_task,
    root_tasks_visible_to,
)
from tasks.task_jobs import task_jobs
from tasks.task_tool_functions import (
    aggregate_results,
    decompose_task,
    insert_new_task,
    insert_queued_task,
    interrupt_task,
    select_agent_by_mode,
    validating_task_results,
)
from tasks.work_queue_line import BUSY_RETRY_INTERVAL_S, BUSY_STATUS, work_queue_line

logger = get_logger("task_routes")

router = APIRouter(prefix="/tasks", tags=["Tasks"], dependencies=[Depends(require_active_license)])

QUEUED_TASK_AGENT_ID = "unassigned"
ROUTE_DIRECT_ANSWER = "direct_answer"
ROUTE_AGENT = "agent"
ROUTE_NONE = "none"
TASK_EVENTS_PAGE_DEFAULT = 1000
TASK_EVENTS_PAGE_MAX = 10_000
CANCELLED_TASK_TEXT = "This request was cancelled before it finished."
AGENT_FAILED_TEXT = "The agent could not answer this request."
AGENT_RESTARTED_TEXT = (
    "The agent restarted while it was working on this request, so the request "
    "was stopped. Please send it again."
)
AGENT_RESTARTED_REASON = "agent_restarted"
AGENT_UNREGISTERED_TEXT = (
    "The agent this request was given to is no longer registered (it probably "
    "restarted), so the request was stopped before it started. Please send it again."
)
AGENT_UNREGISTERED_REASON = "agent_unregistered"


def _next_specialist_name(skills: list[str], db: Session) -> str:
    """Build a friendly, unique-ish display name from a skill set.

    First skill drives the label so the UI shows e.g. ``Specialist-Financial-Analysis``.
    If the name is already taken (rare), append a short suffix.
    """
    leaf = (skills[0] if skills else "agent").replace("_", "-").title()
    base = f"Specialist-{leaf}"
    if not db.query(Agents).filter(Agents.name == base).first():
        return base
    # Collision: append a numeric suffix so the unique constraint stays happy.
    for i in range(2, 100):
        candidate = f"{base}-{i}"
        if not db.query(Agents).filter(Agents.name == candidate).first():
            return candidate
    return f"{base}-{uuid.uuid4().hex[:6]}"


async def _publish_task_to_work_queue(
    db: Session, assigned_agent_id: str, payload: dict
) -> None:
    """Publish a task JSON payload to the shared work queue for the assignee's type."""
    queue = resolve_work_queue_for_agent_id(db, assigned_agent_id)
    if not queue:
        raise HTTPException(
            status_code=500,
            detail="Could not resolve RabbitMQ work queue for assigned agent",
        )
    payload.setdefault("assigned_agent_id", assigned_agent_id)
    await asyncio.to_thread(rabbitmq_instance.publish_task, queue, json.dumps(payload))


@dataclass(frozen=True)
class _WorkDispatch:
    agent_id: str
    payload: dict
    task_id: str
    root_id: str
    conversation_id: int | None

    @property
    def task_ids(self) -> list[str]:
        return list(dict.fromkeys([self.task_id, self.root_id]))


def _work_queue_key(db: Session, agent_id: str) -> str:
    return resolve_work_queue_for_agent_id(db, agent_id) or agent_id


def _set_waiting_status(db: Session, dispatch: _WorkDispatch, waiting: bool) -> None:
    current, target = (
        (TaskStatus.RUNNING.value, TaskStatus.QUEUED.value)
        if waiting
        else (TaskStatus.QUEUED.value, TaskStatus.RUNNING.value)
    )
    db.query(Task).filter(Task.id.in_(dispatch.task_ids), Task.status == current).update(
        {Task.status: target}, synchronize_session=False
    )
    db.commit()


def _dispatch_was_stopped(db: Session, dispatch: _WorkDispatch) -> bool:
    statuses = db.query(Task.status).filter(Task.id.in_(dispatch.task_ids)).all()
    return len(statuses) < len(dispatch.task_ids) or any(
        is_final_status(status) for (status,) in statuses
    )


def _cancel_never_dispatched(db: Session, dispatch: _WorkDispatch) -> None:
    db.query(Task).filter(
        Task.id.in_(dispatch.task_ids),
        Task.status.in_(sorted(IN_PROGRESS_STATUSES)),
    ).update(
        {Task.status: TaskStatus.CANCELED.value, Task.completed_at: datetime.now(UTC)},
        synchronize_session=False,
    )
    db.commit()


async def _report_busy(dispatch: _WorkDispatch, position: int) -> None:
    logger.info(
        "Work queue full; the task waits in line",
        task_id=dispatch.task_id,
        root_task_id=dispatch.root_id,
        position=position,
    )
    await publish_task_status(
        dispatch.root_id,
        dispatch.conversation_id,
        BUSY_STATUS,
        stage=TaskStage.QUEUED,
        detail=f"Busy, position {position}",
        position=position,
    )


async def _publish_unless_full(db: Session, dispatch: _WorkDispatch) -> bool:
    remember_dispatch(dispatch.task_id, dispatch.payload)
    queue = _work_queue_key(db, dispatch.agent_id)
    if work_queue_line.has_waiting(queue):
        depth = work_queue_line.depth(queue)
    else:
        try:
            await _publish_task_to_work_queue(db, dispatch.agent_id, dict(dispatch.payload))
            return True
        except WorkQueueFull as full:
            depth = full.depth
    work_queue_line.join(queue, dispatch.task_id, depth)
    try:
        _set_waiting_status(db, dispatch, waiting=True)
        await _report_busy(dispatch, work_queue_line.position(queue, dispatch.task_id))
    except BaseException:
        work_queue_line.leave(queue, dispatch.task_id)
        raise
    return False


def _release_db_connection(db: Session) -> None:
    db.commit()


async def _wait_for_room(db: Session, dispatch: _WorkDispatch) -> bool:
    queue = _work_queue_key(db, dispatch.agent_id)
    reported = work_queue_line.position(queue, dispatch.task_id)
    try:
        while True:
            _release_db_connection(db)
            await asyncio.sleep(BUSY_RETRY_INTERVAL_S)
            if _dispatch_was_stopped(db, dispatch):
                _cancel_never_dispatched(db, dispatch)
                logger.info("Task %s was stopped while it waited in line", dispatch.task_id)
                return False
            if work_queue_line.ahead_of(queue, dispatch.task_id) == 0:
                try:
                    await _publish_task_to_work_queue(
                        db, dispatch.agent_id, dict(dispatch.payload)
                    )
                    return True
                except WorkQueueFull as full:
                    work_queue_line.record_depth(queue, full.depth)
            position = work_queue_line.position(queue, dispatch.task_id)
            if position != reported:
                await _report_busy(dispatch, position)
                reported = position
    finally:
        work_queue_line.leave(queue, dispatch.task_id)


async def _hand_to_agents(db: Session, dispatch: _WorkDispatch) -> bool:
    handed = await _publish_unless_full(db, dispatch) or await _wait_for_room(db, dispatch)
    if handed:
        _set_waiting_status(db, dispatch, waiting=False)
    return handed


async def _wait_for_room_job(dispatch: _WorkDispatch) -> bool:
    db = SessionLocal()
    try:
        handed = await _wait_for_room(db, dispatch)
        if handed:
            _set_waiting_status(db, dispatch, waiting=False)
            await _announce_dispatch(db, dispatch)
        return handed
    except Exception as exc:
        logger.exception("Could not hand task %s to an agent", dispatch.task_id)
        db.rollback()
        task = db.query(Task).filter(Task.id == dispatch.task_id).first()
        if task is not None:
            await _fail_task_tree(
                db,
                task,
                f"The orchestrator could not hand this request to an agent: {exc}",
                reason="dispatch_failed",
            )
        return False
    finally:
        db.close()


async def _fail_task_tree(
    db: Session,
    task: Task,
    text: str,
    *,
    reason: str,
    agent_id: str | None = None,
    agent_name: str | None = None,
    skill_used: str | None = None,
) -> bool:
    root = (
        db.query(Task).filter(Task.id == task.parent_task_id).first()
        if task.parent_task_id
        else None
    )
    reported = root or task
    already_finished = is_final_status(reported.status)
    for row in (task, root):
        if row is None or is_final_status(row.status):
            continue
        row.status = TaskStatus.FAILED.value
        if row.result is not None:
            row.result.result_data = text
            row.result.future_actions = []
    db.commit()
    if already_finished:
        return False
    message = None
    if reported.conversation_id is not None:
        message = add_messages(
            "assistant",
            text,
            reported.conversation_id,
            db,
            agent_id=agent_id,
            agent_name=agent_name,
            skill_used=skill_used,
        )
    await publish_agent_message(
        reported.id,
        reported.conversation_id,
        text,
        event_type=TaskEventType.ERROR,
        stage=TaskStage.GENERATION,
        agent_id=agent_id,
        agent_name=agent_name,
        skill_used=skill_used,
        status=TaskStatus.FAILED.value,
        reason=reason,
        route=ROUTE_AGENT,
        message_id=_message_id(message),
    )
    return True


async def _broadcast_manager_message(
    conversation_id: int | str | None,
    text: str,
    db: Session,
    skill_used: str = "orchestration",
    *,
    task_id: str,
) -> None:
    """Persist + broadcast a chat message attributed to the Manager agent.

    Skipped when ``conversation_id`` is None (standalone tasks). The Manager
    row is looked up by name — if absent (older seed), the message is still
    persisted as an assistant turn but WS attribution is dropped silently so
    older clients keep working.
    """
    if conversation_id is None or not text:
        return
    manager = get_manager_agent(db)
    _agent_id = manager.id if manager else None
    _agent_name = manager.name if manager else "Manager"
    # Persist attribution so a chat reload still renders this row with the
    # Manager's violet bubble + chip; otherwise loaded history is stripped of
    # everything but role+content and styling regresses to plain agent.
    message = add_messages(
        "assistant",
        text,
        int(conversation_id),
        db,
        agent_id=_agent_id,
        agent_name=_agent_name,
        skill_used=skill_used,
    )
    await publish_agent_message(
        task_id,
        conversation_id,
        text,
        stage=TaskStage.ROUTING,
        agent_id=_agent_id,
        agent_name=_agent_name,
        skill_used=skill_used,
        message_id=_message_id(message),
    )


# Per-step transcript cap so a runaway specialist (e.g. one that dumped its
# whole retrieved context) doesn't blow the next agent's prompt budget. With
# 8192-token tokenizer cap on the worker and ~12 chars/token average, a 4000-
# char-per-step ceiling lets up to ~6 steps fit alongside the persona and the
# new action instruction. Tune with chain length in mind.
_CHAIN_STEP_CHAR_CAP = 4000
_CHAIN_TOTAL_CHAR_CAP = 16000


def _get_chain_root(task: "Task", db: Session) -> "Task":
    """Return the root task for the chain ``task`` belongs to.

    With the tree model, every subtask points directly at the root via
    ``parent_task_id``. Single-agent (non-decomposed) tasks have no parent
    and are their own root. Defensive: an unexpected linked-list shape from
    pre-tree-refactor data still terminates by walking until parent is None.
    """
    cursor = task
    visited = set()
    while cursor.parent_task_id is not None and cursor.id not in visited:
        visited.add(cursor.id)
        parent = db.query(Task).filter(Task.id == cursor.parent_task_id).first()
        if parent is None:
            break
        cursor = parent
    return cursor


def _build_chain_transcript(current_task: "Task", db: Session) -> tuple[str, str]:
    """Build a transcript of every completed sibling subtask under the same root.

    Tree model: all subtasks of one user demand share ``parent_task_id ==
    root.id`` and are ordered via the ``order`` column. The transcript lists
    them in execution order, with the original user demand pulled from the
    root task's ``query``. Subtasks with ``order < current_task.order`` are
    treated as prior steps; the current task's own result is included so the
    next specialist sees it.

    Returns ``(transcript, original_user_demand)``. Empty transcript when
    ``current_task`` is the first subtask (nothing before).
    """
    root = _get_chain_root(current_task, db)
    original_demand = root.query or current_task.query or ""

    # Sibling subtasks (everything under the same root, including current).
    siblings: list[Task] = (
        db.query(Task)
        .filter(Task.parent_task_id == root.id)
        .order_by(Task.order.asc())
        .all()
    )
    # If current_task IS the root (single-agent, no decomposition), there are
    # no siblings — fall back to "self as the only step".
    if not siblings:
        siblings = [current_task]

    # Include every sibling up to and including the current task, in order.
    cutoff_order = current_task.order or 0
    prior_steps = [t for t in siblings if (t.order or 0) <= cutoff_order]

    if not prior_steps:
        return "", original_demand

    lines: list[str] = ["=== Chain transcript (in order) ==="]
    total = 0
    for idx, t in enumerate(prior_steps, start=1):
        agent_row = db.query(Agents).filter(Agents.id == t.agent_id).first()
        agent_name = agent_row.name if agent_row else (t.agent_id or "?")
        agent_type = (
            agent_row.type.value if (agent_row and agent_row.type) else "?"
        )
        result_text = ""
        if t.result and t.result.result_data:
            data = t.result.result_data
            result_text = data if isinstance(data, str) else json.dumps(data)
        if not result_text:
            result_text = "(no result recorded yet)"
        if len(result_text) > _CHAIN_STEP_CHAR_CAP:
            result_text = result_text[:_CHAIN_STEP_CHAR_CAP] + "\n…[step truncated]"

        block = (
            f"\n[Step {idx} — {agent_name} ({agent_type})]\n"
            f"Action: {t.query or '(no action recorded)'}\n"
            f"Result:\n{result_text}\n"
        )
        if total + len(block) > _CHAIN_TOTAL_CHAR_CAP:
            lines.append(
                "\n…[remaining earlier steps omitted to keep prompt within budget]"
            )
            break
        lines.append(block)
        total += len(block)
    lines.append("\n=== End chain transcript ===")
    return "\n".join(lines), original_demand


def _promote_to_chain_root(root: "Task", db: Session) -> None:
    manager = get_manager_agent(db)
    if manager is not None:
        root.agent_id = manager.id
    else:
        logger.warning(
            "Manager agent not found in directory; the chain root keeps its "
            "placeholder owner. Run migration b5d2e1f3a9c7 and restart MAS "
            "so the seed inserts the Manager row."
        )
    root.status = TaskStatus.RUNNING.value
    root.order = 0
    db.commit()
    logger.info(
        "Chain root ready: id=%s query=%r",
        root.id,
        (root.query or "")[:120],
    )


# RabbitMQ messages are kept small; reject huge inline payloads at the API
# boundary so we never silently drop a worker due to a 256 MB-class envelope.
_MAX_INLINE_FILE_BYTES = 2 * 1024 * 1024  # 2 MB per inline file (decoded).
_MAX_TOTAL_INLINE_BYTES = 8 * 1024 * 1024  # 8 MB combined across all inline files.


def _build_files_payload(task: "TaskForm") -> list[dict]:
    """Translate a TaskForm's attachments into the wire format the agent reads.

    Knowledge-store refs are passed by filename; the agent worker resolves the
    text on the fly. Inline files travel as base64 inside the RabbitMQ message
    and are decoded by the consumer. Returns ``[]`` when nothing is attached.
    """
    import base64

    files: list[dict] = []
    for ref in task.attached_files or []:
        name = (ref.filename or "").strip()
        if not name:
            continue
        entry = {"source": "knowledge_store", "filename": name}
        doc_id = (ref.doc_id or "").strip()
        if doc_id:
            entry["doc_id"] = doc_id
        files.append(entry)

    total_inline = 0
    for inl in task.inline_files or []:
        name = (inl.filename or "").strip()
        if not name or not inl.content_b64:
            continue
        try:
            raw = base64.b64decode(inl.content_b64, validate=True)
        except Exception as exc:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid base64 for inline file '{name}': {exc}",
            )
        if len(raw) > _MAX_INLINE_FILE_BYTES:
            raise HTTPException(
                status_code=413,
                detail=(
                    f"Inline file '{name}' exceeds {_MAX_INLINE_FILE_BYTES} bytes. "
                    "Upload it to the knowledge store instead."
                ),
            )
        total_inline += len(raw)
        if total_inline > _MAX_TOTAL_INLINE_BYTES:
            raise HTTPException(
                status_code=413,
                detail=(
                    f"Total inline file size exceeds {_MAX_TOTAL_INLINE_BYTES} bytes."
                ),
            )
        files.append(
            {
                "source": "inline",
                "filename": name,
                "mime": inl.mime,
                "content_b64": inl.content_b64,
            }
        )
    return files


def get_task_queue_stats(db: Session) -> dict[str, Any]:
    """Aggregate task counts by status from the database."""
    rows = (
        db.query(Task.status, func.count(Task.id))
        .filter(Task.parent_task_id.is_(None))
        .group_by(Task.status)
        .all()
    )
    counts = {
        "queued": 0,
        "pending": 0,
        "running": 0,
        "completed": 0,
        "failed": 0,
        "cancelled": 0,
    }
    for status, n in rows:
        sv = status.value if isinstance(status, TaskStatus) else str(status)
        key = {
            TaskStatus.QUEUED.value: "queued",
            TaskStatus.PENDING.value: "pending",
            TaskStatus.RUNNING.value: "running",
            TaskStatus.COMPLETED.value: "completed",
            TaskStatus.FAILED.value: "failed",
            TaskStatus.CANCELED.value: "cancelled",
        }.get(sv)
        if key is not None:
            counts[key] = int(n)
    counts["total"] = sum(counts.values())
    return counts


def update_task_queue_depth(depth: int):
    """Update task queue depth metric."""
    TASK_QUEUE_DEPTH.set(depth)


@router.get(
    "/list",
    summary="List all tasks",
    description=(
        "Retrieve top-level tasks from the database. Excludes subtasks of a "
        "chain (rows whose ``parent_task_id`` is set) so the user-facing list "
        "shows one row per original demand, not per chain step. Admins and "
        "managers get every task; other roles get the tasks they own and every "
        "task in a conversation they own. Requires TASK_READ permission."
    ),
    status_code=200,
    dependencies=[Depends(PermissionChecker(Permission.TASK_READ))],
)
def list_tasks(
    user: Annotated[dict, Depends(PermissionChecker(Permission.TASK_READ))],
    db: Session = Depends(get_db),
):
    # Tree model: each multi-agent chain is one root Task with N subtask
    # children. The list view wants just the roots — clicking through opens
    # the detail page which shows the chain underneath.
    roots = db.query(Task).filter(Task.parent_task_id.is_(None))
    tasks = root_tasks_visible_to(user, roots).all()
    logger.info("Listing root tasks", count=len(tasks))
    return tasks


@router.get(
    "/stats/queue",
    summary="Get task queue statistics",
    description=(
        "Retrieve task counts by status (queued, pending, running, completed, failed, "
        "cancelled) and their total. Counts top-level tasks only, like "
        "``/tasks/list``: subtasks of a chain are excluded. Requires "
        "VIEW_ANALYTICS permission."
    ),
    status_code=200,
    dependencies=[Depends(PermissionChecker(Permission.VIEW_ANALYTICS))],
    responses=QUEUE_STATS_RESPONSES,
)
async def get_queue_stats(
    user: Annotated[dict, Depends(PermissionChecker(Permission.VIEW_ANALYTICS))],
    db: Session = Depends(get_db),
):
    """
    Retrieve task statistics from persisted tasks.

    Returns:
        dict: Counts by status and total.
    """
    stats = get_task_queue_stats(db)
    logger.info("Queue statistics retrieved", stats=stats)
    return stats


def _task_status_value(status) -> str:
    v = status.value if hasattr(status, "value") else str(status)
    if v == "canceled":
        return "cancelled"
    return v


def _isoformat_or_none(moment) -> str | None:
    return moment.isoformat() if moment else None


@router.get(
    "/conversation/{conversation_id}/running",
    summary="List in-flight root tasks for a conversation",
    description=(
        "Returns root-level tasks in this conversation whose status is not "
        "yet terminal (QUEUED, PENDING or RUNNING). The chat page calls this on "
        "mount so a user who navigates away and back still sees the "
        "in-progress spinner + working-agents bar instead of a stale chat "
        "that looks finished. Subtasks (rows with parent_task_id) are "
        "excluded — only the user-visible root surfaces. Allowed for the "
        "conversation's owner, a manager or an admin."
    ),
    status_code=200,
    dependencies=[Depends(PermissionChecker(Permission.TASK_READ))],
)
def list_running_tasks_for_conversation(
    conversation_id: int,
    user: Annotated[dict, Depends(PermissionChecker(Permission.TASK_READ))],
    db: Session = Depends(get_db),
):
    conversation = (
        db.query(Conversations).filter(Conversations.id == conversation_id).first()
    )
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if not may_read_conversation_tasks(user, conversation):
        raise HTTPException(status_code=403, detail=RUNNING_TASKS_REFUSED)
    rows = (
        db.query(Task)
        .filter(
            Task.conversation_id == conversation_id,
            Task.parent_task_id.is_(None),
            Task.status.in_(sorted(IN_PROGRESS_STATUSES)),
        )
        .order_by(Task.created_at.desc())
        .all()
    )
    # Use the same field names as the ``TaskSummary`` TS interface
    # (``id``, not ``task_id``) so the existing client type works unchanged.
    return [
        {
            "id": t.id,
            "status": _task_status_value(t.status),
            "agent_id": t.agent_id,
            "conversation_id": t.conversation_id,
            "query": t.query,
            "created_at": t.created_at.isoformat() if t.created_at else "",
            "parent_task_id": t.parent_task_id,
        }
        for t in rows
    ]


@router.get(
    "/{task_id}",
    summary="Get task details",
    description=(
        "Returns a task, optional result, and child subtasks. Allowed for the "
        "task's owner (else its root task's), the owner of its conversation, a "
        "manager or an admin. Requires TASK_READ."
    ),
    status_code=200,
    dependencies=[Depends(PermissionChecker(Permission.TASK_READ))],
)
def get_task_detail(
    task_id: str,
    user: Annotated[dict, Depends(PermissionChecker(Permission.TASK_READ))],
    db: Session = Depends(get_db),
):
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if not may_read_task(user, task, db):
        raise HTTPException(status_code=403, detail=TASK_READ_REFUSED)
    tr = db.query(TaskResult).filter(TaskResult.task_id == task_id).first()
    children = (
        db.query(Task)
        .filter(Task.parent_task_id == task_id)
        .order_by(Task.created_at.asc())
        .all()
    )

    result_str = None
    if tr and tr.result_data is not None:
        if isinstance(tr.result_data, str):
            result_str = tr.result_data
        else:
            result_str = json.dumps(tr.result_data)

    subtasks_out = [
        {
            "id": c.id,
            "title": (c.query[:200] + "…") if len(c.query) > 200 else c.query,
            "status": _task_status_value(c.status),
            "assignedAgent": c.agent_id,
            "skillsRequired": c.skills_required or [],
            "createdAt": _isoformat_or_none(c.created_at),
            "completedAt": _isoformat_or_none(c.completed_at),
        }
        for c in children
    ]

    return {
        "task_id": task.id,
        "status": _task_status_value(task.status),
        "agent_id": task.agent_id,
        "conversation_id": task.conversation_id,
        "query": task.query,
        "skills_required": task.skills_required or [],
        "created_at": task.created_at.isoformat() if task.created_at else "",
        "completed_at": _isoformat_or_none(task.completed_at),
        "result": result_str,
        "sources": getattr(tr, "sources", None) or [],
        "ai_provider": getattr(tr, "ai_provider", None),
        "history": tr.history if tr else [],
        "future_actions": tr.future_actions if tr else [],
        "subtasks": subtasks_out,
    }


class SuggestSkillsRequest(BaseModel):
    demand: str = Field(..., min_length=1, max_length=2000)
    top_k: int = Field(default=3, ge=1, le=10)


class SuggestedSkill(BaseModel):
    skill: str
    score: float
    agent_id: str
    agent_name: str


class SuggestSkillsResponse(BaseModel):
    suggestions: list[SuggestedSkill]


@router.post(
    "/suggest-skills",
    summary="Suggest skills for a task demand",
    description=(
        "Returns the top-N agent skills ranked by semantic similarity to the "
        "supplied demand string. Uses a cached MiniLM sentence embedding over "
        "every registered agent's (skill, description) pairs — no LLM call. "
        "Requires TASK_CREATE."
    ),
    status_code=200,
    tags=["Tasks"],
    response_model=SuggestSkillsResponse,
    dependencies=[Depends(PermissionChecker(Permission.TASK_CREATE))],
)
def suggest_skills_for_demand(
    body: SuggestSkillsRequest,
    _user: Annotated[dict, Depends(PermissionChecker(Permission.TASK_CREATE))],
):
    try:
        suggestions = rank_skills(body.demand, top_k=body.top_k)
    except Exception:
        logger.exception("Skill suggestion failed; returning empty list")
        suggestions = []
    return {"suggestions": suggestions}


def _accepted(
    task_id: str,
    status: str,
    conversation_id: int | None,
    *,
    replayed: bool = False,
) -> JSONResponse:
    return JSONResponse(
        status_code=202,
        content={
            "task_id": task_id,
            "status": status,
            "conversation_id": conversation_id,
        },
        headers={"Idempotent-Replayed": "true"} if replayed else None,
    )


def _queued_task_agent_id(db: Session) -> str:
    manager = get_manager_agent(db)
    return manager.id if manager is not None else QUEUED_TASK_AGENT_ID


def _message_id(message: Any) -> int | None:
    return message.get("id") if isinstance(message, dict) else None


@router.post("/new_task", include_in_schema=False, status_code=202)
@router.post(
    "/new_task/",
    summary="Queue a new task",
    description=(
        "Stores the task with status ``queued`` and returns ``202 {task_id}`` "
        "at once. Routing, planning and dispatch to the agents run in a "
        "background job; follow them on the conversation WebSocket or with "
        "``GET /tasks/{task_id}/events``. An ``Idempotency-Key`` header makes "
        "retries safe: the same key from the same user returns the same "
        "task_id for 24 h and never creates a second task. A conversation_id "
        "must be a conversation of the poster, unless the poster is an admin. "
        "Requires TASK_CREATE permission."
    ),
    status_code=202,
    tags=["Tasks"],
    dependencies=[Depends(PermissionChecker(Permission.TASK_CREATE))],
    responses=CREATE_TASK_RESPONSES,
    openapi_extra=CREATE_TASK_OPENAPI_EXTRA,
)
async def create_new_task(
    task: TaskForm,
    user: Annotated[dict, Depends(PermissionChecker(Permission.TASK_CREATE))],
    db: Session = Depends(get_db),
    idempotency_key: Annotated[
        str | None,
        Header(
            alias="Idempotency-Key",
            min_length=1,
            max_length=IDEMPOTENCY_KEY_MAX_LENGTH,
        ),
    ] = None,
):
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication Failed")
    if task.conversation_id is not None:
        conversation = (
            db.query(Conversations).filter(Conversations.id == task.conversation_id).first()
        )
        if conversation is None:
            raise HTTPException(status_code=404, detail="Conversation not found")
        if not may_add_task_to(user, conversation):
            raise HTTPException(status_code=403, detail=NEW_TASK_REFUSED)

    files_payload = _build_files_payload(task)
    task_id = str(uuid.uuid4())
    if idempotency_key:
        claimed_id = claim_task_id(user.get("id"), idempotency_key, task_id)
        if claimed_id != task_id:
            existing = db.query(Task).filter(Task.id == claimed_id).first()
            logger.info("Replaying an idempotent new_task", task_id=claimed_id)
            return _accepted(
                claimed_id,
                _task_status_value(existing.status)
                if existing is not None
                else TaskStatus.QUEUED.value,
                existing.conversation_id if existing is not None else task.conversation_id,
                replayed=True,
            )

    try:
        insert_queued_task(
            task_id,
            task.conversation_id,
            _queued_task_agent_id(db),
            task.demand,
            user.get("username"),
            db,
            skills_required=task.skills_required,
        )
    except Exception as exc:
        if idempotency_key:
            release_task_id(user.get("id"), idempotency_key, task_id)
        logger.exception("Could not store the queued task")
        raise HTTPException(status_code=500, detail="Failed to create task") from exc

    if task.conversation_id is not None:
        add_messages("user", task.demand, task.conversation_id, db)
    await publish_task_status(
        task_id, task.conversation_id, TaskStatus.QUEUED.value, stage=TaskStage.QUEUED
    )
    task_jobs.submit(task_id, run_routing_job(task_id, task, files_payload))
    logger.info(
        "Task queued for routing",
        task_id=task_id,
        conversation_id=task.conversation_id,
        mode=task.mode or "auto",
    )
    return _accepted(task_id, TaskStatus.QUEUED.value, task.conversation_id)


async def run_routing_job(
    task_id: str, task: TaskForm, files_payload: list[dict]
) -> dict:
    db = SessionLocal()
    try:
        return await _route_queued_task(task_id, task, files_payload, db)
    except Exception as exc:
        logger.exception("Routing failed for task %s", task_id)
        db.rollback()
        detail = exc.detail if isinstance(exc, HTTPException) else str(exc)
        return await _fail_unrouted_task(
            task_id,
            task,
            f"The orchestrator could not route this request: {detail}",
            db,
        )
    finally:
        db.close()


async def _route_queued_task(
    task_id: str, task: TaskForm, files_payload: list[dict], db: Session
) -> dict:
    queued = db.query(Task).filter(Task.id == task_id).first()
    if queued is None or is_final_status(queued.status):
        logger.info("Task %s was stopped before routing started", task_id)
        return _stopped_outcome(task_id)

    logger.info(
        "Starting agent selection process for new task",
        task_id=task_id,
        demand=task.demand[:50],
        conversation_id=task.conversation_id,
        mode=task.mode or "auto",
        explicit_agent_id=task.agent_id,
    )
    await publish_task_status(
        task_id, task.conversation_id, "routing", stage=TaskStage.ROUTING
    )
    if task.mode == "decompose":
        return await _route_by_forced_decomposition(queued, task, files_payload, db)
    return await _route_by_selection(queued, task, files_payload, db)


async def _route_by_forced_decomposition(
    queued: Task, task: TaskForm, files_payload: list[dict], db: Session
) -> dict:
    # Force-decomposition mode: skip the single-agent router/skill/auto-create
    # path entirely and jump straight to the planner. Without this short-cut,
    # cross-domain demands almost always land on a single specialist (or get
    # an auto-created Specialist-Knowledge-Retriever) because the router or
    # skill-match catches them before decomposition can fire. With ``mode=
    # "decompose"`` we let the planner break the demand into per-domain
    # subtasks and dispatch each to the matching agent.
    logger.info("Force-decompose mode: jumping straight to planner")
    first_action, actions_list = await run_in_threadpool(
        decompose_task, task.demand, db
    )
    if _routing_was_stopped(queued, db):
        return _stopped_outcome(queued.id)
    if not first_action:
        # Surface the actual reason so the user can fix it (vs. blaming
        # their prompt). The two real failure modes are: (a) zero
        # non-Manager agents in the directory, and (b) the skill cache
        # never warmed (embedder still loading on container boot).
        non_manager = (
            db.query(Agents)
            .filter(Agents.name != "Manager")
            .count()
        )
        if non_manager == 0:
            fallback = (
                "Decomposition produced no plan — there are no specialist "
                "agents registered in the directory yet. Start the agent "
                "worker container (or wait for it to register) and retry."
            )
        elif non_manager < 2:
            fallback = (
                "Decomposition produced no plan — only one non-Manager "
                "agent is registered, so there's nothing to decompose "
                "across. Bring more specialists online (the default seed "
                "registers five) or use auto mode for single-agent dispatch."
            )
        else:
            fallback = (
                "Decomposition produced no plan — the planner LLM and the "
                "skill-embedding fallback both returned nothing. Try a "
                "more explicit multi-domain demand, or check MAS logs for "
                "planner JSON parse errors."
            )
        return await _fail_routing(queued, task, fallback, db)

    agent_id, user_demand = first_action
    return await _dispatch_chain(
        queued,
        task,
        files_payload,
        agent_id,
        user_demand,
        actions_list,
        db,
        message=(
            f"Task '{task.demand}' decomposed into "
            f"{len(actions_list) + 1} subtask(s); first dispatched to agent {agent_id}"
        ),
        announce_plan=True,
    )


async def _route_by_selection(
    queued: Task, task: TaskForm, files_payload: list[dict], db: Session
) -> dict:
    # 1. Selection Phase
    # Try the explicit-mode dispatcher first; if it returns no agent (e.g. mode=auto
    # or unresolvable) fall through to the LLM router. This keeps the legacy chat
    # path (no mode field) working untouched.
    agent_id, user_demand, direct_response, future_actions = select_agent_by_mode(
        task.demand, task.skills_required, task.mode, task.agent_id, db
    )
    if not agent_id and not direct_response:
        # The LLM router runs a full generation. On CPU that is minutes, and MAS
        # serves from a single Uvicorn worker, so calling it inline blocks the
        # event loop for every other request, including the Compose healthcheck.
        agent_id, user_demand, direct_response, future_actions = (
            await run_in_threadpool(route_task, task.demand, db, task_id=queued.id)
        )
        if _routing_was_stopped(queued, db):
            return _stopped_outcome(queued.id)

    if direct_response and _has_attachments(task):
        logger.info(
            "Discarding the direct answer: the task has attached files, "
            "so an agent reads them instead"
        )
        direct_response = None

    # Skill-based fallback. The LLM router can fail (bad JSON, picked an
    # unknown agent name, classified as COMPLEX) even when there *is* an
    # agent that advertises the user's requested skill. Walk the supplied
    # ``skills_required`` and pick the first agent that matches — much
    # cheaper than running decomposition and avoids spurious "no agent"
    # errors. If nothing matches here we still try decomposition below.
    if not agent_id and not direct_response and task.skills_required:
        for skill in task.skills_required:
            fb_agent_id, fb_demand, _direct, _future = select_agent_by_mode(
                task.demand, [skill], "any_with_skill", None, db
            )
            if fb_agent_id:
                logger.info(
                    "LLM router skipped/missed; using skill-match fallback",
                    skill=skill,
                    agent_id=fb_agent_id,
                )
                agent_id, user_demand = fb_agent_id, fb_demand
                future_actions = []
                break

    # Catch-all: nothing matched (no skills specified, or none of the
    # specified ones advertised). Two-step strategy:
    #   1. If the user supplied skills no agent advertises, AUTO-CREATE a new
    #      specialist agent with those skills, dispatched to the same general
    #      worker pool. Its credentials travel in the task payload so the
    #      worker can authenticate as the new identity for result POSTs and
    #      pick it up for future heartbeats.
    #   2. Otherwise fall back to any active general agent so the user always
    #      gets a response (avoids running decomposition with a small router
    #      model that tends to mis-classify simple requests as COMPLEX_TASK
    #      and then produce unparseable plans).
    auto_created_api_key: str | None = None
    auto_created_name: str | None = None
    if not agent_id and not direct_response:
        # Identify which requested skills are genuinely missing from the
        # directory — only auto-create when a real gap exists.
        missing_skills: list[str] = []
        if task.skills_required:
            existing_active = (
                db.query(Agents).filter(Agents.status == "active").all()
            )
            advertised: set[str] = set()
            for a in existing_active:
                for s in (a.skills or []):
                    advertised.add(s)
            missing_skills = [
                s for s in task.skills_required if s not in advertised
            ]

        if missing_skills:
            spec_name = _next_specialist_name(missing_skills, db)
            spec_desc = (
                "Auto-created specialist for skill(s): "
                + ", ".join(missing_skills)
                + ". Backed by the General-Assistant worker pool."
            )
            try:
                new_id, new_key, _ = await create_agent(
                    name=spec_name,
                    skills=missing_skills,
                    description=spec_desc,
                    db=db,
                    Agent_type=AgentTypes.GENERAL,
                )
            except Exception:
                logger.exception("Auto-create specialist failed; falling through.")
                new_id, new_key = None, None
            if new_id and new_key:
                logger.info(
                    "Auto-created specialist agent",
                    agent_id=new_id,
                    agent_name=spec_name,
                    skills=missing_skills,
                )
                agent_id = new_id
                user_demand = task.demand
                future_actions = []
                # Stash the plaintext api_key so the dispatch payload can carry
                # it to the worker. (Hashed copy is already in the DB.)
                auto_created_api_key = new_key
                auto_created_name = spec_name

        if not agent_id:
            catch_all = (
                db.query(Agents)
                .filter(Agents.status == "active", Agents.type == "general")
                .order_by(Agents.last_heartbeat.desc())
                .first()
            )
            if catch_all is None:
                catch_all = (
                    db.query(Agents)
                    .filter(Agents.status == "active")
                    .order_by(Agents.last_heartbeat.desc())
                    .first()
                )
            if catch_all is not None:
                logger.info(
                    "No skill match; falling back to active catch-all agent",
                    agent_id=catch_all.id,
                    agent_name=catch_all.name,
                )
                agent_id = catch_all.id
                user_demand = task.demand
                future_actions = []

    # 2. Direct Answer Handling
    if direct_response:
        return await _answer_directly(queued, task, direct_response, db)

    credentials = _auto_created_credentials(
        auto_created_api_key, auto_created_name, task
    )

    # 3. Single Agent Assignment
    if agent_id:
        logger.info("Agent selected for task", agent_id=agent_id)
        message = f"Task '{task.demand}' assigned to agent {agent_id}"
        if future_actions:
            return await _dispatch_chain(
                queued,
                task,
                files_payload,
                agent_id,
                user_demand,
                future_actions,
                db,
                message=message,
                announce_plan=True,
                extra_payload=credentials,
            )
        return await _dispatch_single_agent(
            queued,
            task,
            files_payload,
            agent_id,
            user_demand,
            db,
            message=message,
            extra_payload=credentials,
        )

    # 4. Decomposition Fallback
    logger.info(
        "No single agent found or COMPLEX_TASK classified. Attempting decomposition."
    )
    first_action, actions_list = await run_in_threadpool(
        decompose_task, task.demand, db
    )
    if _routing_was_stopped(queued, db):
        return _stopped_outcome(queued.id)

    if not first_action:
        # Distinguish "absolutely zero agents in the directory" from "agents
        # exist but none match this skill set" — the former is a setup
        # problem, the latter is a routing miss.
        any_agents = db.query(Agents).count() > 0
        if not any_agents:
            fallback = (
                "No agents are currently registered with the orchestrator. "
                "Wait for an agent worker to come online, or check the agent "
                "service logs."
            )
        elif task.skills_required:
            fallback = (
                "Could not match this task to any registered agent. The "
                "requested skill(s) "
                f"{', '.join(repr(s) for s in task.skills_required)} "
                "aren't advertised by any agent that's online right now. "
                "Try again once the relevant agent is up, or pick a "
                "different skill."
            )
        else:
            fallback = (
                "The orchestrator couldn't decide which agent should handle "
                "this. Try rephrasing the task, or pick a specific skill from "
                "the dropdown so routing has more to go on."
            )
        return await _fail_routing(queued, task, fallback, db)

    agent_id, user_demand = first_action
    message = f"Task '{task.demand}' decomposed and assigned to agent {agent_id}"
    if actions_list:
        return await _dispatch_chain(
            queued,
            task,
            files_payload,
            agent_id,
            user_demand,
            actions_list,
            db,
            message=message,
            announce_plan=False,
            extra_payload=credentials,
        )
    return await _dispatch_single_agent(
        queued,
        task,
        files_payload,
        agent_id,
        user_demand,
        db,
        message=message,
        extra_payload=credentials,
    )


def _has_attachments(task: TaskForm) -> bool:
    return bool(task.attached_files) or bool(task.inline_files)


def _routing_was_stopped(queued: Task, db: Session) -> bool:
    db.refresh(queued)
    return is_final_status(queued.status)


def _stopped_outcome(task_id: str) -> dict:
    return {"message": "Task was stopped before it was dispatched", "task_id": task_id}


def _auto_created_credentials(
    api_key: str | None, agent_name: str | None, task: TaskForm
) -> dict | None:
    if not api_key:
        return None
    # Auto-created specialist: the worker doesn't know this identity yet,
    # so we ship its credentials inside the task message. The worker reads
    # them, adds the profile to its registry, and authenticates as the
    # new agent for the result POST (and from then on for heartbeats).
    return {
        "assigned_agent_api_key": api_key,
        "assigned_agent_name": agent_name,
        "assigned_agent_skills": task.skills_required or [],
        "assigned_agent_type": "general",
    }


def _dispatch_payload(
    task: TaskForm,
    task_id: str,
    demand: str,
    files_payload: list[dict],
    extra_payload: dict | None,
) -> dict:
    payload = {
        "conversation_id": task.conversation_id,
        "task_id": task_id,
        "demand": demand,
        "skill_used": task.skills_required[0] if task.skills_required else None,
        "files": files_payload,
    }
    payload.update(extra_payload or {})
    return payload


def _finish_queued_task(
    queued: Task, status: TaskStatus, text: str, db: Session
) -> None:
    queued.status = status.value
    if queued.result is not None:
        queued.result.result_data = text
        if status == TaskStatus.COMPLETED:
            queued.result.history = [
                *(queued.result.history or []),
                {"role": "assistant", "message": text},
            ]
    db.commit()


async def _answer_directly(
    queued: Task, task: TaskForm, direct_response: str, db: Session
) -> dict:
    message = None
    if task.conversation_id is not None:
        message = add_messages(
            "assistant", direct_response, task.conversation_id, db
        )
    _finish_queued_task(queued, TaskStatus.COMPLETED, direct_response, db)
    await publish_agent_message(
        queued.id,
        task.conversation_id,
        direct_response,
        event_type=TaskEventType.RESULT,
        stage=TaskStage.ROUTING,
        status=TaskStatus.COMPLETED.value,
        route=ROUTE_DIRECT_ANSWER,
        message_id=_message_id(message),
    )
    return {
        "message": "Processing complete",
        "conversation_id": task.conversation_id,
        "task_id": queued.id,
        "result": direct_response,
    }


async def _fail_routing(queued: Task, task: TaskForm, text: str, db: Session) -> dict:
    message = None
    if task.conversation_id is not None:
        message = add_messages("assistant", text, task.conversation_id, db)
    _finish_queued_task(queued, TaskStatus.FAILED, text, db)
    await publish_agent_message(
        queued.id,
        task.conversation_id,
        text,
        event_type=TaskEventType.ERROR,
        stage=TaskStage.ROUTING,
        status=TaskStatus.FAILED.value,
        route=ROUTE_NONE,
        message_id=_message_id(message),
    )
    return {"message": text, "task_id": queued.id}


async def _fail_unrouted_task(
    task_id: str, task: TaskForm, text: str, db: Session
) -> dict:
    queued = db.query(Task).filter(Task.id == task_id).first()
    if queued is None or is_final_status(queued.status):
        return _stopped_outcome(task_id)
    return await _fail_routing(queued, task, text, db)


async def _announce_dispatch(db: Session, dispatch: _WorkDispatch) -> None:
    agent_name = _agent_name(db, dispatch.agent_id) or dispatch.agent_id
    await publish_task_status(
        dispatch.root_id,
        dispatch.conversation_id,
        TaskStatus.RUNNING.value,
        stage=TaskStage.RETRIEVAL,
        detail=f"Assigned to {agent_name}",
        agent_id=dispatch.agent_id,
        agent_name=agent_name,
    )


async def _dispatch_single_agent(
    queued: Task,
    task: TaskForm,
    files_payload: list[dict],
    agent_id: str,
    user_demand: str | None,
    db: Session,
    *,
    message: str,
    extra_payload: dict | None = None,
) -> dict:
    demand = user_demand or task.demand
    queued.agent_id = agent_id
    queued.query = demand
    db.commit()
    dispatch = _WorkDispatch(
        agent_id,
        _dispatch_payload(task, queued.id, demand, files_payload, extra_payload),
        queued.id,
        queued.id,
        task.conversation_id,
    )
    if not await _hand_to_agents(db, dispatch):
        return _stopped_outcome(dispatch.root_id)
    await _announce_dispatch(db, dispatch)
    TASK_QUEUE_DEPTH.inc()
    log_agent_operation(
        agent_id, "TASK", f"Assigned task {queued.id}: {task.demand[:50]}..."
    )
    return {
        "message": message,
        "conversation_id": task.conversation_id,
        "task_id": queued.id,
    }


async def _dispatch_chain(
    queued: Task,
    task: TaskForm,
    files_payload: list[dict],
    agent_id: str,
    user_demand: str | None,
    future_actions: list,
    db: Session,
    *,
    message: str,
    announce_plan: bool,
    extra_payload: dict | None = None,
) -> dict:
    demand = user_demand or task.demand
    _promote_to_chain_root(queued, db)
    history = [{"role": "user", "message": task.demand}]
    subtask_id = insert_new_task(
        task.conversation_id,
        agent_id,
        demand,
        history,
        list(future_actions),
        db,
        skills_required=task.skills_required,
    )
    if not subtask_id:
        raise HTTPException(status_code=500, detail="Failed to create task")
    subtask = db.query(Task).filter(Task.id == subtask_id).first()
    subtask.parent_task_id = queued.id
    subtask.order = 1
    db.commit()

    dispatch = _WorkDispatch(
        agent_id,
        _dispatch_payload(task, subtask_id, demand, files_payload, extra_payload),
        subtask_id,
        queued.id,
        task.conversation_id,
    )
    if not await _hand_to_agents(db, dispatch):
        return _stopped_outcome(dispatch.root_id)
    await _announce_dispatch(db, dispatch)
    TASK_QUEUE_DEPTH.inc()
    log_agent_operation(
        agent_id,
        "TASK",
        f"Assigned task {subtask_id} under root {queued.id}: {task.demand[:50]}...",
    )
    if announce_plan and task.conversation_id is not None:
        full_plan = [(agent_id, demand)] + list(future_actions)
        announcement = await run_in_threadpool(
            manager_announce_plan, task.demand, full_plan, db
        )
        await _broadcast_manager_message(
            task.conversation_id,
            announcement,
            db,
            skill_used="planning",
            task_id=queued.id,
        )
    return {
        "message": message,
        "conversation_id": task.conversation_id,
        "task_id": queued.id,
    }


@router.get(
    "/{task_id}/events",
    summary="Replay the stored events of a task",
    description=(
        "Returns the events stored for the task with ``seq`` greater than "
        "``since``, oldest first. Every per-task WebSocket frame is stored "
        "for 24 h, so a client that was disconnected can call this with the "
        "last ``seq`` it saw and replay what it missed. Allowed for the "
        "task's owner, the owner of its conversation, a manager or an admin."
    ),
    status_code=200,
    dependencies=[Depends(PermissionChecker(Permission.TASK_READ))],
)
async def get_task_events(
    task_id: str,
    user: Annotated[dict, Depends(PermissionChecker(Permission.TASK_READ))],
    since: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=TASK_EVENTS_PAGE_MAX)] = TASK_EVENTS_PAGE_DEFAULT,
    db: Session = Depends(get_db),
):
    task = db.query(Task).filter(Task.id == task_id).first()
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    if not may_read_task(user, task, db):
        raise HTTPException(status_code=403, detail=TASK_EVENTS_REFUSED)
    try:
        events = await run_in_threadpool(read_task_events, task_id, since, limit)
    except Exception as exc:
        logger.warning("Task event store unavailable for task %s", task_id, exc_info=True)
        raise HTTPException(
            status_code=503, detail="The task event store is unavailable"
        ) from exc
    return {
        "task_id": task_id,
        "status": _task_status_value(task.status),
        "since": since,
        "events": events,
        "last_seq": events[-1]["seq"] if events else since,
        "has_more": len(events) >= limit,
    }


@router.post(
    "/task-result/",
    summary="Submit task result from agent",
    description="Receive the result from an agent, add to conversation history, distribute via WebSocket. Handles subtasks and future actions if defined. Requires TASK_EXECUTE permission. Requires 'X-API-Key' and 'Agent-ID' headers for authentication.",
    status_code=200,
    tags=["Tasks"],
    responses=SHARE_RESULT_RESPONSES,
    openapi_extra=SHARE_RESULT_OPENAPI_EXTRA,
)
async def sharing_agent_result(
    task_result: TaskResultForm,
    verified_agent: Annotated[tuple[str, str], Depends(verify_agent_api_key)],
    db: Session = Depends(get_db),
):
    """Ingest an agent's task result.

    Verifies the agent, updates task status to COMPLETED, stores the result,
    chains any follow-up actions, and notifies the UI over WebSocket.

    Args:
        task_result: Result payload (output, status, suggestions).
        verified_agent: Authenticated agent ``(id, api_key)``.
        db: Active database session.

    Raises:
        HTTPException: 403 on id mismatch, 404 if task missing, 500 on
            internal failure (e.g. recursion guard).
    """
    verified_agent_id, _ = verified_agent

    task = db.query(Task).filter(Task.id == task_result.task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if task_result.agent_id != task.agent_id:
        raise HTTPException(
            status_code=403,
            detail="agent_id in body must match the task's assigned agent",
        )

    if not agent_may_submit_task_result(verified_agent_id, task.agent_id, db):
        raise HTTPException(
            status_code=403,
            detail="Authenticated agent is not allowed to complete this task",
        )

    if task_result.status != TaskResultStatus.COMPLETED:
        if await _answer_again(task, task_result, db):
            return {"message": f"Task {task.id} is answered once more"}
        if task_result.status == TaskResultStatus.FAILED:
            return await _record_agent_failure(task, task_result, db)
        task_result = task_result.model_copy(
            update={"result": NOT_IN_DOCUMENTS_TEXT, "sources": []}
        )

    step_sources = _sources_of(task_result)
    try:
        validating_task_results(
            task_result.task_id,
            task_result.result,
            db,
            skill_used=task_result.skill_used,
        )
        task = db.query(Task).filter(Task.id == task_result.task_id).first()
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        current_task_result = task.result
        if not current_task_result:
            raise HTTPException(status_code=404, detail="TaskResult not found")

        action_list = current_task_result.future_actions or []
        history = current_task_result.history or []
        chain_root_id = task.parent_task_id or task.id

        task.status = TaskStatus.COMPLETED.value

        history.append({"role": "assistant", "message": task_result.result})
        ai_provider = await asyncio.to_thread(ai_mode.provider)

        current_task_result.result_data = task_result.result
        current_task_result.history = history
        current_task_result.sources = step_sources
        current_task_result.ai_provider = ai_provider
        db.commit()

        TASK_QUEUE_DEPTH.dec()
        observe_task_processing_time(task.created_at)
        log_agent_operation(
            task_result.agent_id,
            "TASK",
            f"Completed task {task_result.task_id} peak_rss_mb={peak_rss_mb()}",
        )

        # Hard depth cap: the Manager can re-route cyclically (INSERT), but a step
        # that fails every attempt (e.g. an LLM/backend error) would otherwise make
        # it INSERT forever — observed runaway to 50+ steps. Once the chain has run
        # MAX_CHAIN_STEPS, stop re-routing and wrap up with what we have.
        MAX_CHAIN_STEPS = 8
        if len(action_list) > 0 and (task.order or 0) >= MAX_CHAIN_STEPS:
            logger.warning(
                "Chain reached step %s (cap %s) — forcing DONE to stop runaway "
                "re-routing (a step is likely failing every attempt).",
                task.order,
                MAX_CHAIN_STEPS,
            )
            if task.conversation_id is not None:
                await _broadcast_manager_message(
                    task.conversation_id,
                    "Stopping here — this request hit its step limit without "
                    "completing cleanly. Returning the best result so far.",
                    db,
                    skill_used="review",
                    task_id=chain_root_id,
                )
            action_list = []
            current_task_result.future_actions = []
            db.commit()
        elif len(action_list) > 0:
            # Manager review: before automatically chaining to the next planned
            # step, ask the Manager LLM whether the chain has already answered
            # the user's demand (DONE), needs an unplanned extra step before
            # continuing (INSERT — cyclic re-routing back to an earlier
            # specialist), or should proceed as planned (CONTINUE). This is
            # what makes the platform a real orchestrator rather than a fixed
            # linear pipeline.
            transcript, original_demand = _build_chain_transcript(task, db)
            available_types = [t.value for t in AgentTypes if t != AgentTypes.MANAGER]
            review = await run_in_threadpool(
                manager_review_step,
                original_demand,
                transcript,
                action_list,
                available_types,
                db,
            )
            decision = review["decision"]
            logger.info(
                "Manager review: decision=%s reasoning=%s",
                decision,
                review.get("reasoning"),
            )

            if decision == "DONE":
                # Skip remaining planned steps — the chain has already produced
                # a sufficient answer. Aggregate + reply as if action_list was
                # empty. Fall through to the post-chain block below by clearing
                # action_list and rebuilding history (already appended above).
                if task.conversation_id is not None:
                    await _broadcast_manager_message(
                        task.conversation_id,
                        (
                            f"I'm wrapping up here — the chain has answered "
                            f"the original demand. ({review.get('reasoning') or ''})"
                        ).strip(),
                        db,
                        skill_used="review",
                        task_id=chain_root_id,
                    )
                action_list = []
                # Persist the truncated action list so any subsequent inspection
                # of this task's `future_actions` reflects the Manager's decision.
                current_task_result.future_actions = []
                db.commit()
            elif decision == "INSERT" and (task.order or 0) >= 3:
                # Anti-loop: past a few steps the 4B Manager tends to INSERT the
                # same "gather more info" step over and over (observed: 8x
                # "routing back to Researcher" with identical reasoning, hitting
                # the step cap and returning an incomplete answer). Suppress
                # cyclic re-routing here and proceed with the planned steps so
                # the chain finishes cleanly.
                logger.info(
                    "INSERT suppressed at step %s (anti-loop); proceeding with plan.",
                    task.order,
                )
            elif decision == "INSERT":
                # Resolve the requested agent_type to a concrete active agent
                # and PREPEND the inserted action to the planned list. The
                # rest of the chain still runs after this extra step.
                next_type = review.get("next_agent_type") or "general"
                next_action_text = (
                    review.get("next_action")
                    or "Provide additional information requested by the chain."
                )
                from db.models import Agents as _Agents
                resolved = (
                    db.query(_Agents)
                    .filter(_Agents.status == "active", _Agents.type == next_type)
                    .order_by(_Agents.last_heartbeat.desc())
                    .first()
                )
                if resolved is None:
                    # Fallback: take any active agent so we don't stall the chain.
                    resolved = (
                        db.query(_Agents)
                        .filter(_Agents.status == "active")
                        .order_by(_Agents.last_heartbeat.desc())
                        .first()
                    )
                if resolved is not None:
                    logger.info(
                        "Manager inserting cyclic step: %s -> %s",
                        resolved.name,
                        next_action_text[:80],
                    )
                    action_list = [(resolved.id, next_action_text)] + list(action_list)
                    if task.conversation_id is not None:
                        await _broadcast_manager_message(
                            task.conversation_id,
                            (
                                f"Routing back to {resolved.name} for an extra step "
                                f"before continuing. ({review.get('reasoning') or ''})"
                            ).strip(),
                            db,
                            skill_used="review",
                            task_id=chain_root_id,
                        )
                else:
                    logger.warning(
                        "Manager wanted to INSERT %s but no active agent resolved; continuing.",
                        next_type,
                    )
            # CONTINUE (or fall-through) — no-op; the loop below proceeds.

        if len(action_list) > 0:
            new_agent = action_list[0][0]
            new_action = action_list[0][1]
            remaining_actions = action_list[1:]

            # Accumulate ALL prior steps in the chain into the new specialist's
            # demand, not just the latest result. Without this, the third agent
            # in a Researcher → Accountant → Writer chain never saw the
            # Researcher's output — a known hallucination foothold. The
            # transcript carries each prior agent's name, the action it was
            # given, and its result so the next specialist can ground its work
            # on the actual chain history rather than relying on a one-hop
            # summary.
            transcript, original_demand = _build_chain_transcript(task, db)
            new_action_context = (
                f"=== Original user demand ===\n{original_demand}\n\n"
                f"{transcript}\n\n"
                f"=== Your task ({new_agent}'s turn) ===\n"
                f"{new_action}\n\n"
                "Ground your answer in the chain transcript above. Where prior "
                "specialists already established a fact, reuse their wording "
                "rather than re-deriving it. If you spot a gap that requires "
                "earlier-specialist work, flag it explicitly so the orchestrator "
                "can route back."
            )

            new_subtask_id = insert_new_task(
                task.conversation_id,
                new_agent,
                new_action_context,
                history,
                remaining_actions,
                db,
            )

            subtask = db.query(Task).filter(Task.id == new_subtask_id).first()
            # Tree model: parent every chained subtask to the SAME root, not
            # to the previous step. ``current_task.parent_task_id`` already
            # points to the root (because step-1 was set up that way), so
            # reuse it. Fallback to ``task.id`` only for legacy linear-chain
            # rows that pre-date the tree refactor.
            chain_root_id = task.parent_task_id or task.id
            subtask.parent_task_id = chain_root_id
            subtask.order = (task.order or 0) + 1
            db.commit()

            next_step = _WorkDispatch(
                new_agent,
                {
                    "conversation_id": task.conversation_id,
                    "task_id": new_subtask_id,
                    "demand": new_action_context,
                    # The full transcript above grounds the LLM, but it is a poor
                    # *retrieval* query: BGE-base truncates at 512 tokens, so the
                    # 16k-char transcript buries this specialist's actual task and
                    # the embedding is dominated by front-matter. Ship the bare
                    # assigned task so knowledge-store retrieval stays on-target.
                    "retrieval_query": new_action,
                },
                new_subtask_id,
                chain_root_id,
                task.conversation_id,
            )
            if not await _publish_unless_full(db, next_step):
                task_jobs.submit(new_subtask_id, _wait_for_room_job(next_step))
            TASK_QUEUE_DEPTH.inc()
            logger.info(
                f"Chained to next task: {new_subtask_id} assigned to agent {new_agent}"
            )

            # Visibility broadcast: tell the user, in their chat, which
            # specialist just finished and who is being called next. Without
            # this, the chain is silent between the Manager's initial plan and
            # the final aggregated answer — 3-10 minutes of "is anything
            # happening?" depending on the LLM. The message is short, attributed
            # to the Manager (violet bubble), so it doesn't compete visually
            # with specialist answers.
            if task.conversation_id is not None:
                # Resolve names for the announcement.
                prev_row = (
                    db.query(Agents).filter(Agents.id == task.agent_id).first()
                )
                next_row = (
                    db.query(Agents).filter(Agents.id == new_agent).first()
                )
                prev_name = prev_row.name if prev_row else (task.agent_id or "previous specialist")
                next_name = next_row.name if next_row else (new_agent or "next specialist")
                # Count completed siblings under the same root instead of
                # relying on ``task.order`` — when root creation failed (e.g.
                # Manager missing), order columns default to 0 and the
                # broadcast would show "Step 1 complete... routing for step 1"
                # for every iteration. Counting actual completed rows is
                # accurate regardless of what's in the ``order`` column.
                _root_id_for_count = task.parent_task_id or task.id
                _siblings = (
                    db.query(Task)
                    .filter(Task.parent_task_id == _root_id_for_count)
                    .all()
                )
                # Build a set of completed sibling ids and explicitly include
                # the just-completed task. SQLAlchemy's session cache + the
                # newly-inserted next subtask in the same transaction make
                # the raw query unreliable — without the explicit add, both
                # broadcasts on a 3-step chain showed "Step 1" because the
                # session view hadn't refreshed the current task's status.
                completed_ids = {
                    s.id
                    for s in _siblings
                    if s.status == TaskStatus.COMPLETED.value
                }
                completed_ids.add(task.id)
                completed_count = len(completed_ids)
                done_step = max(completed_count, 1)
                next_step = done_step + 1
                progress_text = (
                    f"✓ Step {done_step} complete — {prev_name} finished. "
                    f"Now routing to **{next_name}** for step {next_step}."
                )
                await _broadcast_manager_message(
                    task.conversation_id,
                    progress_text,
                    db,
                    skill_used="orchestration",
                    task_id=chain_root_id,
                )

            return {"message": f"Result received from agent {task_result.agent_id}"}

        # Single-agent / non-decomposed tasks (no Manager-owned chain root) have
        # exactly ONE result — the worker's answer already IS the final answer.
        # The ~10-40s aggregation LLM pass (a 1.5B router synthesis, brutal on
        # CPU) only makes sense when fusing multiple specialists' outputs, so
        # skip it here and use the raw result. This is the dominant e2e latency
        # for the common single-agent path. See scripts/perf measurements.
        if task.parent_task_id is None:
            final_answer = (task_result.result or "").strip()
            final_sources = step_sources
        else:
            final_sources = _chain_sources(db, chain_root_id, step_sources)
            await publish_task_status(
                chain_root_id,
                task.conversation_id,
                "aggregating",
                stage=TaskStage.AGGREGATION,
            )
            try:
                final_answer = await run_in_threadpool(
                    aggregate_results, history, task_result.result
                )
            except Exception as exc:
                logger.warning(
                    "aggregate_results raised (%s) — falling back to last subtask result.",
                    exc,
                )
                final_answer = None

        # The small router LLM that powers ``aggregate_results`` sometimes
        # returns nothing meaningful (parse failure, empty output, model
        # confusion when the chain produced fragmented content). Without a
        # fallback the WS broadcast carries an empty content string and the
        # frontend silently drops it — the user sees the chain "finish" with
        # no answer. Prefer the synthesized text when present, otherwise fall
        # back to the last specialist's raw output so the user always gets
        # *something*.
        if not (final_answer and str(final_answer).strip()):
            final_answer = (task_result.result or "").strip() or (
                "I completed the chain but couldn't synthesize a final answer. "
                "Check the task detail page for each specialist's output."
            )

        # Tree close-out: when this subtask is part of a multi-agent chain
        # (it has a Manager-owned root parent) and there are no remaining
        # actions, mark the root COMPLETED and write the aggregated answer
        # into it. That's the row the UI lists in "Recent tasks", so users
        # see "completed" against the user demand they typed — not against
        # the last subtask's auto-generated demand.
        if task.parent_task_id:
            root_task = db.query(Task).filter(Task.id == task.parent_task_id).first()
            if root_task is not None:
                root_task.status = TaskStatus.COMPLETED.value
                if root_task.result is not None:
                    root_task.result.result_data = final_answer
                    root_task.result.sources = final_sources
                    root_task.result.ai_provider = ai_provider
                    # Merge the final history onto the root so the result page
                    # shows the full conversation, not an empty seed.
                    root_history = list(root_task.result.history or [])
                    if not root_history:
                        root_history = [
                            {"role": "user", "message": root_task.query or ""}
                        ]
                    root_history.append(
                        {"role": "assistant", "message": final_answer}
                    )
                    root_task.result.history = root_history
                db.commit()
                logger.info("Closed chain root %s", root_task.id)

        # Standalone tasks (created via /tasks/new with no conversation) have
        # task.conversation_id is None — skip chat-side effects and let the UI
        # fetch the result from /tasks/{id}.
        conv_id = task.conversation_id
        attribution_name = task_result.agent_name
        message = None
        if conv_id is not None:
            # Look up agent_name from the directory if the agent didn't send one
            # (older worker images, or HTTP /task path without metadata).
            if not attribution_name:
                agent_row = (
                    db.query(Agents).filter(Agents.id == task.agent_id).first()
                )
                attribution_name = agent_row.name if agent_row else None

            # Persist attribution alongside the message so the chat history
            # endpoint can return it on reload. Without it, the user
            # navigates back later and every assistant turn shows up as a
            # bare bubble — no attribution chip, no Manager violet styling.
            message = add_messages(
                "assistant",
                final_answer,
                conv_id,
                db,
                agent_id=task.agent_id,
                agent_name=attribution_name,
                skill_used=task_result.skill_used,
                sources=final_sources,
                ai_provider=ai_provider,
            )

        await publish_agent_message(
            chain_root_id,
            conv_id,
            final_answer,
            event_type=TaskEventType.RESULT,
            stage=TaskStage.AGGREGATION if task.parent_task_id else TaskStage.GENERATION,
            agent_id=task.agent_id,
            agent_name=attribution_name,
            skill_used=task_result.skill_used,
            status=TaskStatus.COMPLETED.value,
            route=ROUTE_AGENT,
            message_id=_message_id(message),
            **({"sources": final_sources} if final_sources is not None else {}),
            **({"ai_provider": ai_provider} if ai_provider else {}),
        )
        return {"message": f"Result received from agent {task_result.agent_id}"}
    except HTTPException:
        raise
    except Exception as e:
        TASK_ERRORS.labels(
            agent_id=task_result.agent_id, error_type="processing_error"
        ).inc()
        db.rollback()
        raise HTTPException(
            status_code=500, detail=f"Error processing task result: {str(e)}"
        )


def _sources_of(task_result: TaskResultForm) -> list[dict] | None:
    if task_result.sources is None:
        return None
    return [source.model_dump() for source in task_result.sources]


def _chain_sources(
    db: Session, root_id: str, step_sources: list[dict] | None
) -> list[dict] | None:
    steps = (
        db.query(Task)
        .filter(Task.parent_task_id == root_id)
        .order_by(Task.order.asc(), Task.created_at.asc())
        .all()
    )
    earlier = [getattr(step.result, "sources", None) for step in steps if step.result is not None]
    return merge_sources([*earlier, step_sources])


async def _answer_again(task: Task, task_result: TaskResultForm, db: Session) -> bool:
    if is_final_status(task.status):
        return False
    root = (
        db.query(Task).filter(Task.id == task.parent_task_id).first()
        if task.parent_task_id
        else None
    )
    if root is not None and is_final_status(root.status):
        return False
    plan = retry_plan(
        recall_dispatch(task.id),
        task_result.status,
        task_result.reason,
        root.query if root is not None else None,
    )
    if plan is None:
        return False
    if task.result is not None:
        task.result.history = [
            *(task.result.history or []),
            {
                "role": "assistant",
                "message": task_result.result,
                "status": task_result.status.value,
                "reason": task_result.reason,
                "attempt": plan.attempt - 1,
            },
        ]
    task.claimed_by = None
    task.claim_run = None
    task.started_at = None
    db.commit()
    root_id = task.parent_task_id or task.id
    logger.info(
        "Answer asked for once more",
        task_id=task.id,
        status=task_result.status.value,
        reason=task_result.reason,
        attempt=plan.attempt,
        retrieval_query=plan.payload.get("retrieval_query"),
    )
    await publish_task_status(
        root_id,
        task.conversation_id,
        RETRYING_STATUS,
        stage=TaskStage.RETRIEVAL,
        detail=plan.detail,
        attempt=plan.attempt,
    )
    dispatch = _WorkDispatch(task.agent_id, plan.payload, task.id, root_id, task.conversation_id)
    try:
        if not await _publish_unless_full(db, dispatch):
            task_jobs.submit(task.id, _wait_for_room_job(dispatch))
    except Exception as exc:
        logger.exception("Could not hand task %s to an agent once more", task.id)
        db.rollback()
        detail = exc.detail if isinstance(exc, HTTPException) else str(exc)
        await _fail_task_tree(
            db,
            task,
            f"The orchestrator could not hand this request to an agent: {detail}",
            reason="dispatch_failed",
            agent_id=task.agent_id,
            agent_name=task_result.agent_name,
        )
    return True


def _agent_is_registered(db: Session, agent_id: str) -> bool:
    return db.query(Agents.id).filter(Agents.id == agent_id).first() is not None


def _agent_name(db: Session, agent_id: str | None) -> str | None:
    if not agent_id:
        return None
    agent = db.query(Agents).filter(Agents.id == agent_id).first()
    return agent.name if agent is not None else None


async def _record_agent_failure(
    task: Task, task_result: TaskResultForm, db: Session
) -> dict:
    reason = task_result.reason or "error"
    text = (task_result.result or "").strip() or AGENT_FAILED_TEXT
    reported = await _fail_task_tree(
        db,
        task,
        text,
        reason=reason,
        agent_id=task.agent_id,
        agent_name=task_result.agent_name or _agent_name(db, task.agent_id),
        skill_used=task_result.skill_used,
    )
    TASK_QUEUE_DEPTH.dec()
    TASK_ERRORS.labels(agent_id=task_result.agent_id, error_type=reason).inc()
    log_agent_operation(
        task_result.agent_id,
        "TASK",
        f"Task {task.id} failed ({reason}) peak_rss_mb={peak_rss_mb()}",
    )
    return {
        "message": f"Failure of task {task.id} recorded",
        "reported": reported,
    }


@router.post(
    "/{task_id}/claim",
    summary="Claim a task before running it",
    description=(
        "Called by an agent worker when it takes a task from its work queue, "
        "before it acknowledges the message. The first claim stores the worker "
        "and its run in the task row and marks the task running. The same "
        "claim sent again by the same run is answered 200 again, so a claim "
        "whose answer was lost can be retried; a claim by any other worker or "
        "run, and a claim of a finished, failed or cancelled task, gets 409, so "
        "a task never runs twice. A task whose assigned agent is no longer "
        "registered fails at once and gets 409. Requires the agent's "
        "``X-API-Key`` header."
    ),
    status_code=200,
    tags=["Tasks"],
)
async def claim_task(
    task_id: str,
    claim: TaskClaimForm,
    verified_agent: Annotated[tuple[str, str], Depends(verify_agent_api_key)],
    db: Session = Depends(get_db),
):
    verified_agent_id, _ = verified_agent
    task = db.query(Task).filter(Task.id == task_id).first()
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    if claim.agent_id != task.agent_id:
        raise HTTPException(
            status_code=403,
            detail="agent_id in body must match the task's assigned agent",
        )
    if not agent_may_submit_task_result(verified_agent_id, task.agent_id, db):
        if not _agent_is_registered(db, task.agent_id):
            await _fail_task_tree(
                db,
                task,
                AGENT_UNREGISTERED_TEXT,
                reason=AGENT_UNREGISTERED_REASON,
                agent_id=task.agent_id,
            )
            raise HTTPException(
                status_code=409,
                detail="The task's agent is no longer registered; the task failed",
            )
        raise HTTPException(
            status_code=403,
            detail="Authenticated agent is not allowed to run this task",
        )
    if is_final_status(task.status):
        raise HTTPException(
            status_code=409,
            detail=f"Task is {_task_status_value(task.status)}; it will not run",
        )
    if (task.claimed_by, task.claim_run) == (claim.worker_id, claim.run_id):
        return {"task_id": task_id, "status": TaskStatus.RUNNING.value}
    claimed = (
        db.query(Task)
        .filter(
            Task.id == task_id,
            Task.claimed_by.is_(None),
            Task.status.in_(sorted(IN_PROGRESS_STATUSES)),
        )
        .update(
            {
                Task.claimed_by: claim.worker_id,
                Task.claim_run: claim.run_id,
                Task.started_at: datetime.now(UTC),
                Task.status: TaskStatus.RUNNING.value,
            },
            synchronize_session=False,
        )
    )
    db.commit()
    if not claimed:
        raise HTTPException(status_code=409, detail="Task was already claimed")
    logger.info(
        "Task claimed",
        task_id=task_id,
        worker_id=claim.worker_id,
        run_id=claim.run_id,
    )
    return {"task_id": task_id, "status": TaskStatus.RUNNING.value}


@router.post(
    "/abandoned-claims",
    summary="Fail the tasks an earlier run of a worker left unfinished",
    description=(
        "Called once by an agent worker when it starts, after it registered. "
        "Every task still queued or running that was claimed by the same "
        "worker id under another run id, or claimed by any worker for an "
        "agent that is no longer registered (a recreated container gets a "
        "new host name and replaces its agents when it registers), is marked "
        "failed, with a failed event and a chat message asking the user to "
        "send the request again. Requires the agent's ``X-API-Key`` header."
    ),
    status_code=200,
    tags=["Tasks"],
)
async def fail_abandoned_claims(
    run: WorkerRunForm,
    verified_agent: Annotated[tuple[str, str], Depends(verify_agent_api_key)],
    db: Session = Depends(get_db),
):
    abandoned = (
        db.query(Task)
        .filter(
            Task.claimed_by.is_not(None),
            Task.status.in_(sorted(IN_PROGRESS_STATUSES)),
            or_(
                and_(Task.claimed_by == run.worker_id, Task.claim_run != run.run_id),
                Task.agent_id.not_in(select(Agents.id)),
            ),
        )
        .all()
    )
    failed = [task.id for task in abandoned]
    for task in abandoned:
        await _fail_task_tree(
            db,
            task,
            AGENT_RESTARTED_TEXT,
            reason=AGENT_RESTARTED_REASON,
            agent_id=task.agent_id,
            agent_name=_agent_name(db, task.agent_id),
        )
    if failed:
        logger.warning(
            "Failed the tasks an earlier run of worker %s left unfinished: %s",
            run.worker_id,
            failed,
        )
    return {"failed": failed}


@router.post(
    "/task-step/",
    summary="Submit a thought-process step from agent",
    description=(
        "Receives a coarse phase-boundary event from an agent worker "
        "(retrieval start/end, reasoning start/end, tool invocation, error) "
        "and broadcasts it to the chat WebSocket as a ``task_step`` event "
        "for live UI rendering. Best-effort: failures here never affect the "
        "task-result flow. Requires the agent's ``X-API-Key`` header."
    ),
    status_code=200,
    tags=["Tasks"],
)
async def ingest_task_step(
    step: TaskStepForm,
    verified_agent: Annotated[tuple[str, str], Depends(verify_agent_api_key)],
    db: Session = Depends(get_db),
):
    """Ingest a step event and rebroadcast it over the conversation's WS.

    Steps are stored as events of the root task for 24 h, so a client that
    reconnects can replay them, then broadcast. The endpoint verifies the agent's API key (same auth dependency as
    ``task-result/``) so untrusted clients can't inject "thought" events.

    Args:
        step: The step envelope from the agent worker.
        verified_agent: Authenticated agent ``(id, api_key)``.
        db: DB session, kept available for future persistence.
    """
    verified_agent_id, _ = verified_agent

    if not step.task_id:
        return {"message": "ignored"}

    # Cross-check the body against the task and the authenticated agent so a
    # compromised agent can't squirt fake "thought process" events into
    # another conversation's chat stream.
    broadcast_task_id = step.task_id
    task = db.query(Task).filter(Task.id == step.task_id).first()
    if task is None:
        # Unknown task — silently accept and drop. Avoids tripping older
        # agents that race the task row's INSERT, while still preventing
        # any broadcast to nonexistent conversations.
        logger.debug("Step for unknown task %s ignored", step.task_id)
        return {"message": "ignored"}
    if step.agent_id and step.agent_id != task.agent_id:
        raise HTTPException(
            status_code=403,
            detail="agent_id in step body must match the task's assigned agent",
        )
    if not agent_may_submit_task_result(verified_agent_id, task.agent_id, db):
        raise HTTPException(
            status_code=403,
            detail="Authenticated agent is not allowed to emit steps for this task",
        )
    # Trust the DB's view of the conversation over whatever the agent
    # sent — the agent only forwards what MAS originally dispatched.
    conversation_id = (
        str(task.conversation_id)
        if task.conversation_id is not None
        else None
    )

    # Translate to the chain's ROOT task_id when one exists. The chat
    # frontend keys ``stepsByTaskId`` by the message's task_id, which is
    # the root for multi-agent chains. Without this translation, steps
    # emitted by subtask 2, 3, … would be stored under their own ids and
    # never render in the user message's thought-process card.
    if task.parent_task_id:
        root_task = (
            db.query(Task).filter(Task.id == task.parent_task_id).first()
        )
        if root_task is not None:
            broadcast_task_id = root_task.id

    # Reliably resolve the owning agent's NAME. The worker only forwards an
    # ``agent_id`` (and inconsistently a name), which is why the chat's
    # "which agent is active" label flickers on/off. Look it up from the DB so
    # every step is tagged with the specialist that produced it.
    resolved_agent_name = step.agent_name
    _lookup_id = step.agent_id
    if not _lookup_id and step.task_id:
        _t = db.query(Task).filter(Task.id == step.task_id).first()
        _lookup_id = _t.agent_id if _t else None
    if not resolved_agent_name and _lookup_id:
        from db.models import Agents as _Ag

        _a = db.query(_Ag).filter(_Ag.id == _lookup_id).first()
        if _a:
            resolved_agent_name = _a.name

    payload = {
        # Broadcast under the root task id so the UI groups all subtasks'
        # steps under the single thought-process card pinned to the user's
        # message. Internal step.task_id (subtask) is preserved in metadata
        # for debug/replay paths.
        "task_id": broadcast_task_id,
        "subtask_id": step.task_id,
        "agent_id": step.agent_id,
        "agent_name": resolved_agent_name,
        "step_type": step.step_type,
        "title": step.title,
        "detail": step.detail,
        "timestamp": step.timestamp,
        "metadata": step.metadata or {},
    }
    logger.debug(
        "Task step received task=%s type=%s agent=%s",
        step.task_id,
        step.step_type,
        step.agent_name or step.agent_id,
    )
    await publish_task_step(broadcast_task_id, conversation_id, payload)
    if conversation_id is None:
        return {"message": "no conversation"}
    return {"message": "ok"}


async def _publish_cancellation(task_id: str, db: Session) -> None:
    task = db.query(Task).filter(Task.id == task_id).first()
    if task is None or task.parent_task_id is not None:
        return
    await publish_agent_message(
        task.id,
        task.conversation_id,
        CANCELLED_TASK_TEXT,
        event_type=TaskEventType.ERROR,
        status="cancelled",
        reason="user",
    )


@router.patch(
    "/{task_id}/cancel",
    summary="Cancel a running task (alternate path)",
    description="Same as /task-cancel/{task_id}; provided for API client compatibility.",
    status_code=200,
    tags=["Tasks"],
    dependencies=[Depends(PermissionChecker(Permission.TASK_DELETE))],
    include_in_schema=False,
)
@router.patch(
    "/task-cancel/{task_id}",
    summary="Cancel a running task",
    description="Interrupts a running task by updating its status to CANCELED and sending a high-priority cancellation signal to the assigned agent via RabbitMQ. Allowed for the task's owner, the owner of its conversation, a manager or an admin. Requires TASK_DELETE permission.",
    status_code=200,
    tags=["Tasks"],
    dependencies=[Depends(PermissionChecker(Permission.TASK_DELETE))],
    responses=CANCEL_TASK_RESPONSES,
)
async def cancel_task(
    task_id: str,
    user: Annotated[dict, Depends(PermissionChecker(Permission.TASK_DELETE))],
    db: Session = Depends(get_db),
):
    """Cancel an active task and interrupt its executing agent.

    Marks ``task_id`` CANCELLED, publishes a high-priority interrupt to the
    assigned agent, and writes an audit log entry.

    Raises:
        HTTPException: 401 unauthenticated, 404 task missing, 500 on failure.
    """
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication Failed")
    try:
        if await interrupt_task(task_id, db, user=user):
            log_agent_operation(
                "system",
                "TASK_CANCEL",
                f"User {user.get('username')} canceled task {task_id}",
            )
            await _publish_cancellation(task_id, db)
            return {"message": f"Task {task_id} has been canceled successfully."}
    except HTTPException:
        raise
    except Exception as e:
        TASK_ERRORS.labels(agent_id="system", error_type="cancellation_error").inc()
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error Canceling task: {str(e)}")
