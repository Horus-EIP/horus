import datetime as dt

import pytest

import chat.chat_tool_functions as wsmod


# --------- Dummy WebSocket ---------
class DummyWebSocket:
    def __init__(self, name="ws"):
        self.name = name
        self.sent = []

    async def send_json(self, payload):
        self.sent.append(payload)


# --------- Fixtures ---------
@pytest.fixture(autouse=True)
def clean_state(monkeypatch):
    monkeypatch.setattr(wsmod, "active_connections", {}, raising=True)
    yield
    wsmod.active_connections.clear()


# --------- Tests: save_new_client ---------
def test_save_new_client_appends_to_active_connections(caplog):
    conv_id = "conv-1"
    wsmod.active_connections[conv_id] = []
    ws = DummyWebSocket("ws1")

    session_id = wsmod.save_new_client(conv_id, ws, user_id=1, token="test-token")

    assert wsmod.active_connections[conv_id] == [ws]
    assert session_id is not None
    assert any(
        "WebSocket connected" in record.message and conv_id in record.message
        for record in caplog.records
    )


def test_save_new_client_creates_conversation_list_if_missing(caplog):
    """Test that save_new_client creates a conversation list if it doesn't exist"""
    conv_id = "new-conv"
    ws = DummyWebSocket("ws1")

    # Ensure the conversation doesn't exist initially
    assert conv_id not in wsmod.active_connections

    session_id = wsmod.save_new_client(conv_id, ws, user_id=1, token="test-token")

    # Should create the conversation and add the websocket
    assert conv_id in wsmod.active_connections
    assert wsmod.active_connections[conv_id] == [ws]
    assert session_id is not None
    assert any(
        "WebSocket connected" in record.message and conv_id in record.message
        for record in caplog.records
    )


# --------- Tests: delete_client ---------
def test_delete_client_removes_when_present(caplog):
    conv_id = "conv-2"
    ws1, ws2 = DummyWebSocket("ws1"), DummyWebSocket("ws2")
    wsmod.active_connections[conv_id] = [ws1, ws2]

    wsmod.delete_client(conv_id, ws1, session_id="session-1")

    assert ws1 not in wsmod.active_connections[conv_id]
    assert ws2 in wsmod.active_connections[conv_id]
    assert any(
        "WebSocket disconnected" in record.message and conv_id in record.message
        for record in caplog.records
    )


def test_delete_client_is_noop_when_not_present():
    conv_id = "conv-3"
    ws = DummyWebSocket("ws")
    wsmod.active_connections[conv_id] = []

    wsmod.delete_client(conv_id, ws, session_id="session-2")
    assert wsmod.active_connections[conv_id] == []


def test_delete_client_is_noop_when_conv_absent():
    wsmod.delete_client("no-such-conv", DummyWebSocket(), session_id="session-3")


# --------- Tests: send_messages_via_websockets ---------
@pytest.mark.asyncio
async def test_send_messages_sends_to_all_clients_and_formats_payload():
    conv_id = "conv-4"
    ws1, ws2 = DummyWebSocket("ws1"), DummyWebSocket("ws2")
    wsmod.active_connections[conv_id] = [ws1, ws2]

    msg = "Hello, world!"
    await wsmod.send_messages_via_websockets(conv_id, msg)

    assert len(ws1.sent) == 1 and len(ws2.sent) == 1

    for payload in (ws1.sent[0], ws2.sent[0]):
        assert payload["type"] == "agent"
        assert payload["content"] == msg
        # valid ISO timestamp
        ts = dt.datetime.fromisoformat(payload["timestamp"])
        assert isinstance(ts, dt.datetime)


@pytest.mark.asyncio
async def test_send_messages_handles_unknown_conversation_gracefully():
    """Test that send_messages_via_websockets handles unknown conversations without error"""
    # This should not raise an error anymore since the function uses .get() with default
    await wsmod.send_messages_via_websockets("unknown-conv", "test message")


@pytest.mark.asyncio
async def test_send_messages_with_no_clients_listed():
    conv_id = "conv-5"
    wsmod.active_connections[conv_id] = []
    await wsmod.send_messages_via_websockets(conv_id, "msg")


@pytest.mark.asyncio
async def test_send_message_websocket_connection_removal_error():
    """Test that ValueError when removing websocket connection is handled gracefully."""

    class FailingWebSocket(DummyWebSocket):
        async def send_json(self, payload):
            raise Exception("Connection error")

    failing_ws = FailingWebSocket("failing")
    working_ws = DummyWebSocket("working")

    # Set up connections with failing websocket
    wsmod.active_connections["test_conv"] = [failing_ws, working_ws]

    # Mock the connections list to raise ValueError on remove
    original_conns = wsmod.active_connections["test_conv"]

    class MockList(list):
        def remove(self, item):
            raise ValueError("WebSocket not in list")

    mock_conns = MockList([failing_ws, working_ws])
    wsmod.active_connections["test_conv"] = mock_conns

    # This should not raise an exception even if remove fails
    await wsmod.send_messages_via_websockets("test_conv", "test_message")

    # The working websocket should still receive the message
    assert len(working_ws.sent) == 1
    assert working_ws.sent[0]["content"] == "test_message"

    # Clean up
    wsmod.active_connections["test_conv"] = original_conns


def test_save_new_client_duplicate_websocket_not_added():
    """Test that duplicate websockets are not added twice"""
    conv_id = "conv-dup"
    ws = DummyWebSocket("dup-ws")
    wsmod.active_connections[conv_id] = [ws]

    # Try to add the same websocket again
    session_id = wsmod.save_new_client(conv_id, ws, user_id=1, token="test-token")

    # Should still only have one instance
    assert wsmod.active_connections[conv_id].count(ws) == 1
    assert session_id is not None


