"""Agent FastAPI surface tests (hermetic).

Routes under test (``src/services/agent/app/agent_server/server.py``):

* ``GET  /capabilities`` → 200, dict with 7 fields
* ``POST /task``         → 200 on success, 422 on missing body (Pydantic)
* ``GET  /metrics``      → 200 (Prometheus client mount)
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from agent_server.server import app  # noqa: PLC0415

    return TestClient(app)


class TestHealth:
    def test_health_answers_without_credentials(self, client):
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json()["status"] == "healthy"
        assert r.json()["service"] == "agent"

    def test_health_loads_no_model_and_calls_nothing_downstream(self, client):
        from agent_server import server  # noqa: PLC0415

        with (
            patch.object(server.decision_agent, "_ensure_causal_loaded") as ensure_loaded,
            patch.object(server.decision_agent, "decide") as decide,
            patch.object(server.requests, "get") as http_get,
            patch.object(server.requests, "post") as http_post,
        ):
            r = client.get("/health")

        assert r.status_code == 200
        ensure_loaded.assert_not_called()
        decide.assert_not_called()
        http_get.assert_not_called()
        http_post.assert_not_called()


class TestCapabilities:
    def test_returns_200_with_agent_metadata(self, client):
        r = client.get("/capabilities")
        assert r.status_code == 200
        body = r.json()
        for key in (
            "agent_id",
            "work_queue",
            "agent_name",
            "skills",
            "capabilities",
            "supports_delegation",
            "max_delegation_depth",
        ):
            assert key in body
        assert body["supports_delegation"] is True


class TestMetrics:
    def test_metrics_endpoint_serves_prometheus(self, client):
        r = client.get("/metrics")
        assert r.status_code == 200


class TestTaskHTTPEntry:
    def test_post_task_with_empty_body_returns_422(self, client):
        r = client.post("/task", json={})
        assert r.status_code == 422

    def test_post_task_with_no_body_returns_422(self, client):
        r = client.post("/task")
        assert r.status_code == 422
