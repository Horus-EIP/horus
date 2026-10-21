"""Consolidated analytics endpoints.

A single ``/analytics/overview`` call returns the agent-directory and
task-queue snapshots together so the dashboard can refresh with one round-
trip instead of fanning out. Counts are computed from the same sources the
existing per-domain endpoints already use, so behaviour is consistent.
"""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from agents.registry_tool_functions import _is_agent_recently_alive
from auth.auth_tool_functions import PermissionChecker
from auth.permissions import Permission
from core.logger import get_logger
from db.dependency import get_db
from db.models import Agents
from tasks.routes import get_task_queue_stats

logger = get_logger("analytics_routes")

router = APIRouter(prefix="/analytics", tags=["Analytics"])


def _agent_snapshot(db: Session) -> dict:
    """Return ``{total, active, inactive}`` counts from the agent directory.

    "Active" follows the same heartbeat-recency rule used by the dispatcher,
    so the dashboard's Active Agents card matches the routing layer's view of
    liveness.
    """
    total = 0
    active = 0
    try:
        rows = db.query(Agents).all()
        total = len(rows)
        for row in rows:
            if _is_agent_recently_alive(row):
                active += 1
    except Exception as exc:
        logger.error(f"Failed to compute agent snapshot: {exc}", exc_info=True)
    return {"total": total, "active": active, "inactive": total - active}


@router.get(
    "/overview",
    summary="Consolidated analytics overview",
    description=(
        "Returns one snapshot of the orchestrator's directory and queue: "
        "agent counts (total/active/inactive) plus the task-queue stats. "
        "Used by the dashboard to refresh with a single round-trip instead "
        "of fanning out across `/agents/details` + `/tasks/stats/queue`."
    ),
    status_code=200,
    dependencies=[Depends(PermissionChecker(Permission.VIEW_ANALYTICS))],
)
async def overview(
    user: Annotated[dict, Depends(PermissionChecker(Permission.VIEW_ANALYTICS))],
    db: Session = Depends(get_db),
):
    """Return the merged analytics snapshot."""
    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "agents": _agent_snapshot(db),
        "tasks": get_task_queue_stats(db, user),
    }
    logger.info("Analytics overview retrieved", payload=payload)
    return payload
