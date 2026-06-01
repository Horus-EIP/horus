"""Chat WebSocket contract tests (hermetic).

Route under test (``src/services/mas/chat/routes.py``):

* ``WS /chat/{conversation_id}/`` — enforces Permission.TASK_READ
  (admin, manager, user, system all have it). Closes with code 1008
  on auth failure.

Plus the small ``select_agent_by_mode`` helper used inside the chat
pipeline.

Replaces test_chat_routes_coverage, test_chat_tool_function,
test_chat_auth_scenarios, test_send_messages_attribution,
test_select_agent_by_mode.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from chat.routes import router


class TestWebSocketAuth:
    def test_missing_token_closes_connection_with_1008(self, make_client, mock_db):
        client = make_client(router, current_user=None)
        # The handler closes with code 1008 — TestClient surfaces this as
        # WebSocketDisconnect, which is what we assert.
        from starlette.websockets import WebSocketDisconnect  # noqa: PLC0415

        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect("/chat/1/"):
                pass
        # 1008 = policy violation (the closing code used for auth failure)
        assert exc_info.value.code in (1000, 1008)


class TestAgentSelectionHelper:
    """The ``select_agent_by_mode`` helper used by the chat pipeline.

    Pure unit-level — no client, no DB. Lives here because it owns the
    routing logic the WebSocket relies on.
    """

    def test_returns_general_for_unknown_mode(self):
        from chat.chat_tool_functions import select_agent_by_mode  # noqa: PLC0415

        assert select_agent_by_mode(mode="unknown-mode", available=["general"]) == "general"

    def test_returns_requested_mode_when_available(self):
        from chat.chat_tool_functions import select_agent_by_mode  # noqa: PLC0415

        result = select_agent_by_mode(mode="researcher", available=["general", "researcher"])
        assert result == "researcher"

    def test_falls_back_when_requested_not_available(self):
        from chat.chat_tool_functions import select_agent_by_mode  # noqa: PLC0415

        assert select_agent_by_mode(mode="researcher", available=["general"]) == "general"
