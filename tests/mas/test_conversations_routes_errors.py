import os
from unittest.mock import MagicMock, patch

import pytest

# Disable LLM auto-initialization before importing main
os.environ["LLM_AUTOINIT"] = "0"

from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from auth.auth_tool_functions import get_current_user
from db.database import get_db
from main import app

client = TestClient(app)

# Mock user
mock_user = {
    "username": "testuser",
    "id": 1,
    "email": "test@example.com",
    "role": "admin",
}


def override_get_current_user():
    return mock_user


app.dependency_overrides[get_current_user] = override_get_current_user


def test_create_conversation_integrity_error():
    mock_db = MagicMock()
    mock_db.add.side_effect = IntegrityError("mock", "mock", "mock")

    app.dependency_overrides[get_db] = lambda: mock_db

    response = client.post(
        "/conversations/create-conversation/", json={"name": "Test Conversation"}
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Conversation creation failed"


def test_create_conversation_sqlalchemy_error():
    mock_db = MagicMock()
    mock_db.add.side_effect = SQLAlchemyError("Database error")

    app.dependency_overrides[get_db] = lambda: mock_db

    response = client.post(
        "/conversations/create-conversation/", json={"name": "Test Conversation"}
    )

    assert response.status_code == 500
    assert response.json()["detail"] == "Error: Database error occurred"


def test_create_conversation_generic_exception():
    mock_db = MagicMock()
    mock_db.add.side_effect = Exception("Unexpected error")

    app.dependency_overrides[get_db] = lambda: mock_db

    response = client.post(
        "/conversations/create-conversation/", json={"name": "Test Conversation"}
    )

    assert response.status_code == 500
    assert "Error: Unexpected error" in response.json()["detail"]


def test_remove_conversation_integrity_error():
    mock_db = MagicMock()
    mock_conv = MagicMock()
    mock_conv.owner_username = "testuser"
    mock_db.get.return_value = mock_conv
    mock_db.delete.side_effect = IntegrityError("mock", "mock", "mock")

    app.dependency_overrides[get_db] = lambda: mock_db

    response = client.delete("/conversations/delete-conversation/1")

    assert response.status_code == 409
    assert response.json()["detail"] == "Conversation has dependent records"


def test_remove_conversation_sqlalchemy_error():
    mock_db = MagicMock()
    mock_conv = MagicMock()
    mock_conv.owner_username = "testuser"
    mock_db.get.return_value = mock_conv
    mock_db.delete.side_effect = SQLAlchemyError("Database error")

    app.dependency_overrides[get_db] = lambda: mock_db

    response = client.delete("/conversations/delete-conversation/1")

    assert response.status_code == 500
    assert response.json()["detail"] == "Error: Database error occurred"


def test_remove_conversation_generic_exception():
    mock_db = MagicMock()
    mock_conv = MagicMock()
    mock_conv.owner_username = "testuser"
    mock_db.get.return_value = mock_conv
    mock_db.delete.side_effect = Exception("Unexpected error")

    app.dependency_overrides[get_db] = lambda: mock_db

    response = client.delete("/conversations/delete-conversation/1")

    assert response.status_code == 500
    assert "Error: Unexpected error" in response.json()["detail"]


def test_get_conversation_list_exception():
    # We need to mock get_conversations from conversations.conversation_tool_functions
    with patch("conversations.routes.get_conversations") as mock_get_conversations:
        mock_get_conversations.side_effect = Exception("Unexpected error")

        response = client.get("/conversations/get-conversations/")

        assert response.status_code == 500
        assert response.json()["detail"] == "Error: Failed to retrieve conversations"


def test_remove_conversation_websocket_error():
    mock_db = MagicMock()
    mock_conv = MagicMock()
    mock_conv.owner_username = "testuser"
    mock_db.get.return_value = mock_conv

    app.dependency_overrides[get_db] = lambda: mock_db

    # Mock active_connections to simulate websocket error
    with patch("conversations.routes.active_connections") as mock_active_connections:
        mock_ws = MagicMock()
        mock_ws.close.side_effect = Exception("WebSocket error")
        mock_active_connections.pop.return_value = {mock_ws}

        response = client.delete("/conversations/delete-conversation/1")

        assert response.status_code == 200
        assert response.json() == {"message": "Conversation correctly deleted"}
