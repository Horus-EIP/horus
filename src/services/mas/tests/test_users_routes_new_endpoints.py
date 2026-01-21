from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from db.models import Users
from users.routes import router

app = FastAPI()
app.include_router(router)

client = TestClient(app)


class TestUsersRoutesNewEndpoints:

    @patch("users.routes.get_all_users")
    def test_users_list_success(self, mock_get_all_users):
        # Mock data
        mock_users = [
            {"id": 1, "username": "user1", "role": "user"},
            {"id": 2, "username": "admin", "role": "admin"},
        ]
        mock_get_all_users.return_value = mock_users

        # Override dependency
        from auth.auth_tool_functions import get_current_user

        app.dependency_overrides[get_current_user] = lambda: {
            "username": "admin",
            "role": "admin",
        }
        from db.database import get_db

        app.dependency_overrides[get_db] = lambda: MagicMock()

        response = client.get("/users/users_list/")

        assert response.status_code == 200
        assert response.json() == mock_users
        mock_get_all_users.assert_called_once()

    def test_users_list_unauthorized(self):
        # Override dependency to raise 401
        from auth.auth_tool_functions import get_current_user
        from fastapi import HTTPException

        def mock_401():
            raise HTTPException(status_code=401, detail="Authentication Failed")

        app.dependency_overrides[get_current_user] = mock_401

        response = client.get("/users/users_list/")

        assert response.status_code == 401
        assert response.json()["detail"] == "Authentication Failed"

    @patch("users.routes.get_user_details")
    def test_user_details_success(self, mock_get_user_details):
        # Mock data
        user_id = 1
        mock_get_user_details.return_value = (1, "testuser", "user")

        # Override dependency
        from auth.auth_tool_functions import get_current_user

        app.dependency_overrides[get_current_user] = lambda: {
            "username": "admin",
            "role": "admin",
        }
        from db.database import get_db

        app.dependency_overrides[get_db] = lambda: MagicMock()

        response = client.get(f"/users/user_details/{user_id}")

        assert response.status_code == 200
        assert response.json() == {"id": 1, "username": "testuser", "role": "user"}
        mock_get_user_details.assert_called_once()

    @patch("users.routes.get_user_details")
    def test_user_details_not_found(self, mock_get_user_details):
        # Mock data
        user_id = 999
        mock_get_user_details.return_value = (None, None, None)

        # Override dependency
        from auth.auth_tool_functions import get_current_user

        app.dependency_overrides[get_current_user] = lambda: {
            "username": "admin",
            "role": "admin",
        }

        response = client.get(f"/users/user_details/{user_id}")

        assert response.status_code == 404
        assert response.json()["detail"] == "User not found"

    def test_get_me_success(self):
        # Override dependency
        from auth.auth_tool_functions import get_current_user

        mock_user = {"id": 1, "username": "me", "role": "user"}
        app.dependency_overrides[get_current_user] = lambda: mock_user
        from db.database import get_db

        app.dependency_overrides[get_db] = lambda: MagicMock()

        response = client.get("/users/me")

        assert response.status_code == 200
        assert response.json() == mock_user

    def test_get_me_unauthorized(self):
        # Override dependency
        from auth.auth_tool_functions import get_current_user
        from fastapi import HTTPException

        def mock_401():
            raise HTTPException(status_code=401, detail="Authentication Failed")

        app.dependency_overrides[get_current_user] = mock_401

        response = client.get("/users/me")

        assert response.status_code == 401
        assert response.json()["detail"] == "Authentication Failed"

    def test_delete_user_success(self):
        mock_db = MagicMock()
        mock_user_to_delete = MagicMock()
        mock_user_to_delete.username = "user_to_delete"
        mock_user_to_delete.id = 2

        mock_db.query.return_value.filter.return_value.first.return_value = (
            mock_user_to_delete
        )

        # Override dependency
        from auth.auth_tool_functions import get_current_user

        app.dependency_overrides[get_current_user] = lambda: {
            "id": 1,
            "username": "admin",
            "role": "admin",
        }
        from db.database import get_db

        app.dependency_overrides[get_db] = lambda: mock_db

        response = client.delete("/users/2")

        assert response.status_code == 200
        assert response.json() == {
            "message": "User successfully deleted",
            "username": "user_to_delete",
        }
        mock_db.delete.assert_called_once_with(mock_user_to_delete)
        mock_db.commit.assert_called_once()

    def test_delete_user_self_deletion(self):
        # Override dependency
        from auth.auth_tool_functions import get_current_user

        app.dependency_overrides[get_current_user] = lambda: {
            "id": 1,
            "username": "admin",
            "role": "admin",
        }

        response = client.delete("/users/1")

        assert response.status_code == 403
        assert response.json()["detail"] == "Cannot delete your own account"

    def test_delete_user_not_found(self):
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None

        # Override dependency
        from auth.auth_tool_functions import get_current_user

        app.dependency_overrides[get_current_user] = lambda: {
            "id": 1,
            "username": "admin",
            "role": "admin",
        }
        from db.database import get_db

        app.dependency_overrides[get_db] = lambda: mock_db

        response = client.delete("/users/999")

        assert response.status_code == 404
        assert response.json()["detail"] == "User not found"

    def test_delete_main_admin(self):
        mock_db = MagicMock()
        mock_admin_user = MagicMock()
        mock_admin_user.username = "admin"
        mock_admin_user.id = 1

        mock_db.query.return_value.filter.return_value.first.return_value = (
            mock_admin_user
        )

        # Override dependency
        from auth.auth_tool_functions import get_current_user

        # Admin trying to delete 'admin' (which is ID 1, but let's say the caller is another admin ID 2)
        app.dependency_overrides[get_current_user] = lambda: {
            "id": 2,
            "username": "other_admin",
            "role": "admin",
        }
        from db.database import get_db

        app.dependency_overrides[get_db] = lambda: mock_db

        response = client.delete("/users/1")

        assert response.status_code == 403
        assert response.json()["detail"] == "Cannot delete the main admin account"
