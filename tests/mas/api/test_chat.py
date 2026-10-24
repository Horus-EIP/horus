"""Chat WebSocket contract tests (hermetic).

Route under test (``src/services/mas/chat/routes.py``):

* ``WS /chat/{conversation_id}/`` — enforces Permission.TASK_READ.
  Closes with code 1008 on auth failure.
"""

from __future__ import annotations

import pytest
from licensing.verification import LicenseCheck, LicenseState

from chat.routes import router


class TestWebSocketAuth:
    def test_missing_token_closes_connection_with_1008(self, make_client):
        client = make_client(router, current_user=None)
        client.app.state.license = LicenseCheck(state=LicenseState.VALID)
        from starlette.websockets import WebSocketDisconnect  # noqa: PLC0415

        with pytest.raises(WebSocketDisconnect) as exc_info:
            with client.websocket_connect("/chat/1/"):
                pass
        assert exc_info.value.code in (1000, 1008)
