"""Coverage-focused tests for the MAS chat + conversations modules (hermetic).

Targets (line + branch):

* ``conversations/conversation_tool_functions.py`` — persistence helpers
  (``get_history`` / ``get_full_history`` / ``get_conversations`` /
  ``get_all_conversations`` / ``add_messages``).
* ``chat/chat_tool_functions.py`` — WebSocket broadcast + Redis session
  bookkeeping helpers.
* ``chat/routes.py`` — the ``/chat/{conversation_id}/`` WebSocket endpoint.
* ``conversations/routes.py`` — conversation CRUD + history HTTP routes.

Everything here is in-process: the DB is a ``MagicMock`` (or in-memory
fakes), Redis is patched per-test, and no RabbitMQ / LLM / live socket is
touched. All patches auto-revert (``monkeypatch`` / ``unittest.mock.patch``),
so no global / env / ``sys.modules`` state leaks between tests.
"""

from __future__ import annotations

import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

import chat.chat_tool_functions as ctf
import conversations.conversation_tool_functions as conv_tf
from auth.auth_tool_functions import get_current_user
from auth.permissions import Permission
from chat.routes import router as chat_router
from conversations.routes import router as conv_router

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _make_msg(
    *,
    mid: int = 1,
    role: str = "user",
    content: str = "hello",
    created_at: datetime.datetime | None = None,
    agent_id: str | None = None,
    agent_name: str | None = None,
    skill_used: str | None = None,
    sources: list[dict] | None = None,
) -> MagicMock:
    """Build a Messages-shaped mock with ``.isoformat()``-capable timestamp."""
    msg = MagicMock()
    msg.id = mid
    msg.role = role
    msg.content = content
    msg.created_at = created_at
    msg.agent_id = agent_id
    msg.agent_name = agent_name
    msg.skill_used = skill_used
    msg.sources = sources
    return msg


def _make_conv(
    *,
    cid: int = 1,
    name: str = "chat",
    owner_username: str = "user",
    created_at: datetime.datetime | None = None,
    modified_at: datetime.datetime | None = None,
) -> MagicMock:
    conv = MagicMock()
    conv.id = cid
    conv.name = name
    conv.owner_username = owner_username
    conv.created_at = created_at
    conv.modified_at = modified_at
    return conv


# =========================================================================== #
# conversations/conversation_tool_functions.py
# =========================================================================== #


class TestGetHistory:
    def test_returns_messages_chronologically(self, mock_db):
        ts = datetime.datetime(2026, 1, 1, 12, 0, 0)
        conv = _make_conv()
        msgs = [
            _make_msg(mid=1, role="user", content="hi", created_at=ts),
            _make_msg(
                mid=2,
                role="assistant",
                content="yo",
                created_at=ts,
                agent_id="a-1",
                agent_name="Manager",
                skill_used="chat",
                sources=[{"doc_id": "d1", "chunk_id": "d1:0", "title": "q4.md", "page": None}],
            ),
        ]
        # First query() -> Conversations lookup; second -> Messages ordered.
        mock_db.query.return_value.filter.return_value.first.return_value = conv
        mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = (
            msgs
        )

        out = conv_tf.get_history(1, mock_db)

        assert len(out) == 2
        assert out[0] == {
            "id": 1,
            "role": "user",
            "content": "hi",
            "created_at": ts.isoformat(),
            "agent_id": None,
            "agent_name": None,
            "skill_used": None,
            "sources": None,
        }
        assert out[1]["agent_name"] == "Manager"
        assert out[1]["skill_used"] == "chat"
        assert out[1]["sources"] == [
            {"doc_id": "d1", "chunk_id": "d1:0", "title": "q4.md", "page": None}
        ]

    def test_handles_null_created_at(self, mock_db):
        conv = _make_conv()
        mock_db.query.return_value.filter.return_value.first.return_value = conv
        mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = [
            _make_msg(created_at=None)
        ]
        out = conv_tf.get_history(1, mock_db)
        assert out[0]["created_at"] is None

    def test_missing_conversation_returns_empty(self, mock_db):
        mock_db.query.return_value.filter.return_value.first.return_value = None
        assert conv_tf.get_history(404, mock_db) == []

    def test_empty_messages_returns_empty(self, mock_db):
        conv = _make_conv()
        mock_db.query.return_value.filter.return_value.first.return_value = conv
        mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = (
            []
        )
        assert conv_tf.get_history(1, mock_db) == []

    def test_sqlalchemy_error_returns_empty(self, mock_db):
        mock_db.query.side_effect = SQLAlchemyError("boom")
        assert conv_tf.get_history(1, mock_db) == []

    def test_unexpected_error_returns_empty(self, mock_db):
        mock_db.query.side_effect = RuntimeError("kaboom")
        assert conv_tf.get_history(1, mock_db) == []

    def test_opens_and_closes_own_session_when_db_is_none(self):
        """db=None triggers the SessionLocal()/close() branch + finally."""
        fake_db = MagicMock()
        fake_db.query.return_value.filter.return_value.first.return_value = None
        with patch.object(conv_tf, "SessionLocal", return_value=fake_db) as sl:
            out = conv_tf.get_history(1, None)
        assert out == []
        sl.assert_called_once()
        fake_db.close.assert_called_once()


