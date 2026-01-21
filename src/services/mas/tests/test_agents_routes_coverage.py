from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agents.routes import router

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
        from auth.auth_tool_functions import get_current_user

        app.dependency_overrides[get_current_user] = lambda: {
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
    @patch("agents.routes.get_agent_id")
    def test_handle_agent_creation_conflict(self, mock_get_agent_id, mock_get_db):
        from auth.auth_tool_functions import get_current_user

        app.dependency_overrides[get_current_user] = lambda: {
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
        from auth.auth_tool_functions import get_current_user

        app.dependency_overrides[get_current_user] = lambda: {
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
        from auth.auth_tool_functions import get_current_user

        app.dependency_overrides[get_current_user] = lambda: {
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
        from auth.auth_tool_functions import get_current_user

        app.dependency_overrides[get_current_user] = lambda: {
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
    def test_unregister_agent_not_found(self, mock_delete_agent, mock_get_db):
        from auth.auth_tool_functions import get_current_user

        app.dependency_overrides[get_current_user] = lambda: {
            "username": "admin",
            "role": "admin",
        }

        mock_delete_agent.return_value = False

        response = client.delete("/agents/unregister/agent-uuid")

        assert response.status_code == 404
        assert "not found" in response.json()["detail"]

    @patch("agents.routes.get_db")
    @patch("agents.routes.get_agent_details")
    def test_agent_details_success(self, mock_get_details, mock_get_db):
        from auth.auth_tool_functions import get_current_user

        app.dependency_overrides[get_current_user] = lambda: {
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
        from auth.auth_tool_functions import get_current_user

        app.dependency_overrides[get_current_user] = lambda: {
            "username": "user",
            "role": "user",
        }

        mock_get_details.return_value = (None, None, None, None, None, None, None)

        response = client.get("/agents/details/agent-uuid")

        assert response.status_code == 404

    @patch("agents.routes.get_db")
    @patch("agents.routes.get_all_agents")
    def test_get_all_agents_details(self, mock_get_all, mock_get_db):
        from auth.auth_tool_functions import get_current_user

        app.dependency_overrides[get_current_user] = lambda: {
            "username": "user",
            "role": "user",
        }

        mock_get_all.return_value = [{"id": "1", "name": "A1"}]

        response = client.get("/agents/details/")

        assert response.status_code == 200
        assert len(response.json()) == 1

    @patch("agents.routes.get_db")
    @patch("agents.routes.update_alive_agent_status")
    def test_detect_alive_agents_success(self, mock_update, mock_get_db):
        from auth.auth_tool_functions import get_current_user, verify_agent_api_key

        app.dependency_overrides[get_current_user] = lambda: {
            "username": "user",
            "role": "user",
        }
        app.dependency_overrides[verify_agent_api_key] = lambda: ("agent-uuid", "key")

        mock_update.return_value = True

        response = client.post("/agents/heartbeat/agent-uuid")

        assert response.status_code == 200
        assert "Heartbeat received" in response.json()["message"]

    @patch("agents.routes.get_db")
    @patch("agents.routes.update_alive_agent_status")
    def test_detect_alive_agents_not_found(self, mock_update, mock_get_db):
        from auth.auth_tool_functions import get_current_user, verify_agent_api_key

        app.dependency_overrides[get_current_user] = lambda: {
            "username": "user",
            "role": "user",
        }
        app.dependency_overrides[verify_agent_api_key] = lambda: ("agent-uuid", "key")

        mock_update.return_value = False

        response = client.post("/agents/heartbeat/agent-uuid")

        assert response.status_code == 404
