from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from auth.auth_tool_functions import PermissionChecker
from auth.permissions import Permission
from users.routes import router

app = FastAPI()
app.include_router(router)

client = TestClient(app)


class TestUsersRoutesCoverage:

    @patch("users.routes.get_db")
    def test_update_role_success(self, mock_get_db):
        mock_db = MagicMock()
        mock_get_db.return_value = mock_db

        mock_query = mock_db.query.return_value
        mock_filter = mock_query.filter.return_value

        # First query checks if user has role (None = No)
        # Second query finds user to update (Mock User)
        mock_user = MagicMock()
        mock_filter.first.side_effect = [None, mock_user]

        from db.database import get_db

        app.dependency_overrides[get_db] = lambda: mock_db

        from auth.auth_tool_functions import get_current_user

        app.dependency_overrides[get_current_user] = lambda: {
            "username": "admin",
            "role": "admin",
        }

        response = client.post(
            "/users/update_role",
            json={"user_id": "targetuser", "new_role": "admin"},
        )

        assert response.status_code == 200
        assert response.json() == {"message": "Operation successfully happened"}

    @patch("users.routes.get_db")
    def test_update_role_no_user(self, mock_get_db):
        app.dependency_overrides[PermissionChecker(Permission.USER_UPDATE)] = (
            lambda: None
        )

        response = client.post(
            "/users/update_role", json={"user_id": "u", "new_role": "admin"}
        )
        assert response.status_code == 401

    @patch("users.routes.get_db")
    def test_update_role_db_error(self, mock_get_db):
        app.dependency_overrides[PermissionChecker(Permission.USER_UPDATE)] = lambda: {
            "username": "admin",
            "role": "admin",
        }

        mock_db = MagicMock()

        # Override db dependency at query level
        mock_db.query.side_effect = Exception("DB Error")
        mock_get_db.return_value = mock_db

        # Also override get_db dependency
        from db.database import get_db

        app.dependency_overrides[get_db] = lambda: mock_db

        response = client.post(
            "/users/update_role", json={"user_id": "u", "new_role": "admin"}
        )
        assert response.status_code == 500

    @patch("users.routes.get_all_users")
    def test_obtain_users_details_success(self, mock_get_all_users):
        app.dependency_overrides[PermissionChecker(Permission.USER_READ)] = lambda: {
            "username": "admin",
            "role": "admin",
        }

        mock_get_all_users.return_value = [{"id": 1, "username": "user1"}]

        response = client.get("/users/users_list")
        assert response.status_code == 200
        assert len(response.json()) == 1

    @patch("users.routes.get_all_users")
    def test_obtain_users_details_unauthorized(self, mock):
        app.dependency_overrides[PermissionChecker(Permission.USER_READ)] = lambda: None
        response = client.get("/users/users_list")
        assert response.status_code == 401

    @patch("users.routes.get_user_details")
    def test_user_details_success(self, mock_get_details):
        app.dependency_overrides[PermissionChecker(Permission.USER_READ)] = lambda: {
            "username": "admin",
            "role": "admin",
        }

        # Function returns tuple: (id, username, role)
        mock_get_details.return_value = (1, "user1", "user")

        response = client.get("/users/user_details/1")
        assert response.status_code == 200
        assert response.json() == {"id": 1, "username": "user1", "role": "user"}

    @patch("users.routes.get_user_details")
    def test_user_details_not_found(self, mock_get_details):
        app.dependency_overrides[PermissionChecker(Permission.USER_READ)] = lambda: {
            "username": "admin",
            "role": "admin",
        }

        mock_get_details.return_value = (None, None, None)

        response = client.get("/users/user_details/999")
        assert response.status_code == 404

    def test_user_details_no_user(self):
        app.dependency_overrides[PermissionChecker(Permission.USER_READ)] = lambda: None
        response = client.get("/users/user_details/1")
        assert response.status_code == 401

    def test_get_current_user_info_success(self):
        from auth.auth_tool_functions import get_current_user

        app.dependency_overrides[get_current_user] = lambda: {
            "id": 1,
            "username": "me",
            "role": "user",
        }

        response = client.get("/users/me")
        assert response.status_code == 200
        assert response.json()["username"] == "me"

    def test_get_current_user_info_unauthorized(self):
        from auth.auth_tool_functions import get_current_user

        app.dependency_overrides[get_current_user] = lambda: None

        response = client.get("/users/me")
        assert response.status_code == 401

    @patch("users.routes.delete_user_tool")
    @patch("users.routes.get_db")
    def test_delete_user_success(self, mock_db, mock_delete_tool):
        app.dependency_overrides[PermissionChecker(Permission.USER_DELETE)] = lambda: {
            "id": 1,
            "username": "admin",
            "role": "admin",
        }

        mock_delete_tool.return_value = {"message": "User successfully deleted"}

        response = client.delete("/users/2")
        assert response.status_code == 200

    def test_delete_user_no_user(self):
        app.dependency_overrides[PermissionChecker(Permission.USER_DELETE)] = (
            lambda: None
        )
        response = client.delete("/users/1")
        assert response.status_code == 401

    @patch("users.routes.get_db")
    def test_delete_user_self_failure(self, mock_db):
        app.dependency_overrides[PermissionChecker(Permission.USER_DELETE)] = lambda: {
            "id": 1,
            "username": "admin",
            "role": "admin",
        }

        response = client.delete("/users/1")
        assert response.status_code == 403
        assert "Cannot delete your own account" in response.json()["detail"]

    @patch("users.routes.modify_user_password")
    @patch("users.routes.get_db")
    def test_change_password_success(self, mock_db, mock_modify_pw):
        from auth.auth_tool_functions import get_current_user

        app.dependency_overrides[get_current_user] = lambda: {
            "username": "user",
            "role": "user",
        }

        mock_modify_pw.return_value = True

        response = client.post(
            "/users/me/password_modification",
            json={"old_password": "old_password", "new_password": "new_password"},
        )
        assert response.status_code == 200
        assert response.json()["message"] == "Password successfully changed"

    @patch("users.routes.modify_user_password")
    @patch("users.routes.get_db")
    def test_change_password_failure(self, mock_db, mock_modify_pw):
        from auth.auth_tool_functions import get_current_user

        app.dependency_overrides[get_current_user] = lambda: {
            "username": "user",
            "role": "user",
        }

        mock_modify_pw.return_value = False

        response = client.post(
            "/users/me/password_modification",
            json={"old_password": "wrong", "new_password": "new123"},
        )
        assert response.status_code == 400

    @patch("users.routes.modify_user_username")
    @patch("users.routes.get_db")
    def test_change_username_success(self, mock_db, mock_modify_user):
        from auth.auth_tool_functions import get_current_user

        app.dependency_overrides[get_current_user] = lambda: {
            "username": "user",
            "role": "user",
        }

        mock_modify_user.return_value = True

        response = client.post("/users/me/username_modification/newname")
        assert response.status_code == 200

    @patch("users.routes.modify_user_username")
    @patch("users.routes.get_db")
    def test_change_username_failure(self, mock_db, mock_modify_user):
        from auth.auth_tool_functions import get_current_user

        app.dependency_overrides[get_current_user] = lambda: {
            "username": "user",
            "role": "user",
        }

        mock_modify_user.return_value = False

        response = client.post("/users/me/username_modification/newname")
        assert response.status_code == 400

    @patch("users.routes.get_db")
    def test_update_role_already_has_role(self, mock_get_db):
        app.dependency_overrides[PermissionChecker(Permission.USER_UPDATE)] = lambda: {
            "username": "admin",
            "role": "admin",
        }

        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        mock_query = mock_db.query.return_value
        mock_filter = mock_query.filter.return_value

        # first query returns something (already has role)
        mock_filter.first.return_value = MagicMock()

        from db.database import get_db

        app.dependency_overrides[get_db] = lambda: mock_db

        response = client.post(
            "/users/update_role", json={"user_id": "u", "new_role": "admin"}
        )
        assert response.status_code == 403
        assert "User already has role" in response.json()["detail"]

    @patch("users.routes.get_db")
    def test_update_role_target_not_found(self, mock_get_db):
        app.dependency_overrides[PermissionChecker(Permission.USER_UPDATE)] = lambda: {
            "username": "admin",
            "role": "admin",
        }

        mock_db = MagicMock()
        mock_get_db.return_value = mock_db
        mock_query = mock_db.query.return_value
        mock_filter = mock_query.filter.return_value

        # first query returns None (not already has role), second query returns None (target not found)
        mock_filter.first.side_effect = [None, None]

        from db.database import get_db

        app.dependency_overrides[get_db] = lambda: mock_db

        response = client.post(
            "/users/update_role", json={"user_id": "u", "new_role": "admin"}
        )
        assert response.status_code == 404
        assert "User not found" in response.json()["detail"]