class TestGetFullHistory:
    def test_passthrough_with_supplied_db(self, mock_db):
        mock_db.query.return_value.filter.return_value.first.return_value = None
        assert conv_tf.get_full_history(7, mock_db) == []

    def test_opens_session_when_db_none(self):
        fake_db = MagicMock()
        fake_db.query.return_value.filter.return_value.first.return_value = None
        with patch.object(conv_tf, "SessionLocal", return_value=fake_db) as sl:
            assert conv_tf.get_full_history(7, None) == []
        sl.assert_called_once()


class TestGetConversations:
    def test_returns_user_conversations(self, mock_db):
        ts = datetime.datetime(2026, 2, 2, 9, 0, 0)
        convs = [_make_conv(cid=1, name="a", created_at=ts, modified_at=ts)]
        mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = (
            convs
        )
        out = conv_tf.get_conversations("user", mock_db)
        assert out == [
            {
                "id": 1,
                "name": "a",
                "owner_username": "user",
                "created_at": ts.isoformat(),
                "modified_at": ts.isoformat(),
            }
        ]

    def test_empty_list(self, mock_db):
        mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = (
            []
        )
        assert conv_tf.get_conversations("nobody", mock_db) == []

    def test_null_timestamps(self, mock_db):
        mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = [
            _make_conv(created_at=None, modified_at=None)
        ]
        out = conv_tf.get_conversations("user", mock_db)
        assert out[0]["created_at"] is None and out[0]["modified_at"] is None

    def test_sqlalchemy_error_returns_empty(self, mock_db):
        mock_db.query.side_effect = SQLAlchemyError("db")
        assert conv_tf.get_conversations("user", mock_db) == []

    def test_unexpected_error_returns_empty(self, mock_db):
        mock_db.query.side_effect = ValueError("x")
        assert conv_tf.get_conversations("user", mock_db) == []

    def test_opens_session_when_db_none(self):
        fake_db = MagicMock()
        fake_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = (
            []
        )
        with patch.object(conv_tf, "SessionLocal", return_value=fake_db) as sl:
            assert conv_tf.get_conversations("user", None) == []
        sl.assert_called_once()
        fake_db.close.assert_called_once()


class TestGetAllConversations:
    def test_returns_all(self, mock_db):
        ts = datetime.datetime(2026, 3, 3, 8, 0, 0)
        mock_db.query.return_value.order_by.return_value.all.return_value = [
            _make_conv(cid=5, name="z", created_at=ts, modified_at=ts)
        ]
        out = conv_tf.get_all_conversations(mock_db)
        assert out[0]["id"] == 5 and out[0]["name"] == "z"

    def test_empty(self, mock_db):
        mock_db.query.return_value.order_by.return_value.all.return_value = []
        assert conv_tf.get_all_conversations(mock_db) == []

    def test_null_timestamps(self, mock_db):
        mock_db.query.return_value.order_by.return_value.all.return_value = [
            _make_conv(created_at=None, modified_at=None)
        ]
        out = conv_tf.get_all_conversations(mock_db)
        assert out[0]["created_at"] is None and out[0]["modified_at"] is None

    def test_sqlalchemy_error_returns_empty(self, mock_db):
        mock_db.query.side_effect = SQLAlchemyError("db")
        assert conv_tf.get_all_conversations(mock_db) == []

    def test_unexpected_error_returns_empty(self, mock_db):
        mock_db.query.side_effect = RuntimeError("x")
        assert conv_tf.get_all_conversations(mock_db) == []

    def test_opens_session_when_db_none(self):
        fake_db = MagicMock()
        fake_db.query.return_value.order_by.return_value.all.return_value = []
        with patch.object(conv_tf, "SessionLocal", return_value=fake_db) as sl:
            assert conv_tf.get_all_conversations(None) == []
        sl.assert_called_once()
        fake_db.close.assert_called_once()


