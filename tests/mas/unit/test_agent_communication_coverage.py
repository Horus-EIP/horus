"""Coverage-focused unit tests for the MAS inter-agent communication layer.

Targets three related modules:
    * ``core.agent_communication`` — MessageStore, DelegationRegistry, AgentCommunicator
    * ``core.rabbitmq_tool``       — FastAPI router (heartbeat / delegate / result / messages)
    * ``core.work_queues``         — shared work-queue name resolution + authz helper

Everything is hermetic: pika / RabbitMQ connections and channels are replaced
with ``MagicMock`` so no broker is touched, and the database is faked with
``MagicMock`` sessions. All patching is done via ``unittest.mock.patch`` /
pytest ``monkeypatch`` so global state (env, sys.modules, module singletons)
auto-reverts after every test.
"""

from __future__ import annotations

import asyncio
import json
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.agent_communication import (
    DEFAULT_DELEGATION_TIMEOUT,
    MAX_DELEGATION_DEPTH,
    AgentCommunicator,
    DelegationRegistry,
    MessageStore,
)
from schemas.agent_message import (
    AgentMessage,
    DelegationRequest,
    MessageStatus,
    MessageType,
)

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _make_message(**overrides) -> AgentMessage:
    """Build a minimal valid AgentMessage, allowing field overrides."""
    base = {
        "sender_agent_id": "agent-a",
        "receiver_agent_id": "agent-b",
        "message_type": MessageType.REQUEST,
        "content": {"hello": "world"},
    }
    base.update(overrides)
    return AgentMessage(**base)


# =========================================================================== #
# MessageStore
# =========================================================================== #


class TestMessageStore:
    def test_store_and_get_by_id(self):
        store = MessageStore()
        msg = _make_message()
        store.store(msg)
        assert store.get(msg.id) is msg

    def test_get_missing_returns_none(self):
        assert MessageStore().get("does-not-exist") is None

    def test_get_for_agent_returns_copy(self):
        store = MessageStore()
        msg = _make_message(receiver_agent_id="recv-1")
        store.store(msg)
        bucket = store.get_for_agent("recv-1")
        assert bucket == [msg]
        # Mutating the returned list must not corrupt the store's internal bucket.
        bucket.append("garbage")
        assert store.get_for_agent("recv-1") == [msg]

    def test_get_for_agent_unknown_returns_empty(self):
        assert MessageStore().get_for_agent("nobody") == []

    def test_eviction_drops_oldest_and_unindexes_it(self):
        store = MessageStore(max_messages_per_agent=2)
        m1 = _make_message(receiver_agent_id="r")
        m2 = _make_message(receiver_agent_id="r")
        m3 = _make_message(receiver_agent_id="r")
        store.store(m1)
        store.store(m2)
        store.store(m3)  # triggers eviction of m1

        bucket = store.get_for_agent("r")
        assert bucket == [m2, m3]
        # Evicted message is also purged from the id index.
        assert store.get(m1.id) is None
        assert store.get(m2.id) is m2

    def test_update_status_sets_status(self):
        store = MessageStore()
        msg = _make_message()
        store.store(msg)
        store.update_status(msg.id, MessageStatus.DELIVERED)
        # use_enum_values=True means the stored value is the raw string.
        assert store.get(msg.id).status == MessageStatus.DELIVERED.value

    def test_update_status_unknown_id_is_noop(self):
        store = MessageStore()
        # Must not raise when the id is unknown.
        store.update_status("missing", MessageStatus.FAILED)


# =========================================================================== #
# DelegationRegistry
# =========================================================================== #


