from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from users.routes import router

app = FastAPI()
app.include_router(router)

client = TestClient(app)


class TestUsersRoutesCoverage:

    @patch("users.routes.get_db")
    def test_update_role_success(self, mock_get_db):
        mock_db = MagicMock()
        mock_get_db.return_value = mock_db

        # Mock query chain
        mock_query = mock_db.query.return_value
        mock_filter = mock_query.filter.return_value

        # First call checks for existing user with role (return None)
        # Second call checks for target user (return User object)
        mock_user = MagicMock()
        mock_filter.first.side_effect = [None, mock_user]

        # We need to override the dependency for get_db
        from db.database import get_db

        app.dependency_overrides[get_db] = lambda: mock_db

        # We need to override the dependency for get_current_user
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
        assert mock_user.role == "admin"
        mock_db.commit.assert_called_once()

    @patch("users.routes.get_db")
    def test_update_role_already_has_role(self, mock_get_db):
        mock_db = MagicMock()
        mock_query = mock_db.query.return_value
        mock_filter = mock_query.filter.return_value

        # First call finds existing user with role
        mock_filter.first.return_value = MagicMock()

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

        assert response.status_code == 403
        assert "User already has role admin" in response.json()["detail"]

    @patch("users.routes.get_db")
    def test_update_role_user_not_found(self, mock_get_db):
        mock_db = MagicMock()
        mock_query = mock_db.query.return_value
        mock_filter = mock_query.filter.return_value

        # First call (existing user with role) -> None
        # Second call (target user) -> None
        mock_filter.first.side_effect = [None, None]

        from db.database import get_db

        app.dependency_overrides[get_db] = lambda: mock_db
        from auth.auth_tool_functions import get_current_user

        app.dependency_overrides[get_current_user] = lambda: {
            "username": "admin",
            "role": "admin",
        }

        response = client.post(
            "/users/update_role",
            json={"user_id": "unknownuser", "new_role": "admin"},
        )

        assert response.status_code == 404
        assert "User not found" in response.json()["detail"]