def test_delete_client_removes_conversation_when_empty(caplog):
    """Test that conversation is removed when no clients remain"""
    conv_id = "conv-empty"
    ws = DummyWebSocket("single-ws")
    wsmod.active_connections[conv_id] = [ws]

    wsmod.delete_client(conv_id, ws, session_id="session-4")

    # Conversation should be completely removed
    assert conv_id not in wsmod.active_connections
    assert any("WebSocket disconnected" in record.message for record in caplog.records)


def test_extract_token_from_ws_with_query_param():
    """Test token extraction from query parameter"""
    from unittest.mock import MagicMock

    ws = MagicMock()

    token = wsmod._extract_token_from_ws(ws, "test-token-123")
    assert token == "test-token-123"


def test_extract_token_from_ws_with_bearer_header():
    """Test token extraction from Authorization header"""
    from unittest.mock import MagicMock

    from fastapi import WebSocketException

    ws = MagicMock()
    ws.headers.get.return_value = "Bearer valid-token-456"

    token = wsmod._extract_token_from_ws(ws, None)
    assert token == "valid-token-456"


def test_extract_token_from_ws_with_invalid_auth_scheme():
    """Test token extraction with invalid auth scheme"""
    from unittest.mock import MagicMock

    from fastapi import WebSocketException

    ws = MagicMock()
    ws.headers.get.return_value = "Basic invalid-scheme"

    with pytest.raises(WebSocketException):
        wsmod._extract_token_from_ws(ws, None)


def test_extract_token_from_ws_no_token_provided():
    """Test token extraction when no token is provided"""
    from unittest.mock import MagicMock

    from fastapi import WebSocketException

    ws = MagicMock()
    ws.headers.get.return_value = None

    with pytest.raises(WebSocketException):
        wsmod._extract_token_from_ws(ws, None)


# --------- Tests: get_active_sessions ---------
def test_get_active_sessions_returns_empty_list_when_no_sessions():
    """Test that get_active_sessions returns empty list when no sessions exist"""
    from unittest.mock import MagicMock, patch

    with patch.object(wsmod, "redis_db") as mock_redis:
        mock_redis.smembers.return_value = set()

        sessions = wsmod.get_active_sessions("conv-1")

        assert sessions == []
        mock_redis.smembers.assert_called_once_with("conversation_sessions:conv-1")


def test_get_active_sessions_returns_active_sessions():
    """Test that get_active_sessions returns all active sessions for a conversation"""
    import json
    from unittest.mock import MagicMock, patch

    session_1 = {
        "conversation_id": "conv-1",
        "user_id": 1,
        "token": "token-1",
        "connected_at": "2025-11-17T14:00:00",
        "session_id": "session-1",
    }

    session_2 = {
        "conversation_id": "conv-1",
        "user_id": 2,
        "token": "token-2",
        "connected_at": "2025-11-17T14:05:00",
        "session_id": "session-2",
    }

    with patch.object(wsmod, "redis_db") as mock_redis:
        mock_redis.smembers.return_value = {"session-1", "session-2"}
        mock_redis.get.side_effect = [json.dumps(session_1), json.dumps(session_2)]

        sessions = wsmod.get_active_sessions("conv-1")

        assert len(sessions) == 2
        assert session_1 in sessions
        assert session_2 in sessions
        mock_redis.smembers.assert_called_once_with("conversation_sessions:conv-1")


def test_get_active_sessions_skips_missing_session_data():
    """Test that get_active_sessions skips sessions with missing data"""
    import json
    from unittest.mock import MagicMock, patch

    session_1 = {
        "conversation_id": "conv-1",
        "user_id": 1,
        "token": "token-1",
        "connected_at": "2025-11-17T14:00:00",
        "session_id": "session-1",
    }

    with patch.object(wsmod, "redis_db") as mock_redis:
        # session-1 exists, session-2 is missing (None)
        mock_redis.smembers.return_value = {"session-1", "session-2"}
        mock_redis.get.side_effect = [
            json.dumps(session_1),  # session-1 data
            None,  # session-2 data (missing)
        ]

        sessions = wsmod.get_active_sessions("conv-1")

        # Should only return the existing session
        assert len(sessions) == 1
        assert session_1 in sessions


def test_get_active_sessions_with_multiple_conversations():
    """Test that get_active_sessions only returns sessions for the specified conversation"""
    import json
    from unittest.mock import MagicMock, patch

    session_conv1 = {
        "conversation_id": "conv-1",
        "user_id": 1,
        "token": "token-1",
        "session_id": "session-1",
    }

    with patch.object(wsmod, "redis_db") as mock_redis:
        mock_redis.smembers.return_value = {"session-1"}
        mock_redis.get.return_value = json.dumps(session_conv1)

        sessions = wsmod.get_active_sessions("conv-1")

        assert len(sessions) == 1
        assert sessions[0]["conversation_id"] == "conv-1"
        mock_redis.smembers.assert_called_with("conversation_sessions:conv-1")


def test_get_active_sessions_returns_list_of_dicts():
    """Test that get_active_sessions returns a list of dictionaries"""
    import json
    from unittest.mock import MagicMock, patch

    session_data = {
        "conversation_id": "conv-1",
        "user_id": 1,
        "token": "test-token",
        "connected_at": "2025-11-17T14:00:00",
        "session_id": "session-1",
    }

    with patch.object(wsmod, "redis_db") as mock_redis:
        mock_redis.smembers.return_value = {"session-1"}
        mock_redis.get.return_value = json.dumps(session_data)

        sessions = wsmod.get_active_sessions("conv-1")

        assert isinstance(sessions, list)
        assert len(sessions) == 1
        assert isinstance(sessions[0], dict)
        assert sessions[0] == session_data
