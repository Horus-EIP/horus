"""HTTP routes for task orchestration.

Task creation, status queries, cancellation, and result ingestion from
agents. See ``docs/architecture.md`` for the task lifecycle,
payload shapes, and error codes.
"""

import json
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from agents.registry_tool_functions import create_agent
from auth.auth_tool_functions import PermissionChecker, verify_agent_api_key
from auth.permissions import Permission
from chat.chat_tool_functions import send_messages_via_websockets, send_task_step_via_websockets
from conversations.conversation_tool_functions import add_messages
from core.logger import get_logger, log_agent_operation
from core.metrics import TASK_ERRORS, TASK_QUEUE_DEPTH
from core.rabbitmq_tool import rabbitmq_instance
from core.skill_cache import rank_skills
from core.work_queues import agent_may_submit_task_result, resolve_work_queue_for_agent_id
from db.database import get_db
from db.models import Agents, Task, TaskResult
from db.models.agent_types import AgentTypes
from schemas.schemas import TaskForm, TaskResultForm, TaskStepForm
from tasks.decomposition import get_manager_agent, manager_announce_plan, manager_review_step
from tasks.openapi_docs import (
    CANCEL_TASK_RESPONSES,
    CREATE_TASK_OPENAPI_EXTRA,
    CREATE_TASK_RESPONSES,
    QUEUE_STATS_RESPONSES,
    SHARE_RESULT_OPENAPI_EXTRA,
    SHARE_RESULT_RESPONSES,
)
from tasks.status import TaskStatus
from tasks.task_tool_functions import (
    aggregate_results,
    decompose_task,
    insert_new_task,
    interrupt_task,
    select_agent_by_mode,
    select_agent_for_task,
    validating_task_results,
)

logger = get_logger("task_routes")

router = APIRouter(prefix="/tasks", tags=["Tasks"])


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


