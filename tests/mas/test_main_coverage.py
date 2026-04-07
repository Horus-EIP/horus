from unittest.mock import patch

from fastapi.testclient import TestClient

from auth.auth_tool_functions import get_current_user
from main import app

client = TestClient(app)


def test_root_endpoint_success():
    # Override dependency to simulate authenticated user
    app.dependency_overrides[get_current_user] = lambda: {
        "username": "testuser",
        "role": "user",
    }

    response = client.get("/")

    assert response.status_code == 200
    assert response.json()["message"] == "Authentification succeed"
    assert response.json()["User"]["username"] == "testuser"

    # Clean up
    app.dependency_overrides = {}


def test_root_endpoint_unauthenticated():
    # Override dependency to simulate NO user (None)
    app.dependency_overrides[get_current_user] = lambda: None

    response = client.get("/")

    assert response.status_code == 401
    assert response.json()["detail"] == "Not authenticated"

    # Clean up
    app.dependency_overrides = {}