class TestDelegationRegistry:
    def test_register_returns_event(self):
        reg = DelegationRegistry()
        event = reg.register("d1")
        assert isinstance(event, asyncio.Event)
        assert not event.is_set()

    def test_resolve_sets_event_and_stores_result(self):
        reg = DelegationRegistry()
        event = reg.register("d1")
        ok = reg.resolve("d1", {"result": "done"})
        assert ok is True
        assert event.is_set()
        assert reg.get_result("d1") == {"result": "done"}

    def test_resolve_unknown_returns_false(self):
        assert DelegationRegistry().resolve("nope", {"result": "x"}) is False

    def test_get_result_pops_value(self):
        reg = DelegationRegistry()
        reg.register("d1")
        reg.resolve("d1", {"result": "v"})
        assert reg.get_result("d1") == {"result": "v"}
        # Second read returns None — result was popped.
        assert reg.get_result("d1") is None

    def test_cancel_sets_error_result_and_event(self):
        reg = DelegationRegistry()
        event = reg.register("d1")
        reg.cancel("d1")
        assert event.is_set()
        assert reg.get_result("d1") == {"error": "cancelled"}

    def test_cancel_unknown_is_noop(self):
        # No pending event registered → cancel must not raise.
        DelegationRegistry().cancel("missing")


# =========================================================================== #
# AgentCommunicator — queue management
# =========================================================================== #


class TestAgentQueueManagement:
    def test_agent_queue_name_uses_prefix(self):
        comm = AgentCommunicator()
        assert comm.agent_queue_name("xyz") == f"{AgentCommunicator.QUEUE_PREFIX}xyz"

    def test_ensure_agent_queue_no_rabbitmq_skips(self):
        comm = AgentCommunicator(rabbitmq_instance=None)
        comm.ensure_agent_queue("a1")  # warns and returns, no exception

    def test_ensure_agent_queue_success_calls_create_queue(self):
        rabbit = MagicMock()
        comm = AgentCommunicator(rabbitmq_instance=rabbit)
        comm.ensure_agent_queue("a1")
        rabbit.create_queue.assert_called_once_with("agent_comm_a1")

    def test_ensure_agent_queue_swallows_exception(self):
        rabbit = MagicMock()
        rabbit.create_queue.side_effect = RuntimeError("broker down")
        comm = AgentCommunicator(rabbitmq_instance=rabbit)
        # Error is logged, not raised.
        comm.ensure_agent_queue("a1")
        rabbit.create_queue.assert_called_once()


# =========================================================================== #
# AgentCommunicator — send / acknowledge
# =========================================================================== #


class TestSendMessage:
    def test_send_without_rabbitmq_stores_but_returns_false(self):
        comm = AgentCommunicator(rabbitmq_instance=None)
        msg = _make_message()
        assert comm.send_message(msg) is False
        # Message is still persisted for debugging.
        assert comm.message_store.get(msg.id) is msg

    def test_send_success_publishes_and_marks_delivered(self):
        rabbit = MagicMock()
        comm = AgentCommunicator(rabbitmq_instance=rabbit)
        msg = _make_message(receiver_agent_id="recv-x")

        assert comm.send_message(msg) is True

        # Published to the receiver's comm queue with the JSON payload. The
        # body is serialised *before* the status is flipped, so it carries the
        # pre-delivery PENDING status and the message identity/routing fields.
        rabbit.publish.assert_called_once()
        queue_arg, payload_arg = rabbit.publish.call_args.args
        assert queue_arg == "agent_comm_recv-x"
        sent = json.loads(payload_arg)
        assert sent["id"] == msg.id
        assert sent["receiver_agent_id"] == "recv-x"
        assert sent["sender_agent_id"] == "agent-a"
        assert sent["status"] == MessageStatus.PENDING.value
        # Status flips to DELIVERED on the stored copy after publishing.
        assert comm.message_store.get(msg.id).status == MessageStatus.DELIVERED.value

    def test_send_failure_marks_failed_and_returns_false(self):
        rabbit = MagicMock()
        rabbit.publish.side_effect = RuntimeError("publish boom")
        comm = AgentCommunicator(rabbitmq_instance=rabbit)
        msg = _make_message()

        assert comm.send_message(msg) is False
        assert comm.message_store.get(msg.id).status == MessageStatus.FAILED.value

    def test_acknowledge_message_sets_acknowledged(self):
        comm = AgentCommunicator(rabbitmq_instance=MagicMock())
        msg = _make_message()
        comm.message_store.store(msg)
        comm.acknowledge_message(msg.id)
        assert comm.message_store.get(msg.id).status == MessageStatus.ACKNOWLEDGED.value


