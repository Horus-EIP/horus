from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tasks.routes import router

app = FastAPI()
app.include_router(router)

client = TestClient(app)


class TestTasksRoutesCoverage:

    @patch("tasks.routes.get_db")
    @patch("tasks.routes.select_agent_for_task")
    @patch("tasks.routes.insert_new_task")
    @patch("tasks.routes.rabbitmq_instance")
    @patch("tasks.routes.add_messages")
    def test_create_new_task_success(
        self, mock_add_msg, mock_rabbitmq, mock_insert, mock_select, mock_get_db
    ):
        from auth.auth_tool_functions import get_current_user

        app.dependency_overrides[get_current_user] = lambda: {
            "username": "user",
            "role": "user",
        }

        mock_select.return_value = ("agent-uuid", "demand", None, [])
        mock_insert.return_value = "task-uuid"

        response = client.post(
            "/tasks/new_task/",
            json={
                "demand": "Do something",
                "conversation_id": "1",
                "skills_required": ["skill"],
            },
        )

        assert response.status_code == 200
        assert response.json()["task_id"] == "task-uuid"
        mock_rabbitmq.publish.assert_called_once()
        mock_add_msg.assert_called_once()

    @patch("tasks.routes.get_db")
    @patch("tasks.routes.select_agent_for_task")
    @patch("tasks.routes.add_messages")
    def test_create_new_task_no_agent(self, mock_add_msg, mock_select, mock_get_db):
        from auth.auth_tool_functions import get_current_user

        app.dependency_overrides[get_current_user] = lambda: {
            "username": "user",
            "role": "user",
        }

        mock_select.return_value = (None, None, None, None)

        response = client.post(
            "/tasks/new_task/",
            json={
                "demand": "Do something",
                "conversation_id": "1",
                "skills_required": ["skill"],
            },
        )

        assert response.status_code == 200
        assert "No agent registered" in response.json()["message"]
        mock_add_msg.assert_called_once()

    @patch("tasks.routes.get_db")
    @patch("tasks.routes.select_agent_for_task")
    @patch("tasks.routes.add_messages")
    def test_create_new_task_anticipated_answer(
        self, mock_add_msg, mock_select, mock_get_db
    ):
        from auth.auth_tool_functions import get_current_user

        app.dependency_overrides[get_current_user] = lambda: {
            "username": "user",
            "role": "user",
        }

        mock_select.return_value = (None, None, "Response for user: Hello", None)

        response = client.post(
            "/tasks/new_task/",
            json={
                "demand": "Do something",
                "conversation_id": "1",
                "skills_required": ["skill"],
            },
        )

        assert response.status_code == 200
        assert "Response for user: Hello" in response.json()["message"]
        mock_add_msg.assert_called_once()

    @patch("tasks.routes.get_db")
    @patch("tasks.routes.validating_task_results")
    @patch("tasks.routes.Task")
    @patch("tasks.routes.add_messages")
    @patch("tasks.routes.send_messages_via_websockets")
    def test_sharing_agent_result_success(
        self, mock_send_ws, mock_add_msg, mock_task_model, mock_validate, mock_get_db
    ):
        from auth.auth_tool_functions import get_current_user, verify_agent_api_key

        app.dependency_overrides[get_current_user] = lambda: {
            "username": "system_agent",
            "role": "system",
        }
        app.dependency_overrides[verify_agent_api_key] = lambda: ("agent-uuid", "key")

        mock_db = MagicMock()
        mock_get_db.return_value = mock_db

        mock_task = MagicMock()
        mock_task.result = MagicMock()
        mock_task.result.future_actions = []
        mock_task.result.history = []

        mock_db.query.return_value.filter.return_value.first.return_value = mock_task

        from db.database import get_db

        app.dependency_overrides[get_db] = lambda: mock_db

        response = client.post(
            "/tasks/task-result/",
            json={
                "task_id": "task-uuid",
                "result": "Done",
                "conversation_id": "1",
                "agent_id": "agent-uuid",
            },
        )

        assert response.status_code == 200
        mock_add_msg.assert_called_once()
        mock_send_ws.assert_called_once()

    @patch("tasks.routes.get_db")
    @patch("tasks.routes.validating_task_results")
    @patch("tasks.routes.Task")
    @patch("tasks.routes.insert_new_task")
    @patch("tasks.routes.rabbitmq_instance")
    def test_sharing_agent_result_with_subtasks(
        self, mock_rabbitmq, mock_insert, mock_task_model, mock_validate, mock_get_db
    ):
        from auth.auth_tool_functions import get_current_user, verify_agent_api_key

        app.dependency_overrides[get_current_user] = lambda: {
            "username": "system_agent",
            "role": "system",
        }
        app.dependency_overrides[verify_agent_api_key] = lambda: ("agent-uuid", "key")

        mock_db = MagicMock()
        mock_get_db.return_value = mock_db

        mock_task = MagicMock()
        mock_task.result = MagicMock()
        mock_task.result.future_actions = [["next-agent", "next-action"]]
        mock_task.result.history = []
        mock_task.order = 1
        mock_task.conversation_id = "1"  # Fix: Set conversation_id to a string

        # First query returns original task, second query returns new subtask
        mock_subtask = MagicMock()
        mock_db.query.return_value.filter.return_value.first.side_effect = [
            mock_task,
            mock_subtask,
        ]

        mock_insert.return_value = "subtask-uuid"

        from db.database import get_db

        app.dependency_overrides[get_db] = lambda: mock_db

        response = client.post(
            "/tasks/task-result/",
            json={
                "task_id": "task-uuid",
                "result": "Done",
                "conversation_id": "1",
                "agent_id": "agent-uuid",
            },
        )

        assert response.status_code == 200
        mock_insert.assert_called_once()
        mock_rabbitmq.publish.assert_called_once()

    @patch("tasks.routes.get_db")
    @patch("tasks.routes.validating_task_results")
    @patch("tasks.routes.Task")
    def test_sharing_agent_result_task_not_found(
        self, mock_task_model, mock_validate, mock_get_db
    ):
        from auth.auth_tool_functions import get_current_user, verify_agent_api_key

        app.dependency_overrides[get_current_user] = lambda: {
            "username": "system_agent",
            "role": "system",
        }
        app.dependency_overrides[verify_agent_api_key] = lambda: ("agent-uuid", "key")

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None

        from db.database import get_db

        app.dependency_overrides[get_db] = lambda: mock_db

        response = client.post(
            "/tasks/task-result/",
            json={
                "task_id": "task-uuid",
                "result": "Done",
                "conversation_id": "1",
                "agent_id": "agent-uuid",
            },
        )

        assert response.status_code == 404
        assert "Task not found" in response.json()["detail"]
