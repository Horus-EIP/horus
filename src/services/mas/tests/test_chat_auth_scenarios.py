from unittest.mock import MagicMock, patch
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from chat.routes import router
from db.dependency import get_db
from auth.permissions import Role

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

class TestChatAuthScenarios:

    @patch("chat.routes._extract_token_from_ws")
    @patch("chat.routes.get_current_user_from_token")
    def test_websocket_insufficient_permissions(self, mock_get_user, mock_extract):
        """Test that connection is rejected if user lacks TASK_READ permission"""
        mock_extract.return_value = "valid_token"
        # Use a role that definitely doesn't have TASK_READ. 
        # If "guest" isn't in Role enum, check_permission returns False.
        mock_get_user.return_value = {
            "id": 999,
            "username": "guest_user",
            "payload": {"role": "guest"},
        }

        with pytest.raises(WebSocketDisconnect) as exc:
            with client.websocket_connect("/chat/123/?token=valid_token"):
                pass
        assert exc.value.code == 1008

    @patch("chat.routes._extract_token_from_ws")
    @patch("chat.routes.get_current_user_from_token")
    def test_websocket_invalid_conversation_id(self, mock_get_user, mock_extract):
        """Test that connection is rejected if conversation_id is not an integer"""
        mock_extract.return_value = "valid_token"
        mock_get_user.return_value = {
            "id": 1,
            "username": "user",
            "payload": {"role": "user"},
        }

        with pytest.raises(WebSocketDisconnect) as exc:
            with client.websocket_connect("/chat/not-an-int/?token=valid_token"):
                pass
        assert exc.value.code == 1008

    @patch("chat.routes._extract_token_from_ws")
    @patch("chat.routes.get_current_user_from_token")
    def test_websocket_conversation_not_found(self, mock_get_user, mock_extract):
        """Test that connection is rejected if conversation does not exist"""
        mock_extract.return_value = "valid_token"
        mock_get_user.return_value = {
            "id": 1,
            "username": "user",
            "payload": {"role": "user"},
        }
        
        # Mock DB to return None
        mock_db_session.query.return_value.filter.return_value.first.return_value = None

        with pytest.raises(WebSocketDisconnect) as exc:
            with client.websocket_connect("/chat/999/?token=valid_token"):
                pass
        assert exc.value.code == 1008

    @patch("chat.routes._extract_token_from_ws")
    @patch("chat.routes.get_current_user_from_token")
    def test_websocket_unauthorized_access(self, mock_get_user, mock_extract):
        """Test that connection is rejected if user is not owner and not admin"""
        mock_extract.return_value = "valid_token"
        mock_get_user.return_value = {
            "id": 2,
            "username": "attacker",
            "payload": {"role": "user"},
        }
        
        # Mock DB conversation owned by someone else
        mock_conversation = MagicMock()
        mock_conversation.owner_username = "victim"
        mock_conversation.id = 123
        mock_db_session.query.return_value.filter.return_value.first.return_value = mock_conversation

        with pytest.raises(WebSocketDisconnect) as exc:
            with client.websocket_connect("/chat/123/?token=valid_token"):
                pass
        assert exc.value.code == 1008

    @patch("chat.routes._extract_token_from_ws")
    @patch("chat.routes.get_current_user_from_token")
    @patch("chat.routes.save_new_client")
    @patch("chat.routes.delete_client")
    def test_websocket_success_admin_access(self, mock_delete, mock_save, mock_get_user, mock_extract):
        """Test that admin can access any conversation"""
        mock_extract.return_value = "valid_token"
        mock_get_user.return_value = {
            "id": 1,
            "username": "admin_user",
            "payload": {"role": "admin"},
        }
        mock_save.return_value = "session_id"
        
        # Mock DB conversation owned by someone else
        mock_conversation = MagicMock()
        mock_conversation.owner_username = "victim"
        mock_conversation.id = 123
        mock_db_session.query.return_value.filter.return_value.first.return_value = mock_conversation

        with client.websocket_connect("/chat/123/?token=valid_token") as websocket:
            websocket.send_text("Hello")

        mock_save.assert_called_once()