# =========================================================================== #
# AgentCommunicator — introspection
# =========================================================================== #


class TestIntrospection:
    def test_get_messages_for_agent_serialises(self):
        comm = AgentCommunicator()
        msg = _make_message(receiver_agent_id="r9")
        comm.message_store.store(msg)
        out = comm.get_messages_for_agent("r9")
        assert isinstance(out, list)
        assert out[0]["id"] == msg.id
        assert out[0]["receiver_agent_id"] == "r9"

    def test_get_message_found(self):
        comm = AgentCommunicator()
        msg = _make_message()
        comm.message_store.store(msg)
        out = comm.get_message(msg.id)
        assert out["id"] == msg.id

    def test_get_message_missing_returns_none(self):
        assert AgentCommunicator().get_message("nope") is None


# =========================================================================== #
# AgentCommunicator.handle_delegation  (async)
# =========================================================================== #


class TestHandleDelegation:
    async def test_depth_limit_exceeded(self):
        comm = AgentCommunicator(rabbitmq_instance=MagicMock())
        req = DelegationRequest(
            sender_agent_id="a",
            to_agent_type="analyst",
            request="do x",
            delegation_chain=["c"] * MAX_DELEGATION_DEPTH,
        )
        resp = await comm.handle_delegation(req, lambda t: "agent-z")
        assert resp.status == "error"
        assert "Maximum delegation depth" in resp.error

    async def test_no_available_agent(self):
        comm = AgentCommunicator(rabbitmq_instance=MagicMock())
        req = DelegationRequest(sender_agent_id="a", to_agent_type="ghost", request="r")
        resp = await comm.handle_delegation(req, lambda t: None)
        assert resp.status == "error"
        assert "No available agent" in resp.error

    async def test_loop_detection(self):
        comm = AgentCommunicator(rabbitmq_instance=MagicMock())
        req = DelegationRequest(
            sender_agent_id="a",
            to_agent_type="analyst",
            request="r",
            delegation_chain=["target"],
        )
        resp = await comm.handle_delegation(req, lambda t: "target")
        assert resp.status == "error"
        assert "loop detected" in resp.error

    async def test_send_failure_returns_error(self):
        # rabbitmq=None makes send_message return False → delivery failure path.
        comm = AgentCommunicator(rabbitmq_instance=None)
        req = DelegationRequest(sender_agent_id="a", to_agent_type="analyst", request="r")
        resp = await comm.handle_delegation(req, lambda t: "target")
        assert resp.status == "error"
        assert resp.error == "Failed to deliver delegation message"
        assert resp.delegation_id  # the generated message id is echoed back

    async def test_the_delegation_waits_for_the_broker_off_the_event_loop(self):
        rabbit = MagicMock()
        release = threading.Event()
        waits: list[bool] = []
        rabbit.publish.side_effect = lambda *_args: waits.append(release.wait(timeout=2))
        comm = AgentCommunicator(rabbitmq_instance=rabbit)
        req = DelegationRequest(
            sender_agent_id="a", to_agent_type="analyst", request="r", timeout_seconds=0.01
        )

        async def another_request():
            release.set()

        resp, _ = await asyncio.gather(
            comm.handle_delegation(req, lambda t: "target"), another_request()
        )

        assert waits == [True]
        assert resp.status == "timeout"
        rabbit.publish.assert_called_once()

    async def test_timeout_path(self):
        comm = AgentCommunicator(rabbitmq_instance=MagicMock())
        req = DelegationRequest(
            sender_agent_id="a",
            to_agent_type="analyst",
            request="r",
            timeout_seconds=0.01,  # tiny; nobody resolves the event
        )
        resp = await comm.handle_delegation(req, lambda t: "target")
        assert resp.status == "timeout"
        assert "timed out" in resp.error
        # Message status flipped to TIMEOUT.
        stored = comm.message_store.get(resp.delegation_id)
        assert stored.status == MessageStatus.TIMEOUT.value

    async def test_success_path_resolves_result(self):
        comm = AgentCommunicator(rabbitmq_instance=MagicMock())
        req = DelegationRequest(
            sender_agent_id="caller",
            to_agent_type="analyst",
            request="analyse",
            data={"k": "v"},
            timeout_seconds=2.0,
        )

        # Resolve the delegation shortly after handle_delegation starts waiting.
        async def resolver():
            await asyncio.sleep(0.02)
            # The only pending delegation id is the message we just sent.
            (delegation_id,) = list(comm.delegation_registry._pending.keys())
            comm.receive_delegation_result(delegation_id, "the-answer", "target")

        resp, _ = await asyncio.gather(
            comm.handle_delegation(req, lambda t: "target"),
            resolver(),
        )
        assert resp.status == "completed"
        assert resp.result == "the-answer"
        assert resp.agent_id == "target"
        # Successful delegation is acknowledged in the store.
        assert comm.message_store.get(resp.delegation_id).status == MessageStatus.ACKNOWLEDGED.value

    async def test_error_result_branch(self):
        """Event resolves but the result dict carries an 'error' key."""
        comm = AgentCommunicator(rabbitmq_instance=MagicMock())
        req = DelegationRequest(
            sender_agent_id="caller",
            to_agent_type="analyst",
            request="analyse",
            timeout_seconds=2.0,
        )

        async def resolver():
            await asyncio.sleep(0.02)
            (delegation_id,) = list(comm.delegation_registry._pending.keys())
            # Resolve with an explicit error payload.
            comm.delegation_registry.resolve(delegation_id, {"error": "boom"})

        resp, _ = await asyncio.gather(
            comm.handle_delegation(req, lambda t: "target"),
            resolver(),
        )
        assert resp.status == "error"
        assert resp.error == "boom"

    async def test_default_timeout_used_when_none(self, monkeypatch):
        """timeout_seconds falsy → DEFAULT_DELEGATION_TIMEOUT is passed to wait_for."""
        comm = AgentCommunicator(rabbitmq_instance=MagicMock())
        req = DelegationRequest(sender_agent_id="caller", to_agent_type="analyst", request="r")
        # Force the request's timeout to 0 (falsy) so the `or DEFAULT` branch runs.
        object.__setattr__(req, "timeout_seconds", 0)

        captured = {}

        async def fake_wait_for(awaitable, timeout):
            captured["timeout"] = timeout
            # Close the underlying coroutine to avoid "never awaited" warnings.
            if asyncio.iscoroutine(awaitable):
                awaitable.close()
            return None

        monkeypatch.setattr(asyncio, "wait_for", fake_wait_for)
        # event.wait() will be swallowed; result is unresolved → "No result" error.
        resp = await comm.handle_delegation(req, lambda t: "target")
        assert captured["timeout"] == DEFAULT_DELEGATION_TIMEOUT
        assert resp.status == "error"
        assert resp.error == "No result"

    def test_receive_delegation_result_unknown_returns_false(self):
        comm = AgentCommunicator()
        assert comm.receive_delegation_result("missing", "r", "a") is False


