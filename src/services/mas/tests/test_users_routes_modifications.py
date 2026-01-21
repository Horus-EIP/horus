from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from schemas.schemas import UserPasswordModification
from users.routes import router

app = FastAPI()
app.include_router(router)

client = TestClient(app)


class TestUsersRoutesModifications:

    @patch("users.routes.modify_user_password")
    def test_password_modification_success(self, mock_modify_password):
        mock_modify_password.return_value = True

        # Override dependency
        from auth.auth_tool_functions import get_current_user

        app.dependency_overrides[get_current_user] = lambda: {
            "id": 1,
            "username": "testuser",
            "role": "user",
        }
        from db.database import get_db

        app.dependency_overrides[get_db] = lambda: MagicMock()

        payload = {"old_password": "oldpass", "new_password": "newpass"}

        response = client.post("/users/me/password_modification", json=payload)

        assert response.status_code == 200
        assert response.json() == {"message": "Password successfully changed"}
        mock_modify_password.assert_called_once()

    @patch("users.routes.modify_user_password")
    def test_password_modification_failure(self, mock_modify_password):
        mock_modify_password.return_value = False

        # Override dependency
        from auth.auth_tool_functions import get_current_user

        app.dependency_overrides[get_current_user] = lambda: {
            "id": 1,
            "username": "testuser",
            "role": "user",
        }

        payload = {"old_password": "wrongpass", "new_password": "newpass"}

        response = client.post("/users/me/password_modification", json=payload)

        assert response.status_code == 400
        assert "Failed to change password" in response.json()["detail"]

    @patch("users.routes.modify_user_username")
    def test_username_modification_success(self, mock_modify_username):
        mock_modify_username.return_value = True

        # Override dependency
        from auth.auth_tool_functions import get_current_user

        app.dependency_overrides[get_current_user] = lambda: {
            "id": 1,
            "username": "oldname",
            "role": "user",
        }
        from db.database import get_db

        app.dependency_overrides[get_db] = lambda: MagicMock()

        new_username = "newname"
        response = client.post(f"/users/me/username_modification/{new_username}")

        assert response.status_code == 200
        assert response.json() == {"message": "Username successfully changed"}
        mock_modify_username.assert_called_once()

    @patch("users.routes.modify_user_username")
    def test_username_modification_failure(self, mock_modify_username):
        mock_modify_username.return_value = False

        # Override dependency
        from auth.auth_tool_functions import get_current_user

        app.dependency_overrides[get_current_user] = lambda: {
            "id": 1,
            "username": "oldname",
            "role": "user",
        }

        new_username = "takenname"
        response = client.post(f"/users/me/username_modification/{new_username}")

        assert response.status_code == 400
        assert "Failed to change username" in response.json()["detail"]
