"""Analytics route contract tests (hermetic).

Route under test (``src/services/mas/analytics/routes.py``):

* ``GET /analytics/overview`` → 200 (admin/manager/user have VIEW_ANALYTICS),
                                 403 (system has no VIEW_ANALYTICS).

Replaces: tests/mas/test_analytics_routes.py.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from analytics.routes import router
from auth.auth_tool_functions import get_current_user
from db.database import get_db
from db.models import Conversations, Task
from tasks.status import TaskStatus


def _overview_client(db, user):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app)


@patch("analytics.routes.get_task_queue_stats", return_value={"queued": 0, "running": 0})
def test_admin_can_view_overview(_stats, make_client, mock_db, as_admin):
    mock_db.query.return_value.all.return_value = []
    client = make_client(router, current_user=as_admin)
    r = client.get("/analytics/overview")
    assert r.status_code == 200
    body = r.json()
    assert "agents" in body
    assert "tasks" in body


@patch("analytics.routes.get_task_queue_stats", return_value={"queued": 0, "running": 0})
def test_manager_can_view_overview(_stats, make_client, mock_db, as_manager):
    mock_db.query.return_value.all.return_value = []
    client = make_client(router, current_user=as_manager)
    r = client.get("/analytics/overview")
    assert r.status_code == 200


@patch("analytics.routes.get_task_queue_stats", return_value={"queued": 0, "running": 0})
def test_user_can_view_overview(_stats, make_client, mock_db, as_user):
    """User has VIEW_ANALYTICS per permissions.py (line 74)."""
    mock_db.query.return_value.all.return_value = []
    client = make_client(router, current_user=as_user)
    r = client.get("/analytics/overview")
    assert r.status_code == 200


def test_unauthenticated_caller_is_rejected(make_client, mock_db):
    client = make_client(router, current_user=None)
    assert client.get("/analytics/overview").status_code == 401


@pytest.mark.parametrize(
    ("user", "expected_total", "expected_running", "expected_completed"),
    [
        ({"id": 3, "username": "user", "role": "user"}, 3, 2, 1),
        ({"id": 2, "username": "manager", "role": "manager"}, 4, 3, 1),
        ({"id": 1, "username": "admin", "role": "admin"}, 4, 3, 1),
    ],
    ids=["user-sees-own", "manager-sees-all", "admin-sees-all"],
)
def test_overview_task_counts_follow_task_list_visibility(
    routing_db, user, expected_total, expected_running, expected_completed
):
    routing_db.add(Conversations(id=8, owner_username="other", name="Other"))
    routing_db.add_all(
        [
            Task(
                id="mine",
                agent_id="manager",
                status=TaskStatus.RUNNING.value,
                query="My task",
                conversation_id=7,
                owner_username="user",
            ),
            Task(
                id="via-conversation",
                agent_id="manager",
                status=TaskStatus.COMPLETED.value,
                query="Task in my conversation",
                conversation_id=7,
            ),
            Task(
                id="theirs",
                agent_id="manager",
                status=TaskStatus.RUNNING.value,
                query="Another user's task",
                conversation_id=8,
                owner_username="other",
            ),
            Task(
                id="standalone",
                agent_id="manager",
                status=TaskStatus.RUNNING.value,
                query="Standalone task",
                owner_username="user",
            ),
            Task(
                id="subtask",
                agent_id="manager",
                status=TaskStatus.RUNNING.value,
                query="Subtask",
                parent_task_id="standalone",
            ),
        ]
    )
    routing_db.commit()

    with _overview_client(routing_db, user) as client:
        response = client.get("/analytics/overview")

    assert response.status_code == 200
    payload = response.json()
    assert payload["agents"] == {"total": 0, "active": 0, "inactive": 0}
    assert payload["tasks"]["total"] == expected_total
    assert payload["tasks"]["running"] == expected_running
    assert payload["tasks"]["completed"] == expected_completed