# =========================================================================== #
# core.rabbitmq_tool — FastAPI router
# =========================================================================== #


@pytest.fixture
def client():
    """A TestClient mounting only the rabbitmq router."""
    from core.rabbitmq_tool import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


class TestRabbitMQToolHealth:
    def test_check_rabbit_mq_success(self):
        with patch("core.rabbitmq_tool.RabbitMQ") as MockRMQ:
            inst = MockRMQ.return_value
            inst.connection.is_open = True
            from core.rabbitmq_tool import check_rabbit_mq

            assert check_rabbit_mq() is True
            inst.connect.assert_called_once()
            inst.close.assert_called_once()

    def test_check_rabbit_mq_no_connection_returns_false(self):
        with patch("core.rabbitmq_tool.RabbitMQ") as MockRMQ:
            inst = MockRMQ.return_value
            inst.connection = None
            from core.rabbitmq_tool import check_rabbit_mq

            assert check_rabbit_mq() is False

    def test_check_rabbit_mq_exception_returns_false(self):
        with patch("core.rabbitmq_tool.RabbitMQ") as MockRMQ:
            MockRMQ.return_value.connect.side_effect = RuntimeError("nope")
            from core.rabbitmq_tool import check_rabbit_mq

            assert check_rabbit_mq() is False

    def test_heartbeat_endpoint_ok(self, client):
        with patch("core.rabbitmq_tool.check_rabbit_mq", return_value=True):
            resp = client.post("/rabbitmq/heartbeat")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    def test_heartbeat_endpoint_unhealthy(self, client):
        with patch("core.rabbitmq_tool.check_rabbit_mq", return_value=False):
            resp = client.post("/rabbitmq/heartbeat")
        assert resp.status_code == 503
        assert resp.json()["status"] == "unhealthy"


