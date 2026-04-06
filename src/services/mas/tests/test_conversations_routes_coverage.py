from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from auth.auth_tool_functions import PermissionChecker
from auth.permissions import Permission
from conversations.routes import router

app = FastAPI()
app.include_router(router)

client = TestClient(app)


def raise_401():
    raise HTTPException(status_code=401, detail="Authentication Failed")


class TestConversationsRoutesCoverage:

    @patch("conversations.routes.get_db")
    @patch("conversations.routes.Conversations")
    def test_create_new_conversation_success(self, mock_conversations, mock_get_db):
        mock_db = MagicMock()
        mock_get_db.return_value = mock_db

        mock_conv_instance = MagicMock()
        mock_conv_instance.id = 1
        mock_conversations.return_value = mock_conv_instance

        from db.database import get_db

        app.dependency_overrides[get_db] = lambda: mock_db

        # Override TASK_CREATE for create endpoint
        app.dependency_overrides[PermissionChecker(Permission.TASK_CREATE)] = lambda: {
            "username": "admin",
            "role": "admin",
        }

        response = client.post(
            "/conversations/create-conversation/", json={"name": "New Chat"}
        )

        assert response.status_code == 200
        assert response.json() == {"conversation_id": 1}

    def test_create_new_conversation_no_user_defensive(self):
        # Must raise exception because endpoint expects user dict and crashes if None
        app.dependency_overrides[PermissionChecker(Permission.TASK_CREATE)] = raise_401
        response = client.post(
            "/conversations/create-conversation/", json={"name": "New Chat"}
        )
        assert response.status_code == 401

    @patch("conversations.routes.get_db")
    @patch("conversations.routes.Conversations")
    def test_create_new_conversation_integrity_error(
        self, mock_conversations, mock_get_db
    ):
        app.dependency_overrides[PermissionChecker(Permission.TASK_CREATE)] = lambda: {
            "username": "admin",
            "role": "admin",
        }

        mock_db = MagicMock()
        mock_db.commit.side_effect = IntegrityError(None, None, Exception("Error"))
        mock_db.add.return_value = None  # Ensure add works
        mock_get_db.return_value = mock_db

        from db.database import get_db

        app.dependency_overrides[get_db] = lambda: mock_db

        response = client.post(
            "/conversations/create-conversation/", json={"name": "New Chat"}
        )
        assert response.status_code == 400
        assert "Conversation creation failed" in response.json()["detail"]

    @patch("conversations.routes.get_db")
    @patch("conversations.routes.Conversations")
    def test_create_new_conversation_sqlalchemy_error(
        self, mock_conversations, mock_get_db
    ):
        app.dependency_overrides[PermissionChecker(Permission.TASK_CREATE)] = lambda: {
            "username": "admin",
            "role": "admin",
        }

        mock_db = MagicMock()
        mock_db.commit.side_effect = SQLAlchemyError("DB Error")
        mock_get_db.return_value = mock_db

        from db.database import get_db

        app.dependency_overrides[get_db] = lambda: mock_db

        response = client.post(
            "/conversations/create-conversation/", json={"name": "New Chat"}
        )
        assert response.status_code == 500
        assert "Database error occurred" in response.json()["detail"]

    @patch("conversations.routes.get_db")
    @patch("conversations.routes.Conversations")
    def test_create_new_conversation_generic_error(
        self, mock_conversations, mock_get_db
    ):
        app.dependency_overrides[PermissionChecker(Permission.TASK_CREATE)] = lambda: {
            "username": "admin",
            "role": "admin",
        }

        mock_db = MagicMock()
        mock_db.commit.side_effect = Exception("Generic Error")
        mock_get_db.return_value = mock_db

        from db.database import get_db

        app.dependency_overrides[get_db] = lambda: mock_db

        response = client.post(
            "/conversations/create-conversation/", json={"name": "New Chat"}
        )
        assert response.status_code == 500

    @patch("conversations.routes.get_db")
    @patch("conversations.routes.get_history")
    def test_get_history_success(self, mock_get_history, mock_get_db):
        app.dependency_overrides[PermissionChecker(Permission.TASK_READ)] = lambda: {
            "username": "admin",
            "role": "admin",
        }

        mock_db = MagicMock()
        mock_conv = MagicMock()
        mock_conv.owner_username = "admin"
        mock_db.query.return_value.filter.return_value.first.return_value = mock_conv
        mock_get_db.return_value = mock_db

        from db.database import get_db

        app.dependency_overrides[get_db] = lambda: mock_db

        mock_get_history.return_value = [{"id": 1, "content": "msg"}]

        response = client.get("/conversations/get_history/1")
        assert response.status_code == 200
        assert len(response.json()) == 1

    def test_get_history_no_user_check(self):
        # Override with None to test internal check
        app.dependency_overrides[PermissionChecker(Permission.TASK_READ)] = lambda: None
        response = client.get("/conversations/get_history/1")
        assert response.status_code == 401
        assert response.json()["detail"] == "Authentication Failed"

    @patch("conversations.routes.get_db")
    def test_get_history_not_found(self, mock_get_db):
        app.dependency_overrides[PermissionChecker(Permission.TASK_READ)] = lambda: {
            "username": "admin",
            "role": "admin",
        }

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None
        mock_get_db.return_value = mock_db

        from db.database import get_db

        app.dependency_overrides[get_db] = lambda: mock_db

        response = client.get("/conversations/get_history/1")
        assert response.status_code == 404

    @patch("conversations.routes.get_db")
    def test_get_history_unauthorized(self, mock_get_db):
        app.dependency_overrides[PermissionChecker(Permission.TASK_READ)] = lambda: {
            "username": "other",
            "role": "user",
        }

        mock_db = MagicMock()
        mock_conv = MagicMock()
        mock_conv.owner_username = "admin"  # different owner
        mock_db.query.return_value.filter.return_value.first.return_value = mock_conv
        mock_get_db.return_value = mock_db

        from db.database import get_db

        app.dependency_overrides[get_db] = lambda: mock_db

        response = client.get("/conversations/get_history/1")
        assert response.status_code == 404  # Should be 404 as per implementation

    @patch("conversations.routes.get_db")
    @patch("conversations.routes.get_history")
    def test_get_history_empty(self, mock_get_history, mock_get_db):
        app.dependency_overrides[PermissionChecker(Permission.TASK_READ)] = lambda: {
            "username": "admin",
            "role": "admin",
        }

        mock_db = MagicMock()
        mock_conv = MagicMock()
        mock_conv.owner_username = "admin"
        mock_db.query.return_value.filter.return_value.first.return_value = mock_conv
        mock_get_db.return_value = mock_db

        from db.database import get_db

        app.dependency_overrides[get_db] = lambda: mock_db

        mock_get_history.return_value = []

        response = client.get("/conversations/get_history/1")
        assert response.status_code == 200
        assert response.json() == []

    @patch("conversations.routes.get_db")
    @patch("conversations.routes.get_conversations")
    def test_get_conversation_list_success(self, mock_get_conversations, mock_get_db):
        # Correctly mock USER_READ permission
        app.dependency_overrides[PermissionChecker(Permission.USER_READ)] = lambda: {
            "username": "admin",
            "role": "admin",
        }

        mock_get_conversations.return_value = [{"id": 1, "name": "Chat"}]

        response = client.get("/conversations/get-conversations/")
        assert response.status_code == 200

    def test_get_conversation_list_no_user_check(self):
        app.dependency_overrides[PermissionChecker(Permission.USER_READ)] = lambda: None
        response = client.get("/conversations/get-conversations/")
        assert response.status_code == 401
        assert response.json()["detail"] == "Authentication Failed"

    @patch("conversations.routes.get_db")
    @patch("conversations.routes.get_conversations")
    def test_get_conversation_list_empty(self, mock_get_conversations, mock_get_db):
        app.dependency_overrides[PermissionChecker(Permission.USER_READ)] = lambda: {
            "username": "admin",
            "role": "admin",
        }

        mock_get_conversations.return_value = []

        response = client.get("/conversations/get-conversations/")
        assert response.status_code == 200
        assert response.json() == []

    @patch("conversations.routes.get_db")
    @patch("conversations.routes.get_conversations")
    def test_get_conversation_list_error(self, mock_get_conversations, mock_get_db):
        app.dependency_overrides[PermissionChecker(Permission.USER_READ)] = lambda: {
            "username": "admin",
            "role": "admin",
        }

        mock_get_conversations.side_effect = Exception("Retrieval Error")

        response = client.get("/conversations/get-conversations/")
        assert response.status_code == 500
        assert "Failed to retrieve conversations" in response.json()["detail"]

    @patch("conversations.routes.get_db")
    @patch("conversations.routes.active_connections", new_callable=dict)
    def test_remove_conversation_success(self, mock_active_connections, mock_get_db):
        # Correctly mock TASK_DELETE permission
        app.dependency_overrides[PermissionChecker(Permission.TASK_DELETE)] = lambda: {
            "username": "admin",
            "role": "admin",
        }

        mock_db = MagicMock()
        mock_conv = MagicMock()
        mock_conv.owner_username = "admin"
        mock_db.get.return_value = mock_conv

        from db.database import get_db

        app.dependency_overrides[get_db] = lambda: mock_db

        response = client.delete("/conversations/delete-conversation/1")
        assert response.status_code == 200

    def test_remove_conversation_no_user_check(self):
        app.dependency_overrides[PermissionChecker(Permission.TASK_DELETE)] = (
            lambda: None
        )
        response = client.delete("/conversations/delete-conversation/1")
        assert response.status_code == 401
        assert response.json()["detail"] == "Authentication failed"

    @patch("conversations.routes.get_db")
    def test_remove_conversation_not_found(self, mock_get_db):
        app.dependency_overrides[PermissionChecker(Permission.TASK_DELETE)] = lambda: {
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
    def test_remove_conversation_unauthorized_owner(self, mock_get_db):
        app.dependency_overrides[PermissionChecker(Permission.TASK_DELETE)] = lambda: {
            "username": "other",
            "role": "user",
        }

        mock_db = MagicMock()
        mock_conv = MagicMock()
        mock_conv.owner_username = "admin"
        mock_db.get.return_value = mock_conv

        from db.database import get_db

        app.dependency_overrides[get_db] = lambda: mock_db

        response = client.delete("/conversations/delete-conversation/1")
        assert response.status_code == 404

    @patch("conversations.routes.get_db")
    def test_remove_conversation_integrity_error(self, mock_get_db):
        app.dependency_overrides[PermissionChecker(Permission.TASK_DELETE)] = lambda: {
            "username": "admin",
            "role": "admin",
        }

        mock_db = MagicMock()
        mock_conv = MagicMock()
        mock_conv.owner_username = "admin"
        mock_db.get.return_value = mock_conv
        mock_db.commit.side_effect = IntegrityError(None, None, Exception("FK Error"))

        from db.database import get_db

        app.dependency_overrides[get_db] = lambda: mock_db

        response = client.delete("/conversations/delete-conversation/1")
        assert response.status_code == 409

    @patch("conversations.routes.get_db")
    def test_remove_conversation_sqlalchemy_error(self, mock_get_db):
        app.dependency_overrides[PermissionChecker(Permission.TASK_DELETE)] = lambda: {
            "username": "admin",
            "role": "admin",
        }

        mock_db = MagicMock()
        mock_conv = MagicMock()
        mock_conv.owner_username = "admin"
        mock_db.get.return_value = mock_conv
        mock_db.commit.side_effect = SQLAlchemyError("DB Error")

        from db.database import get_db

        app.dependency_overrides[get_db] = lambda: mock_db

        response = client.delete("/conversations/delete-conversation/1")
        assert response.status_code == 500

    @patch("conversations.routes.get_db")
    def test_remove_conversation_generic_error(self, mock_get_db):
        app.dependency_overrides[PermissionChecker(Permission.TASK_DELETE)] = lambda: {
            "username": "admin",
            "role": "admin",
        }

        mock_db = MagicMock()
        mock_conv = MagicMock()
        mock_conv.owner_username = "admin"
        mock_db.get.return_value = mock_conv
        mock_db.commit.side_effect = Exception("Generic Error")

        from db.database import get_db

        app.dependency_overrides[get_db] = lambda: mock_db

        response = client.delete("/conversations/delete-conversation/1")
        assert response.status_code == 500

    @pytest.mark.asyncio
    @patch("conversations.routes.get_db")
    @patch("conversations.routes.active_connections", new_callable=dict)
    async def test_remove_conversation_with_websocket(
        self, mock_active_connections, mock_get_db
    ):
        # Async test for websocket closing
        app.dependency_overrides[PermissionChecker(Permission.TASK_DELETE)] = lambda: {
            "username": "admin",
            "role": "admin",
        }

        mock_db = MagicMock()
        mock_conv = MagicMock()
        mock_conv.owner_username = "admin"
        mock_db.get.return_value = mock_conv

        from db.database import get_db

        app.dependency_overrides[get_db] = lambda: mock_db

        mock_ws = AsyncMock()
        # IMPORTANT: Populate mock_active_connections dict.
        # But wait, `active_connections.pop` is what is called.
        # Since active_connections is imported from `conversations.routes`, patching it directly works.
        # But we need to use a real dict to make `pop` work OR setup mock `pop` behavior.
        # However, `active_connections` is a module level variable.
        # If I patch it with a dict, I can prepopulate it.

        # But patching dict with `new_callable=dict` makes `active_connections` a NEW empty dict in the test func.
        # Wait, `get_db` patch is standard wrapper. But `active_connections` patch IS effective.

        # So I set item in it.
        mock_active_connections["1"] = {mock_ws}

        # Since client.delete is sync, but the endpoint is async, TestClient handles async loop.
        response = client.delete("/conversations/delete-conversation/1")

        assert response.status_code == 200
        mock_ws.close.assert_called()

    @pytest.mark.asyncio
    @patch("conversations.routes.get_db")
    @patch("conversations.routes.active_connections", new_callable=dict)
    async def test_remove_conversation_websocket_error(
        self, mock_active_connections, mock_get_db
    ):
        app.dependency_overrides[PermissionChecker(Permission.TASK_DELETE)] = lambda: {
            "username": "admin",
            "role": "admin",
        }
        mock_db = MagicMock()
        mock_conv = MagicMock()
        mock_conv.owner_username = "admin"
        mock_db.get.return_value = mock_conv

        from db.database import get_db

        app.dependency_overrides[get_db] = lambda: mock_db

        mock_ws = AsyncMock()
        mock_ws.close.side_effect = Exception("WS Close Error")
        mock_active_connections["1"] = {mock_ws}

        response = client.delete("/conversations/delete-conversation/1")
        assert response.status_code == 200
        # Should still succeed but log warning

    @patch("conversations.routes.get_db")
    @patch("conversations.routes.active_connections")
    def test_remove_conversation_websocket_critical_error(
        self, mock_active_connections, mock_get_db
    ):
        app.dependency_overrides[PermissionChecker(Permission.TASK_DELETE)] = lambda: {
            "username": "admin",
            "role": "admin",
        }
        mock_db = MagicMock()
        mock_conv = MagicMock()
        mock_conv.owner_username = "admin"
        mock_db.get.return_value = mock_conv

        from db.database import get_db

        app.dependency_overrides[get_db] = lambda: mock_db

        mock_active_connections.pop.side_effect = Exception("Critical WS Error")

        response = client.delete("/conversations/delete-conversation/1")
        assert response.status_code == 200
