from typing import Annotated
from unittest.mock import MagicMock, patch

import pytest
from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

# Import router from correct module path
# Running from src/services/mas, so 'agents.routes' works
from agents.routes import router
from auth.auth_tool_functions import (PermissionChecker, get_current_user,
                                      verify_agent_api_key)
from auth.permissions import Permission

app = FastAPI()
app.include_router(router)

client = TestClient(app)


class TestAgentsRoutesCoverage:

    @patch("agents.routes.get_db")
    @patch("agents.routes.get_agent_id")
    @patch("agents.routes.create_agent")
    @patch("agents.routes.rabbitmq_instance")
    def test_handle_agent_creation_success(
        self, mock_rabbitmq, mock_create_agent, mock_get_agent_id, mock_get_db
    ):
        # Allow access
        app.dependency_overrides[PermissionChecker(Permission.AGENT_CREATE)] = lambda: {
            "username": "admin",
            "role": "admin",
        }

        mock_get_agent_id.return_value = None
        mock_create_agent.return_value = ("agent-uuid", "test-api-key")

        response = client.post(
            "/agents/register",
            json={
                "name": "NewAgent",
                "skills": ["skill1"],
                "description": "A new agent",
            },
        )

        assert response.status_code == 200
        assert response.json() == {
            "message": "agent with name NewAgent successfully created",
            "agent_id": "agent-uuid",
            "api_key": "test-api-key",
        }
        mock_rabbitmq.create_queue.assert_called_once_with("agent-uuid")

    @patch("agents.routes.get_db")
    def test_handle_agent_creation_no_user(self, mock_get_db):
        # Simulate unauthorized (user is None)
        app.dependency_overrides[PermissionChecker(Permission.AGENT_CREATE)] = (
            lambda: None
        )

        response = client.post(
            "/agents/register", json={"name": "A", "skills": [], "description": "d"}
        )
        assert response.status_code == 401
        assert "Authentication Failed" in response.json()["detail"]

    @patch("agents.routes.get_db")
    @patch("agents.routes.get_agent_id")
    def test_handle_agent_creation_conflict(self, mock_get_agent_id, mock_get_db):
        app.dependency_overrides[PermissionChecker(Permission.AGENT_CREATE)] = lambda: {
            "username": "admin",
            "role": "admin",
        }

        mock_get_agent_id.return_value = "existing-uuid"

        response = client.post(
            "/agents/register",
            json={
                "name": "ExistingAgent",
                "skills": ["skill1"],
                "description": "An existing agent",
            },
        )

        assert response.status_code == 409
        assert "already has the name" in response.json()["detail"]

    @patch("agents.routes.get_db")
    @patch("agents.routes.get_agent_id")
    @patch("agents.routes.create_agent")
    def test_handle_agent_creation_db_failure(
        self, mock_create_agent, mock_get_agent_id, mock_get_db
    ):
        app.dependency_overrides[PermissionChecker(Permission.AGENT_CREATE)] = lambda: {
            "username": "admin",
            "role": "admin",
        }

        mock_get_agent_id.return_value = None
        mock_create_agent.return_value = (None, None)

        response = client.post(
            "/agents/register",
            json={
                "name": "NewAgent",
                "skills": ["skill1"],
                "description": "A new agent",
            },
        )

        assert response.status_code == 500
        assert response.json()["detail"] == "Failed to create agent"

    @patch("agents.routes.get_db")
    @patch("agents.routes.get_agent_id")
    @patch("agents.routes.create_agent")
    @patch("agents.routes.rabbitmq_instance")
    def test_handle_agent_creation_rabbitmq_failure(
        self, mock_rabbitmq, mock_create_agent, mock_get_agent_id, mock_get_db
    ):
        app.dependency_overrides[PermissionChecker(Permission.AGENT_CREATE)] = lambda: {
            "username": "admin",
            "role": "admin",
        }

        mock_get_agent_id.return_value = None
        mock_create_agent.return_value = ("agent-uuid", "test-api-key")
        mock_rabbitmq.create_queue.side_effect = Exception("RabbitMQ Error")

        response = client.post(
            "/agents/register",
            json={
                "name": "NewAgent",
                "skills": ["skill1"],
                "description": "A new agent",
            },
        )

        assert response.status_code == 500
        assert "Failed to create RabbitMQ queue" in response.json()["detail"]

    @patch("agents.routes.get_db")
    @patch("agents.routes.delete_agent")
    @patch("agents.routes.rabbitmq_instance")
    def test_unregister_agent_success(
        self, mock_rabbitmq, mock_delete_agent, mock_get_db
    ):
        app.dependency_overrides[PermissionChecker(Permission.AGENT_DELETE)] = lambda: {
            "username": "admin",
            "role": "admin",
        }

        mock_delete_agent.return_value = True

        response = client.delete("/agents/unregister/agent-uuid")

        assert response.status_code == 200
        assert response.json() == {
            "message": "Agent agent-uuid successfully unregistered"
        }
        mock_rabbitmq.delete_queue.assert_called_once_with("agent-uuid")

    @patch("agents.routes.get_db")
    @patch("agents.routes.delete_agent")
    @patch("agents.routes.rabbitmq_instance")
    def test_unregister_agent_queue_fail(
        self, mock_rabbitmq, mock_delete_agent, mock_get_db
    ):
        app.dependency_overrides[PermissionChecker(Permission.AGENT_DELETE)] = lambda: {
            "username": "admin",
            "role": "admin",
        }

        mock_delete_agent.return_value = True
        mock_rabbitmq.delete_queue.side_effect = Exception("QueueFail")

        response = client.delete("/agents/unregister/agent-uuid")

        assert response.status_code == 200  # Should survive queue error

    @patch("agents.routes.get_db")
    @patch("agents.routes.delete_agent")
    def test_unregister_agent_not_found(self, mock_delete_agent, mock_get_db):
        app.dependency_overrides[PermissionChecker(Permission.AGENT_DELETE)] = lambda: {
            "username": "admin",
            "role": "admin",
        }

        mock_delete_agent.return_value = False

        response = client.delete("/agents/unregister/agent-uuid")

        assert response.status_code == 404
        assert "not found" in response.json()["detail"]

    @patch("agents.routes.get_db")
    def test_unregister_agent_no_user(self, mock_get_db):
        app.dependency_overrides[PermissionChecker(Permission.AGENT_DELETE)] = (
            lambda: None
        )
        response = client.delete("/agents/unregister/123")
        assert response.status_code == 401

    @patch("agents.routes.get_db")
    @patch("agents.routes.get_agent_details")
    def test_agent_details_success(self, mock_get_details, mock_get_db):
        app.dependency_overrides[PermissionChecker(Permission.AGENT_READ)] = lambda: {
            "username": "user",
            "role": "user",
        }

        mock_get_details.return_value = (
            "agent-uuid",
            "AgentName",
            ["skill1"],
            "active",
            "timestamp",
            "desc",
            "created",
        )

        response = client.get("/agents/details/agent-uuid")

        assert response.status_code == 200
        assert response.json()["name"] == "AgentName"

    @patch("agents.routes.get_db")
    @patch("agents.routes.get_agent_details")
    def test_agent_details_not_found(self, mock_get_details, mock_get_db):
        app.dependency_overrides[PermissionChecker(Permission.AGENT_READ)] = lambda: {
            "username": "user",
            "role": "user",
        }

        mock_get_details.return_value = (None, None, None, None, None, None, None)

        response = client.get("/agents/details/agent-uuid")

        assert response.status_code == 404

    @patch("agents.routes.get_db")
    def test_agent_details_no_user(self, mock_get_db):
        app.dependency_overrides[PermissionChecker(Permission.AGENT_READ)] = (
            lambda: None
        )
        response = client.get("/agents/details/123")
        assert response.status_code == 401

    @patch("agents.routes.get_db")
    @patch("agents.routes.get_all_agents")
    def test_get_all_agents_details(self, mock_get_all, mock_get_db):
        app.dependency_overrides[PermissionChecker(Permission.AGENT_READ)] = lambda: {
            "username": "user",
            "role": "user",
        }

        mock_get_all.return_value = [{"id": "1", "name": "A1"}]
        response = client.get("/agents/details/")
        assert response.status_code == 200
        assert len(response.json()) == 1

    @patch("agents.routes.get_db")
    def test_get_all_agents_no_user(self, mock_get_db):
        app.dependency_overrides[PermissionChecker(Permission.AGENT_READ)] = (
            lambda: None
        )
        response = client.get("/agents/details/")
        assert response.status_code == 401

    @patch("agents.routes.get_db")
    @patch("agents.routes.update_alive_agent_status")
    def test_detect_alive_agents_success(self, mock_update, mock_get_db):
        app.dependency_overrides[PermissionChecker(Permission.AGENT_EXECUTE)] = (
            lambda: {"username": "agent", "role": "agent"}
        )
        app.dependency_overrides[verify_agent_api_key] = lambda: ("agent-uuid", "key")
        mock_update.return_value = True

        response = client.post("/agents/heartbeat/agent-uuid")

        assert response.status_code == 200
        mock_update.assert_called()

    @patch("agents.routes.get_db")
    @patch("agents.routes.update_alive_agent_status")
    def test_detect_alive_agents_not_found_update(self, mock_update, mock_get_db):
        app.dependency_overrides[PermissionChecker(Permission.AGENT_EXECUTE)] = (
            lambda: {"username": "agent", "role": "agent"}
        )
        app.dependency_overrides[verify_agent_api_key] = lambda: ("agent-uuid", "key")
        mock_update.return_value = False

        response = client.post("/agents/heartbeat/agent-uuid")

        assert response.status_code == 404

    def test_detect_alive_agents_mismatch(self):
        app.dependency_overrides[PermissionChecker(Permission.AGENT_EXECUTE)] = (
            lambda: {"username": "agent", "role": "agent"}
        )
        app.dependency_overrides[verify_agent_api_key] = lambda: ("agent-X", "key")

        response = client.post("/agents/heartbeat/agent-Y")

        assert response.status_code == 403
        assert "Agent ID mismatch" in response.json()["detail"]
