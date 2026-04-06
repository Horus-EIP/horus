from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI, WebSocket
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from chat.routes import router
from db.dependency import get_db

app = FastAPI()
app.include_router(router)

mock_db_session = MagicMock()


def override_get_db():
    try:
        yield mock_db_session
    finally:
        pass


app.dependency_overrides[get_db] = override_get_db

client = TestClient(app)


class TestChatRoutesCoverage:

    @patch("chat.routes._extract_token_from_ws")
    @patch("chat.routes.get_current_user_from_token")
    @patch("chat.routes.save_new_client")
    @patch("chat.routes.delete_client")
    @patch("chat.routes.check_permission")
    def test_chat_websocket_success(
        self, mock_perm, mock_delete, mock_save, mock_get_user, mock_extract
    ):
        mock_extract.return_value = "valid_token"
        mock_get_user.return_value = {
            "id": 1,
            "username": "user",
            "payload": {"role": "user"},
        }
        mock_perm.return_value = True
        mock_save.return_value = "session_id"

        # Mock DB conversation
        mock_conversation = MagicMock()
        mock_conversation.owner_username = "user"
        mock_conversation.id = 123
        mock_db_session.query.return_value.filter.return_value.first.return_value = (
            mock_conversation
        )

        with client.websocket_connect("/chat/123/?token=valid_token") as websocket:
            websocket.send_text("Hello")

        mock_save.assert_called_once()
        mock_delete.assert_called_once()

    @patch("chat.routes._extract_token_from_ws")
    def test_chat_websocket_auth_fail(self, mock_extract):
        mock_extract.side_effect = Exception("Invalid token")

        with pytest.raises(WebSocketDisconnect) as exc:
            with client.websocket_connect("/chat/123/?token=invalid"):
                pass
        assert exc.value.code == 1008

    @patch("chat.routes._extract_token_from_ws")
    @patch("chat.routes.get_current_user_from_token")
    @patch("chat.routes.save_new_client")
    @patch("chat.routes.delete_client")
    @patch("chat.routes.check_permission")
    def test_chat_websocket_disconnect(
        self, mock_perm, mock_delete, mock_save, mock_get_user, mock_extract
    ):
        mock_extract.return_value = "valid_token"
        mock_get_user.return_value = {
            "id": 1,
            "username": "user",
            "payload": {"role": "user"},
        }
        mock_perm.return_value = True
        mock_save.return_value = "session_id"

        mock_conversation = MagicMock()
        mock_conversation.owner_username = "user"
        mock_conversation.id = 123
        mock_db_session.query.return_value.filter.return_value.first.return_value = (
            mock_conversation
        )

        with client.websocket_connect("/chat/123/?token=valid_token") as websocket:
            websocket.close()

    @patch("chat.routes._extract_token_from_ws")
    @patch("chat.routes.get_current_user_from_token")
    @patch("chat.routes.check_permission")
    def test_permission_failure(self, mock_perm, mock_get_user, mock_extract):
        mock_extract.return_value = "valid_token"
        mock_get_user.return_value = {
            "id": 1,
            "username": "user",
            "payload": {"role": "user"},
        }
        mock_perm.return_value = False  # Insufficient permissions

        with pytest.raises(WebSocketDisconnect) as exc:
            with client.websocket_connect("/chat/123/?token=valid_token"):
                pass
        assert exc.value.code == 1008

    @patch("chat.routes._extract_token_from_ws")
    @patch("chat.routes.get_current_user_from_token")
    @patch("chat.routes.check_permission")
    def test_invalid_conversation_id(self, mock_perm, mock_get_user, mock_extract):
        mock_extract.return_value = "valid_token"
        mock_get_user.return_value = {
            "id": 1,
            "username": "user",
            "payload": {"role": "user"},
        }
        mock_perm.return_value = True

        with pytest.raises(WebSocketDisconnect) as exc:
            with client.websocket_connect("/chat/not-int/?token=valid_token"):
                pass
        assert exc.value.code == 1008

    @patch("chat.routes._extract_token_from_ws")
    @patch("chat.routes.get_current_user_from_token")
    @patch("chat.routes.check_permission")
    def test_conversation_not_found(self, mock_perm, mock_get_user, mock_extract):
        mock_extract.return_value = "valid_token"
        mock_get_user.return_value = {
            "id": 1,
            "username": "user",
            "payload": {"role": "user"},
        }
        mock_perm.return_value = True

        mock_db_session.query.return_value.filter.return_value.first.return_value = None

        with pytest.raises(WebSocketDisconnect) as exc:
            with client.websocket_connect("/chat/999/?token=valid_token"):
                pass
        assert exc.value.code == 1008

    @patch("chat.routes._extract_token_from_ws")
    @patch("chat.routes.get_current_user_from_token")
    @patch("chat.routes.check_permission")
    def test_unauthorized_access(self, mock_perm, mock_get_user, mock_extract):
        mock_extract.return_value = "valid_token"
        mock_get_user.return_value = {
            "id": 2,
            "username": "other",
            "payload": {"role": "user"},
        }
        mock_perm.return_value = True

        mock_conversation = MagicMock()
        mock_conversation.owner_username = "owner"
        mock_db_session.query.return_value.filter.return_value.first.return_value = (
            mock_conversation
        )

        with pytest.raises(WebSocketDisconnect) as exc:
            with client.websocket_connect("/chat/123/?token=valid_token"):
                pass
        assert exc.value.code == 1008