class TestGetAgentCommunicator:
    def test_singleton_created_once(self, monkeypatch):
        import core.rabbitmq_tool as rt

        # Reset the module-level singleton without leaking across tests.
        monkeypatch.setattr(rt, "_agent_communicator", None)
        c1 = rt.get_agent_communicator()
        c2 = rt.get_agent_communicator()
        assert c1 is c2
        assert isinstance(c1, AgentCommunicator)


def _agent(**kw):
    """Build a fake Agents row as a SimpleNamespace."""
    base = {
        "id": "agent-1",
        "name": "Data Analyst",
        "skills": ["analyst"],
        "status": "active",
        "description": "does analysis",
        "type": "analyst",
    }
    base.update(kw)
    return SimpleNamespace(**base)


class TestDelegateEndpoint:
    """The /delegate route wires a select_agent closure over the DB, then
    calls communicator.handle_delegation. We patch the DB + agents and stub
    the communicator so no broker or real session is involved."""

    def _patches(self, agents, fake_comm):
        """Context managers patching every external dependency of the route."""
        return [
            patch(
                "agents.registry_tool_functions._get_all_agents_internal",
                return_value=agents,
            ),
            patch("db.database.SessionLocal", return_value=MagicMock()),
            patch("core.rabbitmq_tool.get_agent_communicator", return_value=fake_comm),
        ]

    def _body(self, **kw):
        base = {
            "sender_agent_id": "caller-1",
            "to_agent_type": "analyst",
            "request": "please analyse",
            "data": {"x": 1},
            "timeout_seconds": 1.0,
        }
        base.update(kw)
        return base

    def test_delegate_selects_by_skill_and_completes(self, client):
        captured = {}
        fake_comm = MagicMock()

        async def fake_handle(req, select_fn):
            # Exercise the closure: it should pick the active analyst agent.
            captured["selected"] = select_fn(req.to_agent_type)
            captured["req_request"] = req.request
            from schemas.agent_message import DelegationResponse

            return DelegationResponse(
                delegation_id="d-1", status="completed", result="ok", agent_id="agent-1"
            )

        fake_comm.handle_delegation.side_effect = fake_handle

        chosen = _agent(id="agent-1", skills=["analyst"], status="active")
        ctxs = self._patches([chosen], fake_comm)
        with ctxs[0], ctxs[1], ctxs[2]:
            resp = client.post("/rabbitmq/delegate", json=self._body())

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "completed"
        assert data["result"] == "ok"
        assert captured["selected"] == "agent-1"
        assert captured["req_request"] == "please analyse"

    def test_delegate_skips_inactive_and_self_and_matches_by_name(self, client):
        """select_agent must skip inactive agents and the sender itself, and
        fall back to matching the agent_type against name/description."""
        captured = {}
        fake_comm = MagicMock()

        async def fake_handle(req, select_fn):
            captured["selected"] = select_fn("writer")
            from schemas.agent_message import DelegationResponse

            return DelegationResponse(delegation_id="d-2", status="completed")

        fake_comm.handle_delegation.side_effect = fake_handle

        agents = [
            _agent(id="caller-1", name="caller", skills=["writer"], status="active"),
            _agent(id="inactive-1", name="Inactive Writer", skills=[], status="inactive"),
            # Matches by name (contains "writer"), skills not a list -> coerced to [].
            _agent(
                id="agent-name",
                name="Senior Writer",
                skills=None,
                status="active",
                description=None,
            ),
        ]
        ctxs = self._patches(agents, fake_comm)
        with ctxs[0], ctxs[1], ctxs[2]:
            resp = client.post("/rabbitmq/delegate", json=self._body(sender_agent_id="caller-1"))

        assert resp.status_code == 200
        # caller-1 is self (skipped), inactive-1 is inactive (skipped),
        # agent-name matches by name.
        assert captured["selected"] == "agent-name"

    def test_delegate_no_match_returns_none_selection(self, client):
        captured = {}
        fake_comm = MagicMock()

        async def fake_handle(req, select_fn):
            captured["selected"] = select_fn("nonexistent-type")
            from schemas.agent_message import DelegationResponse

            return DelegationResponse(delegation_id="", status="error", error="No available agent")

        fake_comm.handle_delegation.side_effect = fake_handle

        agents = [
            _agent(
                id="other", name="bob", skills=["analyst"], status="active", description="analysis"
            )
        ]
        ctxs = self._patches(agents, fake_comm)
        with ctxs[0], ctxs[1], ctxs[2]:
            resp = client.post("/rabbitmq/delegate", json=self._body())

        assert resp.status_code == 200
        assert captured["selected"] is None
        assert resp.json()["status"] == "error"