class TestAddMessages:
    def test_success_returns_message_dict(self, mock_db):
        ts = datetime.datetime(2026, 4, 4, 7, 0, 0)
        conv = _make_conv()
        mock_db.query.return_value.filter.return_value.first.return_value = conv

        def _refresh(msg):
            msg.id = 99
            msg.created_at = ts

        mock_db.refresh.side_effect = _refresh

        out = conv_tf.add_messages(
            "assistant",
            "answer",
            1,
            mock_db,
            agent_id="a-9",
            agent_name="Specialist",
            skill_used="search",
        )
        assert out["id"] == 99
        assert out["role"] == "assistant"
        assert out["content"] == "answer"
        assert out["created_at"] == ts.isoformat()
        assert out["agent_id"] == "a-9"
        assert out["agent_name"] == "Specialist"
        assert out["skill_used"] == "search"
        mock_db.begin_nested.return_value.commit.assert_called_once()
        mock_db.commit.assert_called_once()

    def test_success_null_created_at(self, mock_db):
        conv = _make_conv()
        mock_db.query.return_value.filter.return_value.first.return_value = conv

        def _refresh(msg):
            msg.id = 1
            msg.created_at = None

        mock_db.refresh.side_effect = _refresh
        out = conv_tf.add_messages("user", "hi", 1, mock_db)
        assert out["created_at"] is None
        assert out["agent_id"] is None

    def test_missing_conversation_returns_none(self, mock_db):
        mock_db.query.return_value.filter.return_value.first.return_value = None
        assert conv_tf.add_messages("user", "hi", 404, mock_db) is None

    def test_sqlalchemy_error_rolls_back_and_returns_none(self, mock_db):
        conv = _make_conv()
        mock_db.query.return_value.filter.return_value.first.return_value = conv
        savepoint = MagicMock()
        mock_db.begin_nested.return_value = savepoint
        # Fail on the main commit, after the savepoint was created.
        mock_db.commit.side_effect = SQLAlchemyError("commit failed")

        assert conv_tf.add_messages("user", "hi", 1, mock_db) is None
        savepoint.rollback.assert_called_once()
        mock_db.rollback.assert_called_once()

    def test_sqlalchemy_error_swallows_rollback_failures(self, mock_db):
        """Both savepoint.rollback and db.rollback raising must not propagate."""
        conv = _make_conv()
        mock_db.query.return_value.filter.return_value.first.return_value = conv
        savepoint = MagicMock()
        savepoint.rollback.side_effect = RuntimeError("sp rollback boom")
        mock_db.begin_nested.return_value = savepoint
        mock_db.commit.side_effect = SQLAlchemyError("commit failed")
        mock_db.rollback.side_effect = RuntimeError("db rollback boom")

        assert conv_tf.add_messages("user", "hi", 1, mock_db) is None

    def test_unexpected_error_rolls_back_and_returns_none(self, mock_db):
        conv = _make_conv()
        mock_db.query.return_value.filter.return_value.first.return_value = conv
        savepoint = MagicMock()
        mock_db.begin_nested.return_value = savepoint
        mock_db.refresh.side_effect = RuntimeError("weird")

        assert conv_tf.add_messages("user", "hi", 1, mock_db) is None
        savepoint.rollback.assert_called_once()
        mock_db.rollback.assert_called_once()

    def test_unexpected_error_swallows_rollback_failures(self, mock_db):
        conv = _make_conv()
        mock_db.query.return_value.filter.return_value.first.return_value = conv
        savepoint = MagicMock()
        savepoint.rollback.side_effect = RuntimeError("sp boom")
        mock_db.begin_nested.return_value = savepoint
        mock_db.refresh.side_effect = RuntimeError("weird")
        mock_db.rollback.side_effect = RuntimeError("db boom")

        assert conv_tf.add_messages("user", "hi", 1, mock_db) is None

    def test_sqlalchemy_error_before_savepoint_skips_savepoint_rollback(self, mock_db):
        """Error during the conversation lookup -> savepoint is still None,
        so only db.rollback() runs (covers the ``if savepoint`` false branch)."""
        mock_db.query.return_value.filter.return_value.first.side_effect = (
            SQLAlchemyError("lookup failed")
        )
        assert conv_tf.add_messages("user", "hi", 1, mock_db) is None
        mock_db.begin_nested.assert_not_called()
        mock_db.rollback.assert_called_once()

    def test_unexpected_error_before_savepoint_skips_savepoint_rollback(self, mock_db):
        mock_db.query.return_value.filter.return_value.first.side_effect = RuntimeError(
            "lookup boom"
        )
        assert conv_tf.add_messages("user", "hi", 1, mock_db) is None
        mock_db.begin_nested.assert_not_called()
        mock_db.rollback.assert_called_once()

    def test_opens_session_when_db_none(self):
        fake_db = MagicMock()
        fake_db.query.return_value.filter.return_value.first.return_value = None
        with patch.object(conv_tf, "SessionLocal", return_value=fake_db) as sl:
            assert conv_tf.add_messages("user", "hi", 1, None) is None
        sl.assert_called_once()
        fake_db.close.assert_called_once()


# =========================================================================== #
# chat/chat_tool_functions.py
# =========================================================================== #


@pytest.fixture(autouse=True)
def _clean_active_connections():
    """Keep the module-level registry empty before/after each test."""
    ctf.active_connections.clear()
    yield
    ctf.active_connections.clear()


def _fake_ws() -> MagicMock:
    ws = MagicMock()
    ws.send_json = AsyncMock()
    return ws


class TestAgentMessagePayload:
    def test_legacy_agent_payload_without_attribution(self):
        payload = ctf.agent_message_payload("plain")
        assert payload["type"] == "agent"
        assert payload["content"] == "plain"
        assert "agent_id" not in payload

    def test_task_complete_payload_with_attribution(self):
        payload = ctf.agent_message_payload(
            "done", agent_id="a1", agent_name="Mgr", skill_used="sk"
        )
        assert payload["type"] == "task_complete"
        assert payload["agent_id"] == "a1"
        assert payload["agent_name"] == "Mgr"
        assert payload["skill_used"] == "sk"


class TestTaskStepPayload:
    def test_full_step_payload(self):
        step = {
            "task_id": "t-1",
            "agent_id": "a-1",
            "agent_name": "Mgr",
            "step_type": "thinking",
            "title": "Planning",
            "detail": "details here",
            "timestamp": "2026-01-01T00:00:00",
            "metadata": {"k": "v"},
        }
        payload = ctf.task_step_payload(step)
        assert payload["type"] == "task_step"
        assert payload["task_id"] == "t-1"
        assert payload["title"] == "Planning"
        assert payload["metadata"] == {"k": "v"}
        assert payload["timestamp"] == "2026-01-01T00:00:00"

    def test_the_subtask_that_emitted_the_step_is_forwarded(self):
        payload = ctf.task_step_payload({"task_id": "root-1", "subtask_id": "step-2"})
        assert payload["task_id"] == "root-1"
        assert payload["subtask_id"] == "step-2"

    def test_defaults_timestamp_and_metadata(self):
        payload = ctf.task_step_payload({"task_id": "t"})
        assert payload["metadata"] == {}
        assert isinstance(payload["timestamp"], str) and payload["timestamp"]