def _publish_task_to_work_queue(
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
    rabbitmq_instance.publish(queue, json.dumps(payload))


async def _broadcast_manager_message(
    conversation_id: int | str | None,
    text: str,
    db: Session,
    skill_used: str = "orchestration",
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
    add_messages(
        "assistant",
        text,
        int(conversation_id),
        db,
        agent_id=_agent_id,
        agent_name=_agent_name,
        skill_used=skill_used,
    )
    await send_messages_via_websockets(
        str(conversation_id),
        text,
        agent_id=_agent_id,
        agent_name=_agent_name,
        skill_used=skill_used,
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


def _create_chain_root(
    user_demand: str,
    conversation_id: int | None,
    db: Session,
) -> "Task":
    """Create the Manager-owned root task that holds a multi-agent chain.

    The root carries the user's original demand verbatim in ``query``, is
    attributed to the Manager agent (so the UI surfaces who orchestrated the
    work), and starts in ``RUNNING`` until the last sibling subtask completes
    and the aggregated result is written back into it. All chained subtasks
    of this user demand share ``parent_task_id == root.id``.

    Returns ``None`` if the Manager agent is missing from the directory —
    callers should treat that as "skip the tree refactor, fall back to a
    linked-list chain for this dispatch" rather than crashing.
    """
    from db.models import Agents as _Agents

    manager = (
        db.query(_Agents).filter(_Agents.name == "Manager").first()
    )
    if manager is None:
        logger.warning(
            "_create_chain_root: Manager agent not found in directory; "
            "skipping root creation. Run migration b5d2e1f3a9c7 and restart MAS "
            "so the seed inserts the Manager row."
        )
        return None
    manager_id = manager.id

    # Defensive: log the exact demand we're about to write so it's easy to
    # diff against `task.demand` in the API request when something looks off.
    preview = (user_demand or "")[:120]
    logger.info(
        "Creating chain root: agent_id=%s conv=%s demand_preview=%r",
        manager_id,
        conversation_id,
        preview,
    )

    # Build a one-line "user role" history entry so downstream paths that
    # read history (e.g. ``aggregate_results``) see the original demand.
    history = [{"role": "user", "message": user_demand}]
    root_id = insert_new_task(
        conversation_id,
        manager_id,
        user_demand,
        history,
        [],  # planner output lives on subtasks, not root
        db,
    )
    root = db.query(Task).filter(Task.id == root_id).first()
    if root is not None:
        root.status = TaskStatus.RUNNING.value
        root.order = 0
        db.commit()
        logger.info(
            "Chain root created: id=%s query=%r",
            root.id,
            (root.query or "")[:120],
        )
    return root


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
        files.append({"source": "knowledge_store", "filename": name})

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
    rows = db.query(Task.status, func.count(Task.id)).group_by(Task.status).all()
    counts = {
        "pending": 0,
        "running": 0,
        "completed": 0,
        "failed": 0,
        "cancelled": 0,
        "timeout": 0,
    }
    for status, n in rows:
        sv = status.value if isinstance(status, TaskStatus) else str(status)
        key = {
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
        "shows one row per original demand, not per chain step. Requires "
        "TASK_READ permission."
    ),
    status_code=200,
    dependencies=[Depends(PermissionChecker(Permission.TASK_READ))],
)
def list_tasks(db: Session = Depends(get_db)):
    # Tree model: each multi-agent chain is one root Task with N subtask
    # children. The list view wants just the roots — clicking through opens
    # the detail page which shows the chain underneath.
    tasks = db.query(Task).filter(Task.parent_task_id.is_(None)).all()
    logger.info("Listing root tasks", count=len(tasks))
    return tasks


@router.get(
    "/stats/queue",
    summary="Get task queue statistics",
    description="Retrieve current statistics about the task queue including pending, running, and completed tasks. Requires VIEW_ANALYTICS permission.",
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


@router.get(
    "/conversation/{conversation_id}/running",
    summary="List in-flight root tasks for a conversation",
    description=(
        "Returns root-level tasks in this conversation whose status is not "
        "yet terminal (RUNNING or PENDING). The chat page calls this on "
        "mount so a user who navigates away and back still sees the "
        "in-progress spinner + working-agents bar instead of a stale chat "
        "that looks finished. Subtasks (rows with parent_task_id) are "
        "excluded — only the user-visible root surfaces."
    ),
    status_code=200,
    dependencies=[Depends(PermissionChecker(Permission.TASK_READ))],
)
def list_running_tasks_for_conversation(
    conversation_id: int, db: Session = Depends(get_db)
):
    rows = (
        db.query(Task)
        .filter(
            Task.conversation_id == conversation_id,
            Task.parent_task_id.is_(None),
            Task.status.in_([TaskStatus.RUNNING.value, TaskStatus.PENDING.value]),
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
    description="Returns a task, optional result, and child subtasks. Requires TASK_READ.",
    status_code=200,
    dependencies=[Depends(PermissionChecker(Permission.TASK_READ))],
)
def get_task_detail(task_id: str, db: Session = Depends(get_db)):
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
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
        }
        for c in children
    ]

    return {
        "task_id": task.id,
        "status": _task_status_value(task.status),
        "agent_id": task.agent_id,
        "conversation_id": task.conversation_id,
        "query": task.query,
        "created_at": task.created_at.isoformat() if task.created_at else "",
        "result": result_str,
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


@router.post("/new_task", include_in_schema=False)
@router.post(
    "/new_task/",
    summary="Create and dispatch a new task",
    description="Attribute a task to the best agent based on the skills required. Publishes the request to the RabbitMQ queue and returns confirmation with task and conversation IDs. Requires TASK_CREATE permission.",
    status_code=200,
    tags=["Tasks"],
    dependencies=[Depends(PermissionChecker(Permission.TASK_CREATE))],
    responses=CREATE_TASK_RESPONSES,
    openapi_extra=CREATE_TASK_OPENAPI_EXTRA,
)
async def create_new_task(
    task: TaskForm,
    user: Annotated[dict, Depends(PermissionChecker(Permission.TASK_CREATE))],
    db: Session = Depends(get_db),
):
    """Create and dispatch a new task.

    Selects an agent for ``task.demand``, either returns a direct answer or
    creates a ``Task`` row and publishes to RabbitMQ.

    Raises:
        HTTPException: 401 if unauthenticated, 500 on DB/messaging failure.
    """
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication Failed")

    logger.info(
        "Starting agent selection process for new task",
        demand=task.demand[:50],
        conversation_id=task.conversation_id,
        mode=task.mode or "auto",
        explicit_agent_id=task.agent_id,
    )

    # Force-decomposition mode: skip the single-agent router/skill/auto-create
    # path entirely and jump straight to the planner. Without this short-cut,
    # cross-domain demands almost always land on a single specialist (or get
    # an auto-created Specialist-Knowledge-Retriever) because the router or
    # skill-match catches them before decomposition can fire. With ``mode=
    # "decompose"`` we let the planner break the demand into per-domain
    # subtasks and dispatch each to the matching agent.
    if task.mode == "decompose":
        logger.info("Force-decompose mode: jumping straight to planner")
        first_action, actions_list = await run_in_threadpool(
            decompose_task, task.demand, db
        )
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
            if task.conversation_id is not None:
                add_messages("assistant", fallback, task.conversation_id, db)
                await send_messages_via_websockets(
                    str(task.conversation_id), fallback
                )
            return {"message": fallback}

        agent_id, user_demand = first_action

        # Tree model: every subtask of this user demand is a child of one
        # Manager-owned root task. ``/tasks/{root.id}`` is the canonical entry
        # point users navigate to — they see the whole multi-agent
        # collaboration in one place, not N separate Task rows in their list.
        root = _create_chain_root(task.demand, task.conversation_id, db)
        if root is None:
            logger.warning(
                "Force-decompose: Manager missing, falling back to linked-list chain"
            )
        history = [{"role": "user", "message": task.demand}]
        task_id = insert_new_task(
            task.conversation_id, agent_id, user_demand, history, actions_list, db
        )
        subtask_row = db.query(Task).filter(Task.id == task_id).first()
        if subtask_row is not None and root is not None:
            subtask_row.parent_task_id = root.id
            subtask_row.order = 1
            db.commit()
        files_payload = _build_files_payload(task)
        decomp_payload = {
            "conversation_id": task.conversation_id,
            "task_id": task_id,
            "demand": user_demand,
            "skill_used": (
                task.skills_required[0] if task.skills_required else None
            ),
            "files": files_payload,
        }
        _publish_task_to_work_queue(db, agent_id, decomp_payload)
        TASK_QUEUE_DEPTH.inc()
        log_agent_operation(
            agent_id,
            "TASK",
            f"Force-decomposed task {task_id} under root {root.id if root else '?'}: {task.demand[:50]}...",
        )
        if task.conversation_id is not None:
            add_messages("user", task.demand, task.conversation_id, db)
            # Manager announces the plan to chat BEFORE the first specialist
            # runs, so the user sees the orchestration. Synchronous: the LLM
            # call is small (max 256 tokens on the router model) and the
            # user is already waiting on the first specialist anyway.
            full_plan = [(agent_id, user_demand)] + list(actions_list)
            announcement = await run_in_threadpool(
                manager_announce_plan, task.demand, full_plan, db
            )
            await _broadcast_manager_message(
                task.conversation_id, announcement, db, skill_used="planning"
            )
        # Return the ROOT id — that's the page the user should land on. They
        # see the whole chain (all subtasks) under one task, not just step 1.
        return {
            "message": (
                f"Task '{task.demand}' decomposed into "
                f"{len(actions_list) + 1} subtask(s); first dispatched to agent {agent_id}"
            ),
            "conversation_id": task.conversation_id,
            "task_id": root.id if root else task_id,
        }

    # 1. Selection Phase
    # Try the explicit-mode dispatcher first; if it returns no agent (e.g. mode=auto
    # or unresolvable) fall through to the LLM router. This keeps the legacy chat
    # path (no mode field) working untouched.
    agent_id, user_demand, direct_response, future_actions = select_agent_by_mode(
        task.demand, task.skills_required, task.mode, task.agent_id, db
    )
    if not agent_id and not direct_response:
        agent_id, user_demand, direct_response, future_actions = (
            select_agent_for_task(task.demand, db)
        )

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
                new_id, new_key = create_agent(
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

    # If the user attached files, skip the direct-LLM-answer path so the
    # worker actually gets to read the attachments. The orchestrator-side LLM
    # doesn't see file content, so its "direct answer" would be misleading.
    # The downstream decomposition fallback will pick an agent if none was
    # chosen above.
    has_attachments = bool(task.attached_files) or bool(task.inline_files)
    if has_attachments and direct_response:
        logger.info(
            "Discarding direct-answer because the task has attached files; "
            "forcing agent dispatch so files are processed."
        )
        direct_response = None

    # 2. Direct Answer Handling
    if direct_response:
        if task.conversation_id is not None:
            add_messages("user", task.demand, task.conversation_id, db)
            add_messages("assistant", direct_response, task.conversation_id, db)
            # Push to chat WebSocket clients (same as agent task-result path); otherwise UI stays "loading".
            await send_messages_via_websockets(str(task.conversation_id), direct_response)
        # We don't create a task, just return the answer
        return {
            "message": "Processing complete",
            "conversation_id": task.conversation_id,
            "result": direct_response,
        }

    # 3. Single Agent Assignment
    if agent_id:
        logger.info("Agent selected for task", agent_id=agent_id)

        history = [{"role": "user", "message": task.demand}]

        # Multi-step plan from the inline decomposer → spin up a Manager-owned
        # root and parent every subtask under it. Single-agent dispatch keeps
        # the legacy one-row shape (no root, the task IS the root).
        root_task = None
        if future_actions:
            root_task = _create_chain_root(task.demand, task.conversation_id, db)

        task_id = insert_new_task(
            task.conversation_id, agent_id, user_demand, history, future_actions, db
        )

        if not task_id:
            raise HTTPException(status_code=500, detail="Failed to create task")

        if root_task is not None:
            subtask_row = db.query(Task).filter(Task.id == task_id).first()
            if subtask_row is not None:
                subtask_row.parent_task_id = root_task.id
                subtask_row.order = 1
                db.commit()

        files_payload = _build_files_payload(task)
        dispatch_payload = {
            "conversation_id": task.conversation_id,
            "task_id": task_id,
            "demand": user_demand,
            "skill_used": (
                task.skills_required[0] if task.skills_required else None
            ),
            "files": files_payload,
        }
        # Auto-created specialist: the worker doesn't know this identity yet,
        # so we ship its credentials inside the task message. The worker reads
        # them, adds the profile to its registry, and authenticates as the
        # new agent for the result POST (and from then on for heartbeats).
        if auto_created_api_key:
            dispatch_payload["assigned_agent_api_key"] = auto_created_api_key
            dispatch_payload["assigned_agent_name"] = auto_created_name
            dispatch_payload["assigned_agent_skills"] = task.skills_required or []
            dispatch_payload["assigned_agent_type"] = "general"
        _publish_task_to_work_queue(db, agent_id, dispatch_payload)
        TASK_QUEUE_DEPTH.inc()
        log_agent_operation(
            agent_id, "TASK", f"Assigned task {task_id}: {task.demand[:50]}..."
        )

        if task.conversation_id is not None:
            add_messages("user", task.demand, task.conversation_id, db)
            # When ``select_agent_for_task`` ran inline decomposition, it
            # returned the first agent + the rest of the chain in
            # ``future_actions``. Surface the Manager's plan to chat so the
            # user sees the orchestration, not just the eventual final answer.
            if future_actions:
                full_plan = [(agent_id, user_demand)] + list(future_actions)
                announcement = await run_in_threadpool(
                    manager_announce_plan, task.demand, full_plan, db
                )
                await _broadcast_manager_message(
                    task.conversation_id, announcement, db, skill_used="planning"
                )
        # Return the root id when a chain was set up (so the UI lands on the
        # task tree page), otherwise return the single-agent task id verbatim.
        return {
            "message": f"Task '{task.demand}' assigned to agent {agent_id}",
            "conversation_id": task.conversation_id,
            "task_id": root_task.id if root_task is not None else task_id,
        }

    # 4. Decomposition Fallback
    logger.info(
        "No single agent found or COMPLEX_TASK classified. Attempting decomposition."
    )

    first_action, actions_list = await run_in_threadpool(
        decompose_task, task.demand, db
    )

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
        if task.conversation_id is not None:
            add_messages("assistant", fallback, task.conversation_id, db)
            await send_messages_via_websockets(str(task.conversation_id), fallback)
        return {"message": fallback}

    agent_id, user_demand = first_action

    history = [{"role": "user", "message": task.demand}]

    task_id = insert_new_task(
        task.conversation_id, agent_id, user_demand, history, actions_list, db
    )
    files_payload = _build_files_payload(task)
    decomp_payload = {
        "conversation_id": task.conversation_id,
        "task_id": task_id,
        "demand": user_demand,
        "skill_used": (
            task.skills_required[0] if task.skills_required else None
        ),
        "files": files_payload,
    }
    if auto_created_api_key:
        decomp_payload["assigned_agent_api_key"] = auto_created_api_key
        decomp_payload["assigned_agent_name"] = auto_created_name
        decomp_payload["assigned_agent_skills"] = task.skills_required or []
        decomp_payload["assigned_agent_type"] = "general"
    _publish_task_to_work_queue(db, agent_id, decomp_payload)

    TASK_QUEUE_DEPTH.inc()
    log_agent_operation(
        agent_id, "TASK", f"Assigned task {task_id}: {task.demand[:50]}..."
    )

    if task.conversation_id is not None:
        add_messages("user", task.demand, task.conversation_id, db)
    return {
        "message": f"Task '{task.demand}' decomposed and assigned to agent {agent_id}",
        "conversation_id": task.conversation_id,
        "task_id": task_id,
    }


@router.post(
    "/task-result/",
    summary="Submit task result from agent",
    description="Receive the result from an agent, add to conversation history, distribute via WebSocket. Handles subtasks and future actions if defined. Requires TASK_EXECUTE permission. Requires 'X-API-Key' and 'Agent-ID' headers for authentication.",
    status_code=200,
    tags=["Tasks"],
    dependencies=[Depends(verify_agent_api_key)],
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

    try:
        validating_task_results(task_result.task_id, task_result.result, db)
        task = db.query(Task).filter(Task.id == task_result.task_id).first()
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        current_task_result = task.result
        if not current_task_result:
            raise HTTPException(status_code=404, detail="TaskResult not found")

        action_list = current_task_result.future_actions or []
        history = current_task_result.history or []

        task.status = TaskStatus.COMPLETED.value

        history.append({"role": "assistant", "message": task_result.result})

        current_task_result.result_data = task_result.result
        current_task_result.history = history
        db.commit()

        TASK_QUEUE_DEPTH.dec()
        log_agent_operation(
            task_result.agent_id, "TASK", f"Completed task {task_result.task_id}"
        )

        if len(action_list) > 0:
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
                    )
                action_list = []
                # Persist the truncated action list so any subsequent inspection
                # of this task's `future_actions` reflects the Manager's decision.
                current_task_result.future_actions = []
                db.commit()
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

            _publish_task_to_work_queue(
                db,
                new_agent,
                {
                    "conversation_id": task.conversation_id,
                    "task_id": new_subtask_id,
                    "demand": new_action_context,
                },
            )
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
                    task.conversation_id, progress_text, db, skill_used="orchestration"
                )

            return {"message": f"Result received from agent {task_result.agent_id}"}

        try:
            final_answer = aggregate_results(history, task_result.result)
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
        if conv_id is not None:
            # Look up agent_name from the directory if the agent didn't send one
            # (older worker images, or HTTP /task path without metadata).
            attribution_name = task_result.agent_name
            if not attribution_name:
                agent_row = (
                    db.query(Agents).filter(Agents.id == task.agent_id).first()
                )
                attribution_name = agent_row.name if agent_row else None

            # Persist attribution alongside the message so the chat history
            # endpoint can return it on reload. Without it, the user
            # navigates back later and every assistant turn shows up as a
            # bare bubble — no attribution chip, no Manager violet styling.
            add_messages(
                "assistant",
                final_answer,
                conv_id,
                db,
                agent_id=task.agent_id,
                agent_name=attribution_name,
                skill_used=task_result.skill_used,
            )

            await send_messages_via_websockets(
                str(conv_id),
                final_answer,
                agent_id=task.agent_id,
                agent_name=attribution_name,
                skill_used=task_result.skill_used,
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
    dependencies=[Depends(verify_agent_api_key)],
)
async def ingest_task_step(
    step: TaskStepForm,
    verified_agent: Annotated[tuple[str, str], Depends(verify_agent_api_key)],
    db: Session = Depends(get_db),
):
    """Ingest a step event and rebroadcast it over the conversation's WS.

    Steps are not persisted — they're a fire-and-forget telemetry channel.
    The endpoint verifies the agent's API key (same auth dependency as
    ``task-result/``) so untrusted clients can't inject "thought" events.

    Args:
        step: The step envelope from the agent worker.
        verified_agent: Authenticated agent ``(id, api_key)``.
        db: DB session, kept available for future persistence.
    """
    verified_agent_id, _ = verified_agent

    # Cross-check the body against the task and the authenticated agent so a
    # compromised agent can't squirt fake "thought process" events into
    # another conversation's chat stream.
    conversation_id = step.conversation_id
    broadcast_task_id = step.task_id
    if step.task_id:
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

    if conversation_id is None:
        # Standalone task with no chat — nothing to broadcast.
        return {"message": "no conversation"}

    payload = {
        # Broadcast under the root task id so the UI groups all subtasks'
        # steps under the single thought-process card pinned to the user's
        # message. Internal step.task_id (subtask) is preserved in metadata
        # for debug/replay paths.
        "task_id": broadcast_task_id,
        "subtask_id": step.task_id,
        "agent_id": step.agent_id,
        "agent_name": step.agent_name,
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
    await send_task_step_via_websockets(conversation_id, payload)
    return {"message": "ok"}


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
    description="Interrupts a running task by updating its status to CANCELED and sending a high-priority cancellation signal to the assigned agent via RabbitMQ. Requires TASK_DELETE permission.",
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
        if interrupt_task(task_id, db):
            log_agent_operation(
                "system",
                "TASK_CANCEL",
                f"User {user.get('username')} canceled task {task_id}",
            )
            return {"message": f"Task {task_id} has been canceled successfully."}
    except HTTPException:
        raise
    except Exception as e:
        TASK_ERRORS.labels(agent_id="system", error_type="cancellation_error").inc()
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error Canceling task: {str(e)}")
