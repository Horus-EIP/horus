from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from conversations.routes import router

app = FastAPI()
app.include_router(router)

client = TestClient(app)


class TestConversationsRoutesCoverage:

    @patch("conversations.routes.get_db")
    @patch("conversations.routes.Conversations")
    def test_create_new_conversation_success(self, mock_conversations, mock_get_db):
        from auth.auth_tool_functions import get_current_user

        app.dependency_overrides[get_current_user] = lambda: {
            "username": "admin",
            "role": "admin",
        }

        mock_db = MagicMock()
        mock_get_db.return_value = mock_db

        mock_conv_instance = MagicMock()
        mock_conv_instance.id = 1
        mock_conversations.return_value = mock_conv_instance

        from db.database import get_db

        app.dependency_overrides[get_db] = lambda: mock_db

        response = client.post(
            "/conversations/create-conversation/", json={"name": "New Chat"}
        )

        assert response.status_code == 200
        assert response.json() == {"conversation_id": 1}
        mock_db.add.assert_called_once()
        mock_db.commit.assert_called_once()

    @patch("conversations.routes.get_db")
    @patch("conversations.routes.Conversations")
    def test_create_new_conversation_integrity_error(
        self, mock_conversations, mock_get_db
    ):
        from sqlalchemy.exc import IntegrityError

        from auth.auth_tool_functions import get_current_user

        app.dependency_overrides[get_current_user] = lambda: {
            "username": "admin",
            "role": "admin",
        }

        mock_db = MagicMock()
        mock_db.commit.side_effect = IntegrityError(None, None, Exception("Error"))

        from db.database import get_db

        app.dependency_overrides[get_db] = lambda: mock_db

        response = client.post(
            "/conversations/create-conversation/", json={"name": "New Chat"}
        )

        assert response.status_code == 400
        assert "Conversation creation failed" in response.json()["detail"]

    @patch("conversations.routes.get_db")
    @patch("conversations.routes.get_history")
    def test_get_conversation_history_success(self, mock_get_history, mock_get_db):
        from auth.auth_tool_functions import get_current_user

        app.dependency_overrides[get_current_user] = lambda: {
            "username": "admin",
            "role": "admin",
        }

        mock_db = MagicMock()
        mock_conv = MagicMock()
        mock_conv.owner_username = "admin"
        mock_db.query.return_value.filter.return_value.first.return_value = mock_conv
        
        from db.database import get_db
        app.dependency_overrides[get_db] = lambda: mock_db

        mock_get_history.return_value = [{"id": 1, "content": "Hello"}]

        response = client.get("/conversations/get_history/1")

        assert response.status_code == 200
        assert len(response.json()) == 1

    @patch("conversations.routes.get_db")
    @patch("conversations.routes.get_conversations")
    def test_get_conversation_list_success(self, mock_get_conversations, mock_get_db):
        from auth.auth_tool_functions import get_current_user

        app.dependency_overrides[get_current_user] = lambda: {
            "username": "admin",
            "role": "admin",
        }

        mock_get_conversations.return_value = [{"id": 1, "name": "Chat"}]

        response = client.get("/conversations/get-conversations/")

        assert response.status_code == 200
        assert len(response.json()) == 1

    @patch("conversations.routes.get_db")
    @patch("conversations.routes.active_connections", new_callable=dict)
    def test_remove_conversation_success(self, mock_active_connections, mock_get_db):
        from auth.auth_tool_functions import get_current_user

        app.dependency_overrides[get_current_user] = lambda: {
            "username": "admin",
            "role": "admin",
        }

        mock_db = MagicMock()
        mock_conv = MagicMock()
        mock_conv.owner_username = "admin"
        mock_db.get.return_value = mock_conv

        from db.database import get_db

        app.dependency_overrides[get_db] = lambda: mock_db

        # Mock active connections
        mock_ws = MagicMock()
        mock_active_connections["1"] = {mock_ws}

        response = client.delete("/conversations/delete-conversation/1")

        assert response.status_code == 200
        assert response.json() == {"message": "Conversation correctly deleted"}
        mock_db.delete.assert_called_once()
        # Verify websocket close called (async mock needed if we want to be strict, but standard mock might fail await)
        # Since remove_conversation is async, and it awaits ws.close(), we need ws.close to be awaitable.
        # But here we are mocking active_connections dict.

    @patch("conversations.routes.get_db")
    def test_remove_conversation_not_found(self, mock_get_db):
        from auth.auth_tool_functions import get_current_user

        app.dependency_overrides[get_current_user] = lambda: {
            "username": "admin",
            "role": "admin",
        }

        mock_db = MagicMock()
        mock_db.get.return_value = None

        from db.database import get_db

        app.dependency_overrides[get_db] = lambda: mock_db

        response = client.delete("/conversations/delete-conversation/1")

        assert response.status_code == 404

    @patch("conversations.routes.get_db")
    def test_remove_conversation_not_owner(self, mock_get_db):
        from auth.auth_tool_functions import get_current_user

        app.dependency_overrides[get_current_user] = lambda: {
            "username": "manager",
            "role": "manager",
        }

        mock_db = MagicMock()
        mock_conv = MagicMock()
        mock_conv.owner_username = "otheruser"
        mock_db.get.return_value = mock_conv

        from db.database import get_db

        app.dependency_overrides[get_db] = lambda: mock_db

        response = client.delete("/conversations/delete-conversation/1")

        assert response.status_code == 404

    @patch("conversations.routes.get_db")
    def test_remove_conversation_admin_can_delete_others(self, mock_get_db):
        from auth.auth_tool_functions import get_current_user

        app.dependency_overrides[get_current_user] = lambda: {
            "username": "admin",
            "role": "admin",
        }

        mock_db = MagicMock()
        mock_conv = MagicMock()
        mock_conv.owner_username = "otheruser"
        mock_db.get.return_value = mock_conv

        from db.database import get_db

        app.dependency_overrides[get_db] = lambda: mock_db

        response = client.delete("/conversations/delete-conversation/1")

        assert response.status_code == 200
