from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from auth.auth_tool_functions import PermissionChecker
from auth.permissions import Permission
from tasks.routes import router

app = FastAPI()
app.include_router(router)
client = TestClient(app)


class TestTasksRoutesCancel:

    @patch("tasks.routes.get_db")
    @patch("tasks.routes.interrupt_task")
    def test_cancel_task_success(self, mock_interrupt, mock_get_db):
        # Mock authentication/permission
        async def mock_auth_dependency():
            return {"username": "admin", "role": "admin"}

        # Override the dependency. Since PermissionChecker implements __eq__ and __hash__,
        # we can use an equivalent instance as the key.
        app.dependency_overrides[PermissionChecker(Permission.TASK_DELETE)] = (
            mock_auth_dependency
        )

        # Mock interrupt_task to return True
        mock_interrupt.return_value = True

        try:
            response = client.patch("/tasks/task-cancel/task-123")

            assert response.status_code == 200
            assert response.json() == {
                "message": "Task task-123 has been canceled successfully."
            }
            mock_interrupt.assert_called_once()
            args, _ = mock_interrupt.call_args
            assert args[0] == "task-123"
        finally:
            app.dependency_overrides = {}

    @patch("tasks.routes.get_db")
    @patch("tasks.routes.interrupt_task")
    def test_cancel_task_failure(self, mock_interrupt, mock_get_db):
        # Mock auth
        async def mock_auth_dependency():
            return {"username": "admin", "role": "admin"}

        app.dependency_overrides[PermissionChecker(Permission.TASK_DELETE)] = (
            mock_auth_dependency
        )

        # Mock interrupt_task to raise HTTPException
        mock_interrupt.side_effect = HTTPException(
            status_code=404, detail="Task not found"
        )

        try:
            response = client.patch("/tasks/task-cancel/task-unknown")

            assert response.status_code == 404
            assert response.json()["detail"] == "Task not found"
        finally:
            app.dependency_overrides = {}

    @patch("tasks.routes.get_db")
    @patch("tasks.routes.interrupt_task")
    def test_cancel_task_internal_error(self, mock_interrupt, mock_get_db):
        # Mock auth
        async def mock_auth_dependency():
            return {"username": "admin", "role": "admin"}

        app.dependency_overrides[PermissionChecker(Permission.TASK_DELETE)] = (
            mock_auth_dependency
        )

        # Mock interrupt_task to raise generic Exception
        mock_interrupt.side_effect = Exception("Database error")

        try:
            response = client.patch("/tasks/task-cancel/task-error")

            assert response.status_code == 500
            assert "Error Canceling task" in response.json()["detail"]
        finally:
            app.dependency_overrides = {}
