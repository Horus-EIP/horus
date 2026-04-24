from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from auth.auth_tool_functions import PermissionChecker, verify_agent_api_key
from auth.permissions import Permission
from core.metrics import TASK_ERRORS, TASK_QUEUE_DEPTH
from db.database import get_db
from db.models import Task, TaskResult
# Import module to be tested
from tasks.routes import get_task_queue_stats, router, update_task_queue_depth
from tasks.status import TaskStatus

app = FastAPI()
app.include_router(router)
client = TestClient(app)


class TestTasksRoutesCoverage:

    def teardown_method(self):
        app.dependency_overrides = {}

    def test_get_queue_stats_success(self):
        app.dependency_overrides[PermissionChecker(Permission.VIEW_ANALYTICS)] = (
            lambda: {"username": "admin", "role": "admin"}
        )
        mock_db = MagicMock()
        app.dependency_overrides[get_db] = lambda: mock_db

        # Mock TASK_QUEUE_DEPTH
        with patch("tasks.routes.TASK_QUEUE_DEPTH") as mock_metric:
            mock_metric.ephemeral_val.return_value = 5
            response = client.get("/tasks/stats/queue")
            assert response.status_code == 200, response.text
            assert response.json()["pending"] == 5

    def test_get_queue_stats_exception(self):
        app.dependency_overrides[PermissionChecker(Permission.VIEW_ANALYTICS)] = (
            lambda: {"username": "admin", "role": "admin"}
        )
        mock_db = MagicMock()
        app.dependency_overrides[get_db] = lambda: mock_db

        # Mock TASK_QUEUE_DEPTH to raise exception
        with patch("tasks.routes.TASK_QUEUE_DEPTH") as mock_metric:
            mock_metric.ephemeral_val.side_effect = Exception("Metric Error")
            response = client.get("/tasks/stats/queue")
            assert response.status_code == 200, response.text
            assert response.json()["pending"] == 0

    @patch("tasks.routes.resolve_work_queue_for_agent_id", return_value="horus.work.general")
    @patch("tasks.routes.select_agent_for_task")
    @patch("tasks.routes.insert_new_task")
    @patch("tasks.routes.rabbitmq_instance")
    @patch("tasks.routes.add_messages")
    def test_create_new_task_success(
        self, mock_add_messages, mock_rabbitmq, mock_insert, mock_select, _mock_wq
    ):
        app.dependency_overrides[PermissionChecker(Permission.TASK_CREATE)] = lambda: {
            "username": "user",
            "role": "user",
        }
        mock_db = MagicMock()
        app.dependency_overrides[get_db] = lambda: mock_db

        mock_select.return_value = ("agent_id", "user_demand", None, [])
        mock_insert.return_value = "task_uuid"

        payload = {
            "demand": "test",
            "conversation_id": "1",
            "skills_required": ["skill"],
        }
        response = client.post("/tasks/new_task/", json=payload)

        assert response.status_code == 200, response.text
        assert response.json()["task_id"] == "task_uuid"
        mock_rabbitmq.publish.assert_called()

    @patch("tasks.routes.select_agent_for_task")
    @patch("tasks.routes.decompose_task")
    @patch("tasks.routes.add_messages")
    def test_create_new_task_no_agent_fail(
        self, mock_add_messages, mock_decompose, mock_select
    ):
        app.dependency_overrides[PermissionChecker(Permission.TASK_CREATE)] = lambda: {
            "username": "user",
            "role": "user",
        }
        mock_db = MagicMock()
        app.dependency_overrides[get_db] = lambda: mock_db

        mock_select.return_value = (None, None, None, None)
        mock_decompose.return_value = (None, None)

        payload = {
            "demand": "test",
            "conversation_id": "1",
            "skills_required": ["skill"],
        }
        response = client.post("/tasks/new_task/", json=payload)

        assert response.status_code == 200, response.text
        assert "No agent registered" in response.json()["message"]
        mock_add_messages.assert_called()

    @patch("tasks.routes.resolve_work_queue_for_agent_id", return_value="horus.work.general")
    @patch("tasks.routes.select_agent_for_task")
    @patch("tasks.routes.decompose_task")
    @patch("tasks.routes.insert_new_task")
    @patch("tasks.routes.rabbitmq_instance")
    def test_create_new_task_decompose_success(
        self, mock_rabbitmq, mock_insert, mock_decompose, mock_select, _mock_wq
    ):
        app.dependency_overrides[PermissionChecker(Permission.TASK_CREATE)] = lambda: {
            "username": "user",
            "role": "user",
        }
        mock_db = MagicMock()
        app.dependency_overrides[get_db] = lambda: mock_db

        mock_select.return_value = (None, None, None, None)
        mock_decompose.return_value = (("agent_id", "sub_demand"), [])
        mock_insert.return_value = "task_uuid"

        payload = {
            "demand": "test",
            "conversation_id": "1",
            "skills_required": ["skill"],
        }
        response = client.post("/tasks/new_task/", json=payload)

        assert response.status_code == 200, response.text
        assert response.json()["task_id"] == "task_uuid"

    @patch("tasks.routes.select_agent_for_task")
    @patch("tasks.routes.add_messages")
    def test_create_new_task_anticipated_answer(self, mock_add_messages, mock_select):
        app.dependency_overrides[PermissionChecker(Permission.TASK_CREATE)] = lambda: {
            "username": "user",
            "role": "user",
        }
        mock_db = MagicMock()
        app.dependency_overrides[get_db] = lambda: mock_db

        mock_select.return_value = (None, None, "Response for user: Answer", None)

        payload = {
            "demand": "test",
            "conversation_id": "1",
            "skills_required": ["skill"],
        }
        response = client.post("/tasks/new_task/", json=payload)

        assert response.status_code == 200, response.text
        assert response.json()["message"] == "Processing complete"

    def test_create_new_task_no_user(self):
        app.dependency_overrides[PermissionChecker(Permission.TASK_CREATE)] = (
            lambda: None
        )
        payload = {
            "demand": "test",
            "conversation_id": "1",
            "skills_required": ["skill"],
        }
        response = client.post("/tasks/new_task/", json=payload)
        assert response.status_code == 401

    @patch("tasks.routes.validating_task_results")
    def test_task_result_agent_mismatch(self, mock_validate):
        app.dependency_overrides[PermissionChecker(Permission.TASK_EXECUTE)] = lambda: {
            "username": "agent",
            "role": "agent",
        }
        app.dependency_overrides[verify_agent_api_key] = lambda: ("agent_1", "key")
        mock_db = MagicMock()
        mock_task = MagicMock()
        mock_task.agent_id = "agent_1"
        mock_db.query.return_value.filter.return_value.first.return_value = mock_task
        app.dependency_overrides[get_db] = lambda: mock_db

        payload = {
            "task_id": "t1",
            "result": "res",
            "conversation_id": "1",
            "agent_id": "agent_2",
        }
        response = client.post("/tasks/task-result/", json=payload)

        assert response.status_code == 403
        assert "must match the task's assigned agent" in response.json()["detail"]

    @patch("tasks.routes.validating_task_results")
    def test_task_result_task_not_found(self, mock_validate):
        app.dependency_overrides[PermissionChecker(Permission.TASK_EXECUTE)] = lambda: {
            "username": "agent",
            "role": "agent",
        }
        app.dependency_overrides[verify_agent_api_key] = lambda: ("agent_1", "key")

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None
        app.dependency_overrides[get_db] = lambda: mock_db

        payload = {
            "task_id": "t1",
            "result": "res",
            "conversation_id": "1",
            "agent_id": "agent_1",
        }
        response = client.post("/tasks/task-result/", json=payload)

        assert response.status_code == 404
        assert "Task not found" in response.json()["detail"]

    @patch("tasks.routes.validating_task_results")
    def test_task_result_result_not_found(self, mock_validate):
        app.dependency_overrides[PermissionChecker(Permission.TASK_EXECUTE)] = lambda: {
            "username": "agent",
            "role": "agent",
        }
        app.dependency_overrides[verify_agent_api_key] = lambda: ("agent_1", "key")

        mock_db = MagicMock()
        mock_task = MagicMock()
        mock_task.agent_id = "agent_1"
        mock_task.result = None
        mock_db.query.return_value.filter.return_value.first.return_value = mock_task
        app.dependency_overrides[get_db] = lambda: mock_db

        payload = {
            "task_id": "t1",
            "result": "res",
            "conversation_id": "1",
            "agent_id": "agent_1",
        }
        response = client.post("/tasks/task-result/", json=payload)

        assert response.status_code == 404
        assert "TaskResult not found" in response.json()["detail"]

    @patch("tasks.routes.validating_task_results")
    @patch("tasks.routes.aggregate_results")
    @patch("tasks.routes.send_messages_via_websockets")
    def test_task_result_success_no_actions(
        self, mock_send_ws, mock_agg, mock_validate
    ):
        app.dependency_overrides[PermissionChecker(Permission.TASK_EXECUTE)] = lambda: {
            "username": "agent",
            "role": "agent",
        }
        app.dependency_overrides[verify_agent_api_key] = lambda: ("agent_1", "key")

        mock_db = MagicMock()
        mock_task = MagicMock()
        mock_task.agent_id = "agent_1"
        mock_task_res = MagicMock()
        mock_task_res.future_actions = []
        mock_task_res.history = []
        mock_task.result = mock_task_res
        mock_db.query.return_value.filter.return_value.first.return_value = mock_task
        app.dependency_overrides[get_db] = lambda: mock_db

        mock_agg.return_value = "final"

        payload = {
            "task_id": "t1",
            "result": "res",
            "conversation_id": "1",
            "agent_id": "agent_1",
        }
        response = client.post("/tasks/task-result/", json=payload)

        assert response.status_code == 200, response.text
        mock_send_ws.assert_called()

    @patch("tasks.routes.resolve_work_queue_for_agent_id", return_value="horus.work.general")
    @patch("tasks.routes.validating_task_results")
    @patch("tasks.routes.insert_new_task")
    @patch("tasks.routes.rabbitmq_instance")
    @patch("tasks.routes.log_agent_operation")
    @patch("tasks.routes.TASK_QUEUE_DEPTH")
    def test_task_result_success_with_actions(
        self,
        mock_queue_depth,
        mock_log,
        mock_rabbitmq,
        mock_insert,
        mock_validate,
        _mock_wq,
    ):
        app.dependency_overrides[PermissionChecker(Permission.TASK_EXECUTE)] = lambda: {
            "username": "agent",
            "role": "agent",
        }
        app.dependency_overrides[verify_agent_api_key] = lambda: ("agent_1", "key")

        mock_db = MagicMock()
        mock_task = MagicMock()
        mock_task.id = "task_1"
        mock_task.agent_id = "agent_1"
        mock_task.order = 1
        mock_task.conversation_id = 1
        mock_task_res = MagicMock()
        mock_task_res.future_actions = [["next_agent", "action"]]
        mock_task_res.history = []
        mock_task.result = mock_task_res

        mock_subtask = MagicMock()
        mock_subtask.to_dict.return_value = {"id": "sub_task_id", "demand": "action"}

        mock_query = mock_db.query.return_value
        mock_filter = mock_query.filter.return_value
        # Task lookup (auth), validating_task_results, re-fetch task, then subtask row
        mock_filter.first.side_effect = [
            mock_task,
            mock_task,
            mock_task,
            mock_subtask,
        ]

        app.dependency_overrides[get_db] = lambda: mock_db
        mock_insert.return_value = "sub_task_id"

        payload = {
            "task_id": "t1",
            "result": "res",
            "conversation_id": "1",
            "agent_id": "agent_1",
        }

        with patch("core.metrics.TASK_ERRORS") as mock_metric:
            response = client.post("/tasks/task-result/", json=payload)
            assert response.status_code == 200, response.text
            mock_insert.assert_called()
            mock_rabbitmq.publish.assert_called()

    @patch("tasks.routes.validating_task_results")
    def test_task_result_exception(self, mock_validate):
        app.dependency_overrides[PermissionChecker(Permission.TASK_EXECUTE)] = lambda: {
            "username": "agent",
            "role": "agent",
        }
        app.dependency_overrides[verify_agent_api_key] = lambda: ("agent_1", "key")

        mock_validate.side_effect = Exception("Validation Error")

        payload = {
            "task_id": "t1",
            "result": "res",
            "conversation_id": "1",
            "agent_id": "agent_1",
        }
        mock_db = MagicMock()
        mock_task = MagicMock()
        mock_task.agent_id = "agent_1"
        mock_db.query.return_value.filter.return_value.first.return_value = mock_task
        app.dependency_overrides[get_db] = lambda: mock_db

        with patch("tasks.routes.TASK_ERRORS") as mock_metric:
            response = client.post("/tasks/task-result/", json=payload)
            assert response.status_code == 500
            assert "Error processing task result" in response.json()["detail"]

    @patch("tasks.routes.interrupt_task")
    def test_cancel_task_http_exception(self, mock_interrupt):
        app.dependency_overrides[PermissionChecker(Permission.TASK_DELETE)] = lambda: {
            "username": "admin",
            "role": "admin",
        }
        mock_interrupt.side_effect = HTTPException(status_code=404, detail="Not Found")

        response = client.patch("/tasks/task-cancel/t1")
        assert response.status_code == 404
        assert "Not Found" in response.json()["detail"]

    def test_update_task_queue_depth(self):
        with patch("tasks.routes.TASK_QUEUE_DEPTH") as mock_metric:
            update_task_queue_depth(10)
            mock_metric.set.assert_called_with(10)

    @patch("tasks.routes.interrupt_task")
    def test_cancel_task_success(self, mock_interrupt):
        app.dependency_overrides[PermissionChecker(Permission.TASK_DELETE)] = lambda: {
            "username": "admin",
            "role": "admin",
        }
        mock_db = MagicMock()
        app.dependency_overrides[get_db] = lambda: mock_db

        mock_interrupt.return_value = True

        response = client.patch("/tasks/task-cancel/t1")
        assert response.status_code == 200, response.text
        assert "canceled successfully" in response.json()["message"]

    @patch("tasks.routes.interrupt_task")
    def test_cancel_task_failed_interrupt(self, mock_interrupt):
        app.dependency_overrides[PermissionChecker(Permission.TASK_DELETE)] = lambda: {
            "username": "admin",
            "role": "admin",
        }
        mock_db = MagicMock()
        app.dependency_overrides[get_db] = lambda: mock_db

        mock_interrupt.return_value = False
        response = client.patch("/tasks/task-cancel/t1")
        assert response.status_code == 200, response.text
        assert response.json() is None

    def test_cancel_task_no_user(self):
        app.dependency_overrides[PermissionChecker(Permission.TASK_DELETE)] = (
            lambda: None
        )
        response = client.patch("/tasks/task-cancel/t1")
        assert response.status_code == 401

    @patch("tasks.routes.interrupt_task")
    def test_cancel_task_exception(self, mock_interrupt):
        app.dependency_overrides[PermissionChecker(Permission.TASK_DELETE)] = lambda: {
            "username": "admin",
            "role": "admin",
        }

        mock_interrupt.side_effect = Exception("Interrupt Error")
        mock_db = MagicMock()
        app.dependency_overrides[get_db] = lambda: mock_db

        with patch("tasks.routes.TASK_ERRORS") as mock_metric:
            response = client.patch("/tasks/task-cancel/t1")
            assert response.status_code == 500
            assert "Error Canceling task" in response.json()["detail"]

    @patch("tasks.routes.interrupt_task")
    def test_cancel_task_http_exception(self, mock_interrupt):
        app.dependency_overrides[PermissionChecker(Permission.TASK_DELETE)] = lambda: {
            "username": "admin",
            "role": "admin",
        }
        mock_interrupt.side_effect = HTTPException(status_code=404, detail="Not Found")
        mock_db = MagicMock()
        app.dependency_overrides[get_db] = lambda: mock_db

        response = client.patch("/tasks/task-cancel/t1")
        assert response.status_code == 404
        assert "Not Found" in response.json()["detail"]

    def test_update_task_queue_depth(self):
        with patch("tasks.routes.TASK_QUEUE_DEPTH") as mock_metric:
            update_task_queue_depth(10)
            mock_metric.set.assert_called_with(10)
