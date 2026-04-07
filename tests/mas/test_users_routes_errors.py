from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from auth.auth_tool_functions import get_current_user
from db.database import get_db
from users.routes import router

app = FastAPI()
app.include_router(router)

client = TestClient(app)

# Mock admin user
mock_admin = {"username": "admin", "id": 1, "role": "admin"}


def override_get_current_user():
    return mock_admin


app.dependency_overrides[get_current_user] = override_get_current_user


def test_update_role_exception():
    mock_db = MagicMock()
    mock_db.query.side_effect = Exception("DB Error")

    app.dependency_overrides[get_db] = lambda: mock_db

    response = client.post(
        "/users/update_role",
        json={"user_id": "testuser", "new_role": "admin"},
    )

    assert response.status_code == 500
    assert "Error: DB Error" in response.json()["detail"]