class TestBroadcastToConversation:
    async def test_no_connections_is_noop(self):
        await ctf.broadcast_to_conversation("1", {"type": "agent"})

    async def test_every_socket_of_the_conversation_receives_the_payload(self):
        first, second, other = _fake_ws(), _fake_ws(), _fake_ws()
        ctf.active_connections["1"] = [first, second]
        ctf.active_connections["2"] = [other]
        await ctf.broadcast_to_conversation(1, {"type": "agent", "content": "hi"})
        first.send_json.assert_awaited_once_with({"type": "agent", "content": "hi"})
        second.send_json.assert_awaited_once_with({"type": "agent", "content": "hi"})
        other.send_json.assert_not_awaited()

    async def test_dead_socket_is_removed(self):
        bad = _fake_ws()
        bad.send_json.side_effect = RuntimeError("closed")
        good = _fake_ws()
        ctf.active_connections["1"] = [bad, good]
        await ctf.broadcast_to_conversation("1", {"type": "agent"})
        assert bad not in ctf.active_connections["1"]
        assert good in ctf.active_connections["1"]

    async def test_dead_socket_already_gone_is_swallowed(self):
        bad = _fake_ws()
        conns: list = []

        async def _send(_payload):
            if bad in conns:
                conns.remove(bad)
            raise RuntimeError("closed")

        bad.send_json.side_effect = _send
        conns.append(bad)
        ctf.active_connections["1"] = conns
        await ctf.broadcast_to_conversation("1", {"type": "agent"})


class TestConnectedConversationIds:
    def test_lists_only_conversations_with_an_open_socket(self):
        ctf.active_connections["1"] = [_fake_ws()]
        ctf.active_connections["2"] = []
        assert ctf.connected_conversation_ids() == ["1"]


class TestSaveNewClient:
    def test_registers_socket_and_persists_session(self):
        ws = _fake_ws()
        fake_redis = MagicMock()
        with patch.object(ctf, "redis_db", fake_redis):
            session_id = ctf.save_new_client(
                5, ws, "u-1", "tok", username="user", role="user"
            )
        assert isinstance(session_id, str) and session_id
        assert ws in ctf.active_connections["5"]
        fake_redis.setex.assert_called_once()
        key, ttl, _payload = fake_redis.setex.call_args.args
        assert key == f"ws_session:{session_id}"
        assert ttl == 3600
        fake_redis.sadd.assert_called_once_with(
            "conversation_sessions:5", session_id
        )

    def test_does_not_duplicate_existing_socket(self):
        ws = _fake_ws()
        ctf.active_connections["5"] = [ws]
        fake_redis = MagicMock()
        with patch.object(ctf, "redis_db", fake_redis):
            ctf.save_new_client(5, ws, "u-1", "tok")
        assert ctf.active_connections["5"].count(ws) == 1


class TestDeleteClient:
    def test_no_connection_list_is_noop(self):
        fake_redis = MagicMock()
        with patch.object(ctf, "redis_db", fake_redis):
            ctf.delete_client("123", _fake_ws(), "sess")
        fake_redis.delete.assert_not_called()

    def test_removes_socket_and_cleans_redis(self):
        ws = _fake_ws()
        ctf.active_connections["5"] = [ws]
        fake_redis = MagicMock()
        with patch.object(ctf, "redis_db", fake_redis):
            ctf.delete_client(5, ws, "sess-1")
        # Last socket removed -> key popped from the registry entirely.
        assert "5" not in ctf.active_connections
        fake_redis.delete.assert_called_once_with("ws_session:sess-1")
        fake_redis.srem.assert_called_once_with(
            "conversation_sessions:5", "sess-1"
        )

    def test_keeps_list_when_other_sockets_remain(self):
        ws1, ws2 = _fake_ws(), _fake_ws()
        ctf.active_connections["5"] = [ws1, ws2]
        fake_redis = MagicMock()
        with patch.object(ctf, "redis_db", fake_redis):
            ctf.delete_client(5, ws1, "sess-1")
        assert ctf.active_connections["5"] == [ws2]

    def test_socket_not_in_list_still_cleans_redis(self):
        ws_known, ws_unknown = _fake_ws(), _fake_ws()
        ctf.active_connections["5"] = [ws_known]
        fake_redis = MagicMock()
        with patch.object(ctf, "redis_db", fake_redis):
            ctf.delete_client(5, ws_unknown, "sess-2")
        # ws_unknown wasn't in the list, so the known socket stays.
        assert ctf.active_connections["5"] == [ws_known]
        fake_redis.delete.assert_called_once_with("ws_session:sess-2")


