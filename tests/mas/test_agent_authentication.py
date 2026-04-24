from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from agents.routes import router as agents_router
from auth.auth_tool_functions import get_current_user, verify_agent_api_key
from db.database import get_db
from tasks.routes import router as tasks_router

# Setup App
app = FastAPI()
app.include_router(agents_router)
app.include_router(tasks_router)

client = TestClient(app)


class TestAgentAuthentication:

    @pytest.fixture(autouse=True)
    def setup_dependencies(self):
        """Override dependencies for all tests"""
        # Mock User Auth
        app.dependency_overrides[get_current_user] = lambda: {
            "username": "admin",
            "role": "admin",
        }

        # Mock DB
        self.mock_session = MagicMock(spec=Session)
        app.dependency_overrides[get_db] = lambda: self.mock_session

        yield

        app.dependency_overrides = {}

    def test_heartbeat_missing_auth(self):
        """Test heartbeat without API key headers"""
        # Ensure verify_agent_api_key is NOT overridden for this test
        if verify_agent_api_key in app.dependency_overrides:
            del app.dependency_overrides[verify_agent_api_key]

        # Re-apply get_current_user and get_db (autouse fixture handles it, but just in case)
        app.dependency_overrides[get_current_user] = lambda: {
            "username": "admin",
            "role": "admin",
        }
        app.dependency_overrides[get_db] = lambda: self.mock_session

        response = client.post("/agents/heartbeat/some-uuid")

        # Expect 401 because authentication is missing (or 403 depending on FastAPI version/config)
        assert response.status_code in [401, 403]

    @patch("agents.routes.update_alive_agent_status")
    def test_heartbeat_success(self, mock_update):
        """Test heartbeat with valid authentication"""
        agent_id = "test-agent-id"
        api_key = "test-api-key"

        # Mock the verification dependency to return success
        app.dependency_overrides[verify_agent_api_key] = lambda: (agent_id, api_key)

        mock_update.return_value = True

        response = client.post(
            f"/agents/heartbeat/{agent_id}",
            headers={"X-API-Key": api_key, "Agent-ID": agent_id},
        )

        assert response.status_code == 200
        assert "Heartbeat received" in response.json()["message"]

    def test_heartbeat_id_mismatch(self):
        """Test heartbeat where header Agent-ID matches key but URL agent_id is different"""
        agent_id_header = "agent-1"
        agent_id_url = "agent-2"

        # Mock verification saying the headers are valid for agent-1
        app.dependency_overrides[verify_agent_api_key] = lambda: (
            agent_id_header,
            "key",
        )

        response = client.post(
            f"/agents/heartbeat/{agent_id_url}",
            headers={"X-API-Key": "key", "Agent-ID": agent_id_header},
        )

        assert response.status_code == 403
        assert "Agent ID mismatch" in response.json()["detail"]

    @patch("tasks.routes.validating_task_results")
    def test_task_result_auth_success(self, mock_validate):
        """Test task result submission with valid auth"""
        agent_id = "agent-1"

        app.dependency_overrides[verify_agent_api_key] = lambda: (agent_id, "key")

        # Mock DB queries for task update
        mock_task = MagicMock()
        mock_task.agent_id = agent_id
        mock_task.result = MagicMock()
        mock_task.result.future_actions = []

        # Setup the mock session to return our mock task
        # db.query(Task).filter(...).first()
        self.mock_session.query.return_value.filter.return_value.first.return_value = (
            mock_task
        )

        response = client.post(
            "/tasks/task-result/",
            json={
                "task_id": "task-1",
                "result": "done",
                "conversation_id": "conv-1",
                "agent_id": agent_id,
            },
        )

        assert response.status_code == 200

    @patch("tasks.routes.agent_may_submit_task_result", return_value=False)
    def test_task_result_agent_mismatch(self, _mock_may):
        """Pool peer cannot submit if not same assignee and not same specialization."""
        auth_agent_id = "agent-real"
        payload_agent_id = "agent-fake"

        app.dependency_overrides[verify_agent_api_key] = lambda: (auth_agent_id, "key")

        mock_task = MagicMock()
        mock_task.agent_id = payload_agent_id
        self.mock_session.query.return_value.filter.return_value.first.return_value = (
            mock_task
        )

        response = client.post(
            "/tasks/task-result/",
            json={
                "task_id": "task-1",
                "result": "done",
                "conversation_id": "conv-1",
                "agent_id": payload_agent_id,
            },
        )

        assert response.status_code == 403
        assert "not allowed to complete this task" in response.json()["detail"]
