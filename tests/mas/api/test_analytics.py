"""Analytics route contract tests (hermetic).

Route under test (``src/services/mas/analytics/routes.py``):

* ``GET /analytics/overview`` → 200 (admin/manager/user have VIEW_ANALYTICS),
                                 403 (system has no VIEW_ANALYTICS).

Replaces: tests/mas/test_analytics_routes.py.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from analytics.routes import router


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