class TestGetActiveSessions:
    def test_returns_decoded_sessions(self):
        fake_redis = MagicMock()
        fake_redis.smembers.return_value = {"s1", "s2"}

        def _get(key):
            if key == "ws_session:s1":
                return '{"session_id": "s1"}'
            if key == "ws_session:s2":
                return None  # stale pointer -> skipped
            return None

        fake_redis.get.side_effect = _get
        with patch.object(ctf, "redis_db", fake_redis):
            out = ctf.get_active_sessions(5)
        assert out == [{"session_id": "s1"}]

    def test_empty_when_no_sessions(self):
        fake_redis = MagicMock()
        fake_redis.smembers.return_value = set()
        with patch.object(ctf, "redis_db", fake_redis):
            assert ctf.get_active_sessions("5") == []


class TestExtractTokenFromWs:
    def test_prefers_query_param(self):
        ws = MagicMock()
        assert ctf._extract_token_from_ws(ws, "qtok") == "qtok"

    def test_falls_back_to_bearer_header(self):
        ws = MagicMock()
        ws.headers = {"Authorization": "Bearer header-tok"}
        assert ctf._extract_token_from_ws(ws, None) == "header-tok"

    def test_raises_when_no_token(self):
        from fastapi import WebSocketException  # noqa: PLC0415

        ws = MagicMock()
        ws.headers = {}
        with pytest.raises(WebSocketException):
            ctf._extract_token_from_ws(ws, None)

    def test_raises_when_non_bearer_scheme(self):
        from fastapi import WebSocketException  # noqa: PLC0415

        ws = MagicMock()
        ws.headers = {"Authorization": "Basic abc"}
        with pytest.raises(WebSocketException):
            ctf._extract_token_from_ws(ws, None)


# =========================================================================== #
# chat/routes.py — WebSocket endpoint
# =========================================================================== #


def _token_user(role: str = "user", username: str = "user", uid: str = "3") -> dict:
    """Shape returned by get_current_user_from_token (note nested payload.role)."""
    return {"id": uid, "username": username, "payload": {"role": role}}


class TestChatWebSocketRoute:
    def test_missing_token_closes_1008(self, make_client):
        from starlette.websockets import WebSocketDisconnect  # noqa: PLC0415

        client = make_client(chat_router)
        with pytest.raises(WebSocketDisconnect) as exc:
            with client.websocket_connect("/chat/1/"):
                pass
        assert exc.value.code == 1008

    def test_insufficient_permission_closes_1008(self, make_client, mock_db):
        from starlette.websockets import WebSocketDisconnect  # noqa: PLC0415

        client = make_client(chat_router)
        # "guest" maps to no role -> check_permission(TASK_READ) is False.
        with patch(
            "chat.routes.get_current_user_from_token",
            return_value=_token_user(role="guest"),
        ):
            with pytest.raises(WebSocketDisconnect) as exc:
                with client.websocket_connect("/chat/1/?token=abc"):
                    pass
        assert exc.value.code == 1008

    def test_invalid_conversation_id_closes_1008(self, make_client, mock_db):
        from starlette.websockets import WebSocketDisconnect  # noqa: PLC0415

        client = make_client(chat_router)
        with patch(
            "chat.routes.get_current_user_from_token",
            return_value=_token_user(role="user"),
        ):
            with pytest.raises(WebSocketDisconnect) as exc:
                with client.websocket_connect("/chat/not-an-int/?token=abc"):
                    pass
        assert exc.value.code == 1008

    def test_conversation_not_found_closes_1008(self, make_client, mock_db):
        from starlette.websockets import WebSocketDisconnect  # noqa: PLC0415

        mock_db.query.return_value.filter.return_value.first.return_value = None
        client = make_client(chat_router)
        with patch(
            "chat.routes.get_current_user_from_token",
            return_value=_token_user(role="user"),
        ):
            with pytest.raises(WebSocketDisconnect) as exc:
                with client.websocket_connect("/chat/1/?token=abc"):
                    pass
        assert exc.value.code == 1008

    def test_unauthorized_non_owner_non_admin_closes_1008(self, make_client, mock_db):
        from starlette.websockets import WebSocketDisconnect  # noqa: PLC0415

        conv = _make_conv(owner_username="someone-else")
        mock_db.query.return_value.filter.return_value.first.return_value = conv
        client = make_client(chat_router)
        with patch(
            "chat.routes.get_current_user_from_token",
            return_value=_token_user(role="user", username="user"),
        ):
            with pytest.raises(WebSocketDisconnect) as exc:
                with client.websocket_connect("/chat/1/?token=abc"):
                    pass
        assert exc.value.code == 1008

    def test_auth_raises_exception_closes_1008(self, make_client, mock_db):
        from starlette.websockets import WebSocketDisconnect  # noqa: PLC0415

        client = make_client(chat_router)
        # token decode raising is caught by the outer try -> 1008.
        with patch(
            "chat.routes.get_current_user_from_token",
            side_effect=RuntimeError("bad token"),
        ):
            with pytest.raises(WebSocketDisconnect) as exc:
                with client.websocket_connect("/chat/1/?token=abc"):
                    pass
        assert exc.value.code == 1008

    def test_owner_connects_and_cleans_up_on_disconnect(self, make_client, mock_db):
        conv = _make_conv(owner_username="user")
        mock_db.query.return_value.filter.return_value.first.return_value = conv
        client = make_client(chat_router)

        fake_save = MagicMock(return_value="sess-xyz")
        fake_delete = MagicMock()
        with (
            patch(
                "chat.routes.get_current_user_from_token",
                return_value=_token_user(role="user", username="user", uid="3"),
            ),
            patch("chat.routes.save_new_client", fake_save),
            patch("chat.routes.delete_client", fake_delete),
        ):
            with client.websocket_connect("/chat/1/?token=abc") as ws:
                ws.send_text("ping")
            # Context exit closes the socket -> receive loop ends -> cleanup.
        fake_save.assert_called_once()
        fake_delete.assert_called_once()
        # delete_client is called with the session id returned by save_new_client.
        assert fake_delete.call_args.args[2] == "sess-xyz"

    def test_falsy_session_id_skips_cleanup_in_finally(self, make_client, mock_db):
        """If save_new_client returns a falsy session id, the finally's
        ``if session_id`` guard is False and delete_client is never called
        (covers the 104->exit branch)."""
        conv = _make_conv(owner_username="user")
        mock_db.query.return_value.filter.return_value.first.return_value = conv
        client = make_client(chat_router)
        fake_delete = MagicMock()
        with (
            patch(
                "chat.routes.get_current_user_from_token",
                return_value=_token_user(role="user", username="user", uid="3"),
            ),
            patch("chat.routes.save_new_client", MagicMock(return_value=None)),
            patch("chat.routes.delete_client", fake_delete),
        ):
            with client.websocket_connect("/chat/1/?token=abc") as ws:
                ws.send_text("ping")
        fake_delete.assert_not_called()

    def test_admin_can_connect_to_foreign_conversation(self, make_client, mock_db):
        conv = _make_conv(owner_username="someone-else")
        mock_db.query.return_value.filter.return_value.first.return_value = conv
        client = make_client(chat_router)
        fake_save = MagicMock(return_value="sess-admin")
        fake_delete = MagicMock()
        with (
            patch(
                "chat.routes.get_current_user_from_token",
                return_value=_token_user(role="admin", username="admin", uid="1"),
            ),
            patch("chat.routes.save_new_client", fake_save),
            patch("chat.routes.delete_client", fake_delete),
        ):
            with client.websocket_connect("/chat/1/?token=abc") as ws:
                ws.send_text("hello")
        fake_save.assert_called_once()
        fake_delete.assert_called_once()