class TestDelegationResultEndpoint:
    def test_result_resolved_ok(self, client):
        fake_comm = MagicMock()
        fake_comm.receive_delegation_result.return_value = True
        with patch("core.rabbitmq_tool.get_agent_communicator", return_value=fake_comm):
            resp = client.post(
                "/rabbitmq/delegation-result",
                json={"delegation_id": "d-9", "result": "done", "agent_id": "a-1"},
            )
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok", "delegation_id": "d-9"}
        fake_comm.receive_delegation_result.assert_called_once_with(
            delegation_id="d-9", result="done", agent_id="a-1"
        )

    def test_result_not_found(self, client):
        fake_comm = MagicMock()
        fake_comm.receive_delegation_result.return_value = False
        with patch("core.rabbitmq_tool.get_agent_communicator", return_value=fake_comm):
            resp = client.post(
                "/rabbitmq/delegation-result",
                json={"delegation_id": "missing", "result": "x", "agent_id": "a"},
            )
        assert resp.status_code == 404
        assert resp.json()["status"] == "not_found"


class TestGetMessagesEndpoint:
    def test_get_messages_for_agent(self, client):
        fake_comm = MagicMock()
        fake_comm.get_messages_for_agent.return_value = [{"id": "m1"}]
        with patch("core.rabbitmq_tool.get_agent_communicator", return_value=fake_comm):
            resp = client.get("/rabbitmq/messages/agent-7")
        assert resp.status_code == 200
        assert resp.json() == [{"id": "m1"}]
        fake_comm.get_messages_for_agent.assert_called_once_with("agent-7")


# =========================================================================== #
# core.work_queues
# =========================================================================== #


