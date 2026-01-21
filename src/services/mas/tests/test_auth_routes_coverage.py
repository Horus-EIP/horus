from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from auth.routes import router

app = FastAPI()
app.include_router(router)

client = TestClient(app)


class TestAuthRoutesCoverage:

    @patch("auth.routes.bcrypt_context")
    @patch("auth.routes.Users")
    def test_create_user_success(self, mock_users, mock_bcrypt):
        mock_db = MagicMock()
        mock_bcrypt.hash.return_value = "hashed_password"

        # Mock the dependency injection for db
        app.dependency_overrides = {}  # Reset overrides
        # We can't easily override the db dependency here because it's used in the route function signature
        # But we can mock the db session object if we could inject it.
        # Instead, let's rely on patching the db dependency if possible, or mocking the session operations.

        # Since `db: db_dependency` is used, we need to override it.
        from db.dependency import get_db

        app.dependency_overrides[get_db] = lambda: mock_db

        response = client.post(
            "/auth/register", json={"username": "newuser", "password": "password123"}
        )

        assert response.status_code == 201
        mock_db.add.assert_called_once()
        mock_db.commit.assert_called_once()
        mock_db.refresh.assert_called_once()

    @patch("auth.routes.bcrypt_context")
    @patch("auth.routes.Users")
    def test_create_user_conflict(self, mock_users, mock_bcrypt):
        from sqlalchemy.exc import IntegrityError

        mock_db = MagicMock()
        mock_bcrypt.hash.return_value = "hashed_password"

        # Simulate IntegrityError on commit
        mock_db.commit.side_effect = IntegrityError(
            None, None, Exception("UNIQUE constraint failed")
        )

        from db.dependency import get_db

        app.dependency_overrides[get_db] = lambda: mock_db

        response = client.post(
            "/auth/register",
            json={"username": "existinguser", "password": "password123"},
        )

        assert response.status_code == 409
        assert "User Registration Error" in response.json()["detail"]
        mock_db.rollback.assert_called_once()

    @patch("auth.routes.authenticate_user")
    @patch("auth.routes.create_access_token")
    def test_login_for_access_token_success(self, mock_create_token, mock_authenticate):
        mock_db = MagicMock()
        from db.dependency import get_db

        app.dependency_overrides[get_db] = lambda: mock_db

        mock_user = MagicMock()
        mock_user.username = "user"
        mock_user.id = 1
        mock_user.role = "user"
        mock_authenticate.return_value = mock_user

        mock_create_token.return_value = "access_token"

        response = client.post(
            "/auth/token", data={"username": "user", "password": "password"}
        )

        assert response.status_code == 200
        assert response.json() == {
            "access_token": "access_token",
            "token_type": "bearer",
        }

    @patch("auth.routes.authenticate_user")
    def test_login_for_access_token_failure(self, mock_authenticate):
        mock_db = MagicMock()
        from db.dependency import get_db

        app.dependency_overrides[get_db] = lambda: mock_db

        mock_authenticate.return_value = False

        response = client.post(
            "/auth/token", data={"username": "user", "password": "wrongpassword"}
        )

        assert response.status_code == 401

    @patch("auth.routes.get_current_user")
    @patch("auth.routes.redis_db")
    def test_user_logout_success(self, mock_redis, mock_get_user):
        # Mock get_current_user dependency
        from auth.auth_tool_functions import get_current_user

        app.dependency_overrides[get_current_user] = lambda: {
            "sub": "user",
            "exp": int((datetime.now() + timedelta(minutes=10)).timestamp()),
            "nonce": "nonce123",
        }

        from datetime import datetime

        response = client.post("/auth/logout")

        assert response.status_code == 200
        assert response.json() == {"message": "Successfully logout"}
        mock_redis.setex.assert_called_once()