# =========================================================================== #
# conversations/routes.py — HTTP routes
# =========================================================================== #


def _guest_user() -> dict:
    """A user whose role grants none of the conversation permissions -> 403."""
    return {"id": 9, "user_id": "9", "username": "guest", "role": "guest"}


class TestCreateConversationRoute:
    def test_success(self, make_client, mock_db, as_user):
        def _refresh(conv):
            conv.id = 42

        mock_db.refresh.side_effect = _refresh
        client = make_client(conv_router, current_user=as_user)
        r = client.post("/conversations/create-conversation/", json={"name": "My chat"})
        assert r.status_code == 200
        assert r.json() == {"conversation_id": 42}
        mock_db.add.assert_called_once()
        mock_db.commit.assert_called_once()

    def test_requires_auth_401(self, make_client, mock_db):
        client = make_client(conv_router)
        r = client.post("/conversations/create-conversation/", json={"name": "x"})
        assert r.status_code == 401

    def test_forbidden_403(self, make_client, mock_db):
        client = make_client(conv_router, current_user=_guest_user())
        r = client.post("/conversations/create-conversation/", json={"name": "x"})
        assert r.status_code == 403

    def test_missing_name_422(self, make_client, mock_db, as_user):
        client = make_client(conv_router, current_user=as_user)
        r = client.post("/conversations/create-conversation/", json={})
        assert r.status_code == 422

    def test_integrity_error_400(self, make_client, mock_db, as_user):
        mock_db.commit.side_effect = IntegrityError("stmt", {}, Exception("dup"))
        client = make_client(conv_router, current_user=as_user)
        r = client.post("/conversations/create-conversation/", json={"name": "x"})
        assert r.status_code == 400
        assert r.json()["detail"] == "Conversation creation failed"
        mock_db.rollback.assert_called_once()

    def test_sqlalchemy_error_500(self, make_client, mock_db, as_user):
        mock_db.commit.side_effect = SQLAlchemyError("db down")
        client = make_client(conv_router, current_user=as_user)
        r = client.post("/conversations/create-conversation/", json={"name": "x"})
        assert r.status_code == 500
        assert r.json()["detail"] == "Error: Database error occurred"

    def test_unexpected_error_500(self, make_client, mock_db, as_user):
        mock_db.commit.side_effect = RuntimeError("boom")
        client = make_client(conv_router, current_user=as_user)
        r = client.post("/conversations/create-conversation/", json={"name": "x"})
        assert r.status_code == 500
        assert r.json()["detail"].startswith("Error: ")


