"""Tests for the consolidated analytics overview endpoint."""

from unittest.mock import MagicMock, patch

import pytest

from analytics.routes import _agent_snapshot, overview


def _agent(alive: bool):
    a = MagicMock()
    a.last_heartbeat = None
    a.status = "active" if alive else "inactive"
    return a


def test_agent_snapshot_counts_live_vs_dead():
    db = MagicMock()
    db.query.return_value.all.return_value = [
        _agent(True),
        _agent(True),
        _agent(False),
    ]
    with patch(
        "analytics.routes._is_agent_recently_alive",
        side_effect=lambda a: a.status == "active",
    ):
        snap = _agent_snapshot(db)
    assert snap == {"total": 3, "active": 2, "inactive": 1}


def test_agent_snapshot_empty_directory():
    db = MagicMock()
    db.query.return_value.all.return_value = []
    snap = _agent_snapshot(db)
    assert snap == {"total": 0, "active": 0, "inactive": 0}


def test_agent_snapshot_handles_db_error():
    db = MagicMock()
    db.query.side_effect = RuntimeError("connection lost")
    snap = _agent_snapshot(db)
    # Errors should produce zeros, never crash the dashboard
    assert snap == {"total": 0, "active": 0, "inactive": 0}


@pytest.mark.asyncio
async def test_overview_combines_agents_and_tasks():
    db = MagicMock()
    db.query.return_value.all.return_value = [_agent(True)]

    with patch(
        "analytics.routes._is_agent_recently_alive", return_value=True
    ), patch(
        "analytics.routes.get_task_queue_stats",
        return_value={
            "pending": 1,
            "running": 2,
            "completed": 3,
            "failed": 0,
            "cancelled": 0,
            "timeout": 0,
            "total": 6,
        },
    ):
        result = await overview(user={"role": "admin"}, db=db)

    assert result["agents"] == {"total": 1, "active": 1, "inactive": 0}
    assert result["tasks"]["total"] == 6
    assert "generated_at" in result