class TestWorkQueueName:
    def test_plain_string_lowercased(self, monkeypatch):
        from core import work_queues

        # Pin the prefix so the assertion is deterministic regardless of env.
        monkeypatch.setattr(work_queues.settings, "agent_work_queue_prefix", "horus.work")
        assert work_queues.work_queue_name_for_agent_type("Analyst") == "horus.work.analyst"

    def test_enum_value_used(self, monkeypatch):
        from core import work_queues
        from db.models.agent_types import AgentTypes

        monkeypatch.setattr(work_queues.settings, "agent_work_queue_prefix", "horus.work")
        assert (
            work_queues.work_queue_name_for_agent_type(AgentTypes.RESEARCHER)
            == "horus.work.researcher"
        )

    def test_dotted_type_takes_last_segment(self, monkeypatch):
        from core import work_queues

        monkeypatch.setattr(work_queues.settings, "agent_work_queue_prefix", "horus.work")
        assert (
            work_queues.work_queue_name_for_agent_type("some.namespace.writer")
            == "horus.work.writer"
        )

    def test_prefix_override_via_settings(self, monkeypatch):
        from core import work_queues

        monkeypatch.setattr(work_queues.settings, "agent_work_queue_prefix", "custom.q")
        assert work_queues.work_queue_name_for_agent_type("general") == "custom.q.general"

    def test_falsy_prefix_falls_back_to_default(self, monkeypatch):
        from core import work_queues

        # Empty string is falsy → the `or "horus.work"` default kicks in.
        monkeypatch.setattr(work_queues.settings, "agent_work_queue_prefix", "")
        assert work_queues.work_queue_name_for_agent_type("analyst") == "horus.work.analyst"


class TestResolveWorkQueueForAgentId:
    def test_found_agent(self, monkeypatch):
        from core import work_queues

        monkeypatch.setattr(work_queues.settings, "agent_work_queue_prefix", "horus.work")
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = _agent(type="writer")
        assert work_queues.resolve_work_queue_for_agent_id(db, "agent-1") == "horus.work.writer"

    def test_missing_agent_returns_none(self):
        from core import work_queues

        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None
        assert work_queues.resolve_work_queue_for_agent_id(db, "ghost") is None


class TestAgentMaySubmitTaskResult:
    def test_same_id_allowed(self):
        from core import work_queues

        # No DB lookups happen on the fast path.
        assert work_queues.agent_may_submit_task_result("a", "a", MagicMock()) is True

    def test_same_pool_allowed(self):
        from core import work_queues
        from db.models.agent_types import AgentTypes

        ex = _agent(id="ex", type=AgentTypes.ANALYST)
        asg = _agent(id="asg", type=AgentTypes.ANALYST)
        db = MagicMock()
        db.query.return_value.filter.return_value.first.side_effect = [ex, asg]
        assert work_queues.agent_may_submit_task_result("ex", "asg", db) is True

    def test_different_pool_denied(self):
        from core import work_queues
        from db.models.agent_types import AgentTypes

        ex = _agent(id="ex", type=AgentTypes.ANALYST)
        asg = _agent(id="asg", type=AgentTypes.WRITER)
        db = MagicMock()
        db.query.return_value.filter.return_value.first.side_effect = [ex, asg]
        assert work_queues.agent_may_submit_task_result("ex", "asg", db) is False

    def test_string_type_pool_match(self):
        """type may be a plain string (no .value attribute)."""
        from core import work_queues

        ex = _agent(id="ex", type="analyst")
        asg = _agent(id="asg", type="ANALYST")  # case-insensitive compare
        db = MagicMock()
        db.query.return_value.filter.return_value.first.side_effect = [ex, asg]
        assert work_queues.agent_may_submit_task_result("ex", "asg", db) is True

    def test_missing_executor_denied(self):
        from core import work_queues

        db = MagicMock()
        # executor lookup returns None → denied immediately.
        db.query.return_value.filter.return_value.first.side_effect = [None, _agent()]
        assert work_queues.agent_may_submit_task_result("ex", "asg", db) is False

    def test_missing_assignee_denied(self):
        from core import work_queues

        db = MagicMock()
        db.query.return_value.filter.return_value.first.side_effect = [_agent(), None]
        assert work_queues.agent_may_submit_task_result("ex", "asg", db) is False