class TestGetHistoryRoute:
    def test_owner_success_returns_history(self, make_client, mock_db, as_user):
        conv = _make_conv(owner_username="user")
        ts = datetime.datetime(2026, 5, 5, 6, 0, 0)
        msgs = [_make_msg(mid=1, role="user", content="hi", created_at=ts)]
        # First query().filter().first() -> ownership check (conv).
        mock_db.query.return_value.filter.return_value.first.return_value = conv
        # get_history's second query() (ordered messages).
        mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = (
            msgs
        )
        client = make_client(conv_router, current_user=as_user)
        r = client.get("/conversations/get_history/1")
        assert r.status_code == 200
        body = r.json()
        assert len(body) == 1 and body[0]["content"] == "hi"

    def test_owner_success_empty_history(self, make_client, mock_db, as_user):
        conv = _make_conv(owner_username="user")
        mock_db.query.return_value.filter.return_value.first.return_value = conv
        mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = (
            []
        )
        client = make_client(conv_router, current_user=as_user)
        r = client.get("/conversations/get_history/1")
        assert r.status_code == 200
        assert r.json() == []

    def test_admin_can_read_foreign_history(self, make_client, mock_db, as_admin):
        conv = _make_conv(owner_username="someone-else")
        mock_db.query.return_value.filter.return_value.first.return_value = conv
        mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = (
            []
        )
        client = make_client(conv_router, current_user=as_admin)
        r = client.get("/conversations/get_history/1")
        assert r.status_code == 200

    def test_requires_auth_401(self, make_client, mock_db):
        client = make_client(conv_router)
        r = client.get("/conversations/get_history/1")
        assert r.status_code == 401

    def test_forbidden_403(self, make_client, mock_db):
        client = make_client(conv_router, current_user=_guest_user())
        r = client.get("/conversations/get_history/1")
        assert r.status_code == 403

    def test_not_found_404(self, make_client, mock_db, as_user):
        mock_db.query.return_value.filter.return_value.first.return_value = None
        client = make_client(conv_router, current_user=as_user)
        r = client.get("/conversations/get_history/9999")
        assert r.status_code == 404

    def test_non_owner_non_admin_gets_404(self, make_client, mock_db, as_user):
        conv = _make_conv(owner_username="someone-else")
        mock_db.query.return_value.filter.return_value.first.return_value = conv
        client = make_client(conv_router, current_user=as_user)
        r = client.get("/conversations/get_history/1")
        assert r.status_code == 404

    def test_non_int_chat_id_422(self, make_client, mock_db, as_user):
        # Path is declared {chat_id:int}; a non-int segment doesn't match -> 404,
        # but the trailing-form variant validates the type and returns 422.
        client = make_client(conv_router, current_user=as_user)
        r = client.get("/conversations/get_history/not-an-int")
        assert r.status_code in (404, 422)


class TestDeleteConversationRoute:
    def test_owner_success(self, make_client, mock_db, as_user):
        conv = _make_conv(owner_username="user")
        mock_db.get.return_value = conv
        client = make_client(conv_router, current_user=as_user)
        r = client.delete("/conversations/delete-conversation/1")
        assert r.status_code == 200
        assert r.json() == {"message": "Conversation correctly deleted"}
        mock_db.delete.assert_called_once_with(conv)
        mock_db.commit.assert_called_once()

    def test_owner_success_closes_active_websockets(self, make_client, mock_db, as_user):
        conv = _make_conv(owner_username="user")
        mock_db.get.return_value = conv
        good = _fake_ws()
        good.close = AsyncMock()
        bad = _fake_ws()
        bad.close = AsyncMock(side_effect=RuntimeError("already closed"))
        ctf.active_connections["1"] = [good, bad]
        client = make_client(conv_router, current_user=as_user)
        r = client.delete("/conversations/delete-conversation/1")
        assert r.status_code == 200
        good.close.assert_awaited_once()
        bad.close.assert_awaited_once()  # error is swallowed, not raised
        assert "1" not in ctf.active_connections

    def test_admin_can_delete_foreign(self, make_client, mock_db, as_admin):
        conv = _make_conv(owner_username="someone-else")
        mock_db.get.return_value = conv
        client = make_client(conv_router, current_user=as_admin)
        r = client.delete("/conversations/delete-conversation/1")
        assert r.status_code == 200

    def test_requires_auth_401(self, make_client, mock_db):
        client = make_client(conv_router)
        r = client.delete("/conversations/delete-conversation/1")
        assert r.status_code == 401

    def test_forbidden_403(self, make_client, mock_db):
        client = make_client(conv_router, current_user=_guest_user())
        r = client.delete("/conversations/delete-conversation/1")
        assert r.status_code == 403

    def test_missing_404(self, make_client, mock_db, as_user):
        mock_db.get.return_value = None
        client = make_client(conv_router, current_user=as_user)
        r = client.delete("/conversations/delete-conversation/9999")
        assert r.status_code == 404

    def test_non_owner_non_admin_404(self, make_client, mock_db, as_user):
        conv = _make_conv(owner_username="someone-else")
        mock_db.get.return_value = conv
        client = make_client(conv_router, current_user=as_user)
        r = client.delete("/conversations/delete-conversation/1")
        assert r.status_code == 404

    def test_null_owner_treated_as_unauthorized_404(self, make_client, mock_db, as_user):
        # owner_username is None (orphaned) -> conv_owner falsy -> 404 for non-admin.
        conv = _make_conv(owner_username=None)
        mock_db.get.return_value = conv
        client = make_client(conv_router, current_user=as_user)
        r = client.delete("/conversations/delete-conversation/1")
        assert r.status_code == 404

    def test_integrity_error_409(self, make_client, mock_db, as_user):
        conv = _make_conv(owner_username="user")
        mock_db.get.return_value = conv
        mock_db.commit.side_effect = IntegrityError("stmt", {}, Exception("fk"))
        client = make_client(conv_router, current_user=as_user)
        r = client.delete("/conversations/delete-conversation/1")
        assert r.status_code == 409
        assert r.json()["detail"] == "Conversation has dependent records"
        mock_db.rollback.assert_called_once()

    def test_sqlalchemy_error_500(self, make_client, mock_db, as_user):
        conv = _make_conv(owner_username="user")
        mock_db.get.return_value = conv
        mock_db.commit.side_effect = SQLAlchemyError("db")
        client = make_client(conv_router, current_user=as_user)
        r = client.delete("/conversations/delete-conversation/1")
        assert r.status_code == 500
        assert r.json()["detail"] == "Error: Database error occurred"

    def test_unexpected_error_500(self, make_client, mock_db, as_user):
        conv = _make_conv(owner_username="user")
        mock_db.get.return_value = conv
        mock_db.commit.side_effect = RuntimeError("boom")
        client = make_client(conv_router, current_user=as_user)
        r = client.delete("/conversations/delete-conversation/1")
        assert r.status_code == 500
        assert r.json()["detail"].startswith("Error: ")

    def test_websocket_management_error_is_swallowed(self, make_client, mock_db, as_user):
        """If iterating the stored connections blows up, the handler still 200s.

        The outer ``try`` around the WS-cleanup block must absorb the error
        (routes.py lines 203-204). We stash a truthy object that raises when
        ``list(conns)`` is attempted, exercising that except branch.
        """
        conv = _make_conv(owner_username="user")
        mock_db.get.return_value = conv

        class _ExplodingConns:
            def __bool__(self):  # truthy -> enters the `if conns:` block
                return True

            def __iter__(self):  # list(conns) -> boom
                raise RuntimeError("cannot iterate")

        ctf.active_connections["1"] = _ExplodingConns()
        client = make_client(conv_router, current_user=as_user)
        r = client.delete("/conversations/delete-conversation/1")
        assert r.status_code == 200


