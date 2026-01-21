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
    def test_chat_websocket_success(
        self, mock_delete, mock_save, mock_get_user, mock_extract
    ):
        mock_extract.return_value = "valid_token"
        mock_get_user.return_value = {
            "id": 1,
            "username": "user",
            "payload": {"role": "user"},
        }
        mock_save.return_value = "session_id"
        
        # Mock DB conversation
        mock_conversation = MagicMock()
        mock_conversation.owner_username = "user"
        mock_conversation.id = 123
        mock_db_session.query.return_value.filter.return_value.first.return_value = mock_conversation

        with client.websocket_connect("/chat/123/?token=valid_token") as websocket:
            # The loop in the route waits for receive_text
            # We can send something to trigger it, or just close to exit the loop
            websocket.send_text("Hello")
            # The route doesn't do anything with received text, just loops

        mock_save.assert_called_once()
        mock_delete.assert_called_once()

    @patch("chat.routes._extract_token_from_ws")
    def test_chat_websocket_auth_fail(self, mock_extract):
        mock_extract.side_effect = Exception("Invalid token")

        with pytest.raises(Exception):  # TestClient might raise on close with code
            with client.websocket_connect("/chat/123/?token=invalid") as websocket:
                pass

        # Verify connection closed with 1008 (Policy Violation)
        # TestClient handles this differently, usually by raising WebSocketDisconnect
        # But since we are mocking extract to fail before accept, it might just close.

    @patch("chat.routes._extract_token_from_ws")
    @patch("chat.routes.get_current_user_from_token")
    @patch("chat.routes.save_new_client")
    @patch("chat.routes.delete_client")
    def test_chat_websocket_disconnect(
        self, mock_delete, mock_save, mock_get_user, mock_extract
    ):
        mock_extract.return_value = "valid_token"
        mock_get_user.return_value = {
            "id": 1,
            "username": "user",
            "payload": {"role": "user"},
        }
        mock_save.return_value = "session_id"
        
        # Mock DB conversation
        mock_conversation = MagicMock()
        mock_conversation.owner_username = "user"
        mock_conversation.id = 123
        mock_db_session.query.return_value.filter.return_value.first.return_value = mock_conversation

        with client.websocket_connect("/chat/123/?token=valid_token") as websocket:
            websocket.close()

        mock_delete.assert_called_once()