class TestGetConversationListRoute:
    def test_success(self, make_client, mock_db, as_user):
        ts = datetime.datetime(2026, 6, 6, 5, 0, 0)
        convs = [_make_conv(cid=1, name="a", owner_username="user", modified_at=ts, created_at=ts)]
        mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = (
            convs
        )
        client = make_client(conv_router, current_user=as_user)
        r = client.get("/conversations/get-conversations/")
        assert r.status_code == 200
        assert r.json()[0]["name"] == "a"

    def test_empty_list_200(self, make_client, mock_db, as_user):
        mock_db.query.return_value.filter.return_value.order_by.return_value.all.return_value = (
            []
        )
        client = make_client(conv_router, current_user=as_user)
        r = client.get("/conversations/get-conversations/")
        assert r.status_code == 200
        assert r.json() == []

    def test_requires_auth_401(self, make_client, mock_db):
        client = make_client(conv_router)
        r = client.get("/conversations/get-conversations/")
        assert r.status_code == 401

    def test_forbidden_403(self, make_client, mock_db):
        client = make_client(conv_router, current_user=_guest_user())
        r = client.get("/conversations/get-conversations/")
        assert r.status_code == 403

    def test_error_during_retrieval_500(self, make_client, mock_db, as_user):
        # Make get_conversations() raise inside the route's try-block.
        client = make_client(conv_router, current_user=as_user)
        with patch(
            "conversations.routes.get_conversations",
            side_effect=RuntimeError("boom"),
        ):
            r = client.get("/conversations/get-conversations/")
        assert r.status_code == 500
        assert r.json()["detail"] == "Error: Failed to retrieve conversations"


class TestRouteDefensiveNoneUser:
    """The ``if user is None`` guards are unreachable through the HTTP stack
    (``PermissionChecker`` short-circuits first), so call the coroutines
    directly to cover those defensive 401 branches."""

    async def test_get_history_none_user_raises_401(self, mock_db):
        from fastapi import HTTPException  # noqa: PLC0415

        from conversations.routes import get_conversation_history  # noqa: PLC0415

        with pytest.raises(HTTPException) as exc:
            await get_conversation_history(chat_id=1, user=None, db=mock_db)
        assert exc.value.status_code == 401

    async def test_remove_conversation_none_user_raises_401(self, mock_db):
        from fastapi import HTTPException  # noqa: PLC0415

        from conversations.routes import remove_conversation  # noqa: PLC0415

        with pytest.raises(HTTPException) as exc:
            await remove_conversation(chat_id=1, user=None, db=mock_db)
        assert exc.value.status_code == 401

    async def test_get_list_none_user_raises_401(self, mock_db):
        from fastapi import HTTPException  # noqa: PLC0415

        from conversations.routes import get_conversation_list  # noqa: PLC0415

        with pytest.raises(HTTPException) as exc:
            await get_conversation_list(user=None, db=mock_db)
        assert exc.value.status_code == 401


# A trivial assertion that the imports above resolved the permission enum we
# rely on for the RBAC tests (guards against an accidental import regression).
def test_permission_enum_present():
    assert Permission.TASK_READ.value == "task:read"
    assert callable(get_current_user)
