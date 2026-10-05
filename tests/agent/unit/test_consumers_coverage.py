"""Coverage-focused unit tests for ``agent_server.consumers``.

The module runs two long-lived RabbitMQ ``BlockingConnection`` loops plus a
handful of pure helpers for attaching files to a demand. Everything here is
hermetic: ``pika`` is mocked so no broker is touched, and the lazily-imported
``agent_server.server`` / ``agent_server.profiles`` /
``agent_server.delegation_bridge`` / knowledge-store client are patched.

Strategy for the two consumer loops:

* Patch ``pika.BlockingConnection`` so ``channel.basic_consume`` *captures*
  the per-message callback the consumer registers, and ``start_consuming`` is
  a no-op. We then drive that captured callback directly with crafted
  ``(ch, method, properties, body)`` tuples to cover every message branch
  (success, cancel, empty demand, malformed JSON, pipeline error, ack/nack).
"""

from __future__ import annotations

import base64
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent_server import consumers


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _b64(s: str) -> str:
    return base64.b64encode(s.encode("utf-8")).decode("ascii")


def _make_method(tag: int = 7):
    return SimpleNamespace(delivery_tag=tag)


def _make_props(headers=None):
    return SimpleNamespace(headers=headers)


class _FakePika:
    """Stand-in for the ``pika`` module used by the consumer.

    ``BlockingConnection(...)`` -> connection whose ``channel()`` returns a
    MagicMock channel. ``basic_consume`` records ``(queue, callback)`` pairs so
    tests can fish out the message handler and invoke it themselves.
    """

    def __init__(self):
        self.channel = MagicMock(name="channel")
        self.channel.basic_consume.side_effect = self._record_consume
        self.consumed: list = []  # list[(queue, callback)]
        self.connection = MagicMock(name="connection")
        self.connection.channel.return_value = self.channel
        self.PlainCredentials = MagicMock(name="PlainCredentials")
        self.ConnectionParameters = MagicMock(name="ConnectionParameters")
        self.BlockingConnection = MagicMock(
            name="BlockingConnection", return_value=self.connection
        )

    def _record_consume(self, *, queue, on_message_callback):
        self.consumed.append((queue, on_message_callback))

    def callback_for(self, queue_substr: str):
        for q, cb in self.consumed:
            if queue_substr in q:
                return cb
        raise AssertionError(f"no consumer registered for {queue_substr!r}")


@pytest.fixture
def fake_pika():
    fp = _FakePika()
    with patch.object(consumers, "pika", fp):
        yield fp


# --------------------------------------------------------------------------- #
# _decode_inline_file
# --------------------------------------------------------------------------- #
class TestDecodeInlineFile:
    def test_valid_utf8(self):
        assert consumers._decode_inline_file(_b64("hello world")) == "hello world"

    def test_invalid_base64_returns_empty(self):
        # Not valid base64 (validate=True rejects the padding/charset) -> "".
        assert consumers._decode_inline_file("!!!not base64!!!") == ""

    def test_binary_content_falls_back_to_hex(self):
        # Bytes that are not valid UTF-8 trigger the hex best-effort branch.
        raw = b"\xff\xfe\x00\x01binary"
        out = consumers._decode_inline_file(base64.b64encode(raw).decode("ascii"))
        assert out == raw.hex()

    def test_binary_hex_is_truncated_to_4096_bytes(self):
        raw = b"\xff" * 5000
        out = consumers._decode_inline_file(base64.b64encode(raw).decode("ascii"))
        # Only the first 4096 bytes are hex-encoded (2 hex chars per byte).
        assert out == (b"\xff" * 4096).hex()
        assert len(out) == 4096 * 2


# --------------------------------------------------------------------------- #
# _resolve_attached_files (async)
# --------------------------------------------------------------------------- #
class TestResolveAttachedFiles:
    async def test_empty_list_short_circuits(self):
        assert await consumers._resolve_attached_files([]) == []

    async def test_inline_file_decoded_locally(self):
        files = [{"source": "inline", "filename": "a.txt", "content_b64": _b64("hi")}]
        with patch("ai_agents.knowledge_store_client.KnowledgeStoreClient") as KS:
            out = await consumers._resolve_attached_files(files)
            # Inline files never touch the knowledge store.
            KS.return_value.resolve_by_filename.assert_not_called()
        assert out == [{"filename": "a.txt", "source": "inline", "text": "hi"}]

    async def test_knowledge_store_file_resolved_via_client(self):
        files = [{"source": "knowledge_store", "filename": "report.pdf"}]
        client = MagicMock()
        client.resolve_by_filename = AsyncMock(return_value={"text": "KS body"})
        with patch(
            "ai_agents.knowledge_store_client.KnowledgeStoreClient",
            return_value=client,
        ):
            out = await consumers._resolve_attached_files(files)
        client.resolve_by_filename.assert_awaited_once_with("report.pdf")
        assert out == [
            {"filename": "report.pdf", "source": "knowledge_store", "text": "KS body"}
        ]

    async def test_knowledge_store_ref_with_doc_id_still_resolves_by_filename(self):
        files = [
            {"source": "knowledge_store", "filename": "report.pdf", "doc_id": "abc123"}
        ]
        client = MagicMock()
        client.resolve_by_filename = AsyncMock(return_value=None)
        with patch(
            "ai_agents.knowledge_store_client.KnowledgeStoreClient",
            return_value=client,
        ):
            out = await consumers._resolve_attached_files(files)
        client.resolve_by_filename.assert_awaited_once_with("report.pdf")
        assert [r["filename"] for r in out] == ["report.pdf"]

    async def test_knowledge_store_none_hit_yields_empty_text(self):
        files = [{"source": "knowledge_store", "filename": "missing.pdf"}]
        client = MagicMock()
        client.resolve_by_filename = AsyncMock(return_value=None)
        with patch(
            "ai_agents.knowledge_store_client.KnowledgeStoreClient",
            return_value=client,
        ):
            out = await consumers._resolve_attached_files(files)
        assert out == [
            {"filename": "missing.pdf", "source": "knowledge_store", "text": ""}
        ]

    async def test_knowledge_store_exception_swallowed(self):
        files = [{"source": "knowledge_store", "filename": "boom.pdf"}]
        client = MagicMock()
        client.resolve_by_filename = AsyncMock(side_effect=RuntimeError("ks down"))
        with patch(
            "ai_agents.knowledge_store_client.KnowledgeStoreClient",
            return_value=client,
        ):
            out = await consumers._resolve_attached_files(files)
        # Failure is logged and text falls back to "" — file still listed.
        assert out == [{"filename": "boom.pdf", "source": "knowledge_store", "text": ""}]

    async def test_missing_filename_is_skipped(self):
        files = [{"source": "inline", "content_b64": _b64("x")}]  # no filename
        with patch("ai_agents.knowledge_store_client.KnowledgeStoreClient"):
            out = await consumers._resolve_attached_files(files)
        assert out == []

    async def test_unknown_source_is_skipped(self):
        files = [{"source": "ftp", "filename": "weird.bin"}]
        with patch("ai_agents.knowledge_store_client.KnowledgeStoreClient"):
            out = await consumers._resolve_attached_files(files)
        assert out == []

    async def test_oversized_text_is_truncated(self):
        big = "z" * (consumers._MAX_FILE_CONTEXT_CHARS + 500)
        files = [{"source": "inline", "filename": "big.txt", "content_b64": _b64(big)}]
        with patch("ai_agents.knowledge_store_client.KnowledgeStoreClient"):
            out = await consumers._resolve_attached_files(files)
        text = out[0]["text"]
        assert text.endswith("\n…[truncated]")
        assert len(text) == consumers._MAX_FILE_CONTEXT_CHARS + len("\n…[truncated]")


# --------------------------------------------------------------------------- #
# _prepend_files_to_demand
# --------------------------------------------------------------------------- #
class TestPrependFilesToDemand:
    def test_no_files_returns_demand_unchanged(self):
        assert consumers._prepend_files_to_demand("do the thing", []) == "do the thing"

    def test_files_wrapped_in_context_block_before_demand(self):
        resolved = [{"filename": "a.txt", "source": "inline", "text": "ALPHA"}]
        out = consumers._prepend_files_to_demand("answer me", resolved)
        assert out.startswith("--- Attached Files ---")
        assert "[file: a.txt (source=inline)]" in out
        assert "ALPHA" in out
        assert out.endswith("answer me")
        # The demand sits after the closing marker (background-first).
        assert out.index("--- End Attached Files ---") < out.index("answer me")

    def test_empty_text_shows_placeholder(self):
        resolved = [{"filename": "e.txt", "source": "inline", "text": ""}]
        out = consumers._prepend_files_to_demand("q", resolved)
        assert "(no content available)" in out

    def test_none_demand_is_tolerated(self):
        resolved = [{"filename": "a.txt", "source": "inline", "text": "body"}]
        out = consumers._prepend_files_to_demand(None, resolved)
        # Trailing demand normalised to "" -> output just ends with newline.
        assert out.endswith("\n")
        assert "body" in out

    def test_per_file_body_truncated_to_remaining_budget(self):
        # One file just over the *total* budget forces the per-file truncation
        # branch (len(body) > budget) without hitting the omit-break.
        body = "y" * (consumers._MAX_TOTAL_CONTEXT_CHARS + 1000)
        resolved = [{"filename": "f.txt", "source": "inline", "text": body}]
        out = consumers._prepend_files_to_demand("tail", resolved)
        assert "\n…[truncated]" in out
        assert out.endswith("tail")

    def test_budget_exhaustion_omits_remaining_files(self):
        # First file consumes the whole budget so the second hits budget<=0
        # and triggers the "remaining attached files omitted" break.
        first = {
            "filename": "first.txt",
            "source": "inline",
            "text": "a" * consumers._MAX_TOTAL_CONTEXT_CHARS,
        }
        second = {"filename": "second.txt", "source": "inline", "text": "later"}
        out = consumers._prepend_files_to_demand("d", [first, second])
        assert "omitted to stay within prompt budget" in out
        # The omitted file's header never gets emitted.
        assert "[file: second.txt" not in out


# --------------------------------------------------------------------------- #
# _consume_messages — setup / guard branches
# --------------------------------------------------------------------------- #
class TestConsumeMessagesSetup:
    def test_returns_early_when_agent_id_missing(self):
        srv = MagicMock()
        srv.AGENT_ID = None
        with patch("agent_server.server", srv, create=True), patch(
            "agent_server.profiles.unique_agent_types", return_value=["general"]
        ):
            # No pika usage expected: bail out before connecting.
            with patch.object(consumers, "pika") as pk:
                consumers._consume_messages_session()
                pk.BlockingConnection.assert_not_called()

    def test_declares_one_queue_per_type_and_starts_consuming(self, fake_pika):
        srv = MagicMock()
        srv.AGENT_ID = "agent-1"
        srv.work_queue_name_for_type.side_effect = lambda t: f"work_{t}"
        with patch("agent_server.server", srv, create=True), patch(
            "agent_server.profiles.unique_agent_types",
            return_value=["general", "analyst"],
        ):
            consumers._consume_messages_session()

        # Two distinct types -> two queue_declare calls + two consumers + QoS.
        assert fake_pika.channel.queue_declare.call_count == 2
        declared = {
            c.kwargs["queue"] for c in fake_pika.channel.queue_declare.call_args_list
        }
        assert declared == {"work_general", "work_analyst"}
        fake_pika.channel.basic_qos.assert_called_once_with(prefetch_count=1)
        fake_pika.channel.start_consuming.assert_called_once()
        assert {q for q, _ in fake_pika.consumed} == {"work_general", "work_analyst"}

    def test_empty_types_falls_back_to_general(self, fake_pika):
        srv = MagicMock()
        srv.AGENT_ID = "agent-1"
        srv.work_queue_name_for_type.side_effect = lambda t: f"work_{t}"
        with patch("agent_server.server", srv, create=True), patch(
            "agent_server.profiles.unique_agent_types", return_value=[]
        ):
            consumers._consume_messages_session()
        assert {q for q, _ in fake_pika.consumed} == {"work_general"}

    def test_connection_error_is_caught_and_counted(self, fake_pika):
        srv = MagicMock()
        srv.AGENT_ID = "agent-1"
        srv.work_queue_name_for_type.side_effect = lambda t: f"work_{t}"
        fake_pika.BlockingConnection.side_effect = RuntimeError("broker unreachable")
        with patch("agent_server.server", srv, create=True), patch(
            "agent_server.profiles.unique_agent_types", return_value=["general"]
        ), patch.object(consumers, "agent_errors_total") as errs:
            # Must not raise — the loop logs and increments the error counter.
            consumers._consume_messages_session()
            errs.labels.assert_called_with(error_type="rabbitmq")
            errs.labels.return_value.inc.assert_called()


# --------------------------------------------------------------------------- #
# _run_consumer_supervisor — reconnect loop
# --------------------------------------------------------------------------- #
class TestConsumerSupervisor:
    def test_stops_when_session_returns_true(self):
        # A permanent-stop session (True) runs exactly once, no reconnect.
        session = MagicMock(return_value=True)
        consumers._run_consumer_supervisor(session, "X")
        session.assert_called_once()

    def test_reconnects_until_session_stops(self):
        # Dropped connection (False) then permanent stop (True): exactly one
        # reconnect, with a backoff sleep in between. sleep is patched so the
        # test doesn't actually wait.
        session = MagicMock(side_effect=[False, True])
        with patch.object(consumers.time_module, "sleep") as slp:
            consumers._run_consumer_supervisor(session, "X")
        assert session.call_count == 2
        slp.assert_called_once()


# --------------------------------------------------------------------------- #
# _consume_messages — per-message callback behaviour
# --------------------------------------------------------------------------- #
def _start_consumer_and_get_callback(fake_pika, *, agent_id="agent-1", types=None):
    """Run ``_consume_messages`` with a fully-mocked server/profiles and return
    (server_mock, on_message_callback) for the first queue.
    """
    types = types or ["general"]
    srv = MagicMock()
    srv.AGENT_ID = agent_id
    srv.work_queue_name_for_type.side_effect = lambda t: f"work_{t}"
    with patch("agent_server.server", srv, create=True), patch(
        "agent_server.profiles.unique_agent_types", return_value=types
    ):
        consumers._consume_messages_session()
    return srv, fake_pika.callback_for(f"work_{types[0]}")


class TestConsumeMessagesCallback:
    def _patch_profiles(self, active_profile=None):
        """Patch the profile helpers the callback lazily imports.

        ``get_profile_by_agent_id`` returns ``active_profile`` (or None) and the
        contextvars are real enough to set/reset without error.
        """
        from agent_server import profiles

        return patch.multiple(
            profiles,
            get_profile_by_agent_id=MagicMock(return_value=active_profile),
            upsert_external_profile=MagicMock(),
        )

    def test_general_success_posts_result_and_acks(self, fake_pika):
        srv, cb = _start_consumer_and_get_callback(fake_pika)
        # general pipeline: process_task -> {"response": ...}
        pipeline = MagicMock()
        pipeline.process_task = AsyncMock(return_value={"response": "ANSWER"})
        srv.get_pipeline_for_type.return_value = pipeline

        ch = MagicMock()
        body = json.dumps(
            {
                "demand": "summarise Q4",
                "conversation_id": "conv-9",
                "task_id": "task-42",
                "skill_used": "rag",
            }
        ).encode("utf-8")

        with self._patch_profiles():
            cb(ch, _make_method(11), _make_props(), body)

        # The general RAG pipeline ran on the demand.
        pipeline.process_task.assert_awaited_once()
        task_arg = pipeline.process_task.await_args.args[0]
        assert task_arg["task_id"] == "task-42"
        assert task_arg["query"] == "summarise Q4"
        # Result POSTed back with the right conversation/task ids.
        srv.send_result.assert_called_once()
        kwargs = srv.send_result.call_args
        assert kwargs.args[0] == "ANSWER"
        assert kwargs.args[1] == "conv-9"
        assert kwargs.args[2] == "task-42"
        assert kwargs.kwargs["skill_used"] == "rag"
        # Success path acks exactly once with the delivery tag.
        ch.basic_ack.assert_called_once_with(delivery_tag=11)

    def test_cancel_control_message_just_acks(self, fake_pika):
        srv, cb = _start_consumer_and_get_callback(fake_pika)
        ch = MagicMock()
        body = json.dumps({"type": "cancel", "task_id": "task-x"}).encode("utf-8")

        with self._patch_profiles():
            cb(ch, _make_method(3), _make_props(), body)

        ch.basic_ack.assert_called_once_with(delivery_tag=3)
        # No pipeline lookup, no result POST for a cancel.
        srv.get_pipeline_for_type.assert_not_called()
        srv.send_result.assert_not_called()

    def test_empty_demand_and_query_acks_without_processing(self, fake_pika):
        srv, cb = _start_consumer_and_get_callback(fake_pika)
        ch = MagicMock()
        body = json.dumps({"conversation_id": "c", "task_id": "t"}).encode("utf-8")

        with self._patch_profiles():
            cb(ch, _make_method(5), _make_props(), body)

        ch.basic_ack.assert_called_once_with(delivery_tag=5)
        srv.get_pipeline_for_type.assert_not_called()
        srv.send_result.assert_not_called()

    def test_malformed_json_falls_back_to_raw_body_as_demand(self, fake_pika):
        srv, cb = _start_consumer_and_get_callback(fake_pika)
        pipeline = MagicMock()
        pipeline.process_task = AsyncMock(return_value={"response": "OK"})
        srv.get_pipeline_for_type.return_value = pipeline

        ch = MagicMock()
        # Not JSON -> json.loads raises -> payload={"demand": <raw>}.
        body = b"this is not json at all"

        with self._patch_profiles():
            cb(ch, _make_method(8), _make_props(), body)

        # Raw text became the demand and was processed.
        task_arg = pipeline.process_task.await_args.args[0]
        assert "this is not json at all" in task_arg["query"]
        ch.basic_ack.assert_called_once_with(delivery_tag=8)

    def test_correlation_id_set_from_headers(self, fake_pika):
        srv, cb = _start_consumer_and_get_callback(fake_pika)
        pipeline = MagicMock()
        pipeline.process_task = AsyncMock(return_value={"response": "OK"})
        srv.get_pipeline_for_type.return_value = pipeline

        ch = MagicMock()
        body = json.dumps({"demand": "hi", "task_id": "t1"}).encode("utf-8")
        props = _make_props(headers={"X-Request-ID": "corr-123"})

        with self._patch_profiles(), patch.object(
            consumers, "set_correlation_id"
        ) as set_corr:
            cb(ch, _make_method(9), props, body)
            set_corr.assert_called_once_with("corr-123")

    def test_external_credentials_trigger_profile_upsert(self, fake_pika):
        srv, cb = _start_consumer_and_get_callback(fake_pika)
        pipeline = MagicMock()
        pipeline.process_task = AsyncMock(return_value={"response": "OK"})
        srv.get_pipeline_for_type.return_value = pipeline

        from agent_server import profiles

        ch = MagicMock()
        body = json.dumps(
            {
                "demand": "do it",
                "task_id": "t2",
                "assigned_agent_id": "ext-agent",
                "assigned_agent_api_key": "ext-key",
                "assigned_agent_name": "Ext",
                "assigned_agent_skills": ["s1"],
            }
        ).encode("utf-8")

        upsert = MagicMock()
        with patch.multiple(
            profiles,
            get_profile_by_agent_id=MagicMock(return_value=None),
            upsert_external_profile=upsert,
        ):
            cb(ch, _make_method(2), _make_props(), body)
            upsert.assert_called_once()
            up_kwargs = upsert.call_args.kwargs
            assert up_kwargs["agent_id"] == "ext-agent"
            assert up_kwargs["api_key"] == "ext-key"
            assert up_kwargs["skills"] == ["s1"]

    def test_specialist_without_operation_falls_back_to_general_pipeline(
        self, fake_pika
    ):
        # Consumer subscribed to the analyst queue; a task with no "operation"
        # must reroute to the general RAG pipeline (effective_type=general).
        srv, cb = _start_consumer_and_get_callback(fake_pika, types=["analyst"])
        general_pipeline = MagicMock()
        general_pipeline.process_task = AsyncMock(return_value={"response": "RAGGED"})
        specialist_pipeline = MagicMock()  # should NOT be used

        def _pick(t):
            return general_pipeline if t == "general" else specialist_pipeline

        srv.get_pipeline_for_type.side_effect = _pick

        ch = MagicMock()
        body = json.dumps({"demand": "analyse risk", "task_id": "t3"}).encode("utf-8")

        with self._patch_profiles():
            cb(ch, _make_method(4), _make_props(), body)

        general_pipeline.process_task.assert_awaited_once()
        specialist_pipeline.process_request.assert_not_called()
        srv.send_result.assert_called_once()
        assert srv.send_result.call_args.args[0] == "RAGGED"
        ch.basic_ack.assert_called_once_with(delivery_tag=4)

    def test_specialist_with_operation_calls_process_request(self, fake_pika):
        srv, cb = _start_consumer_and_get_callback(fake_pika, types=["analyst"])
        pipeline = MagicMock()
        pipeline.process_request = AsyncMock(return_value="SPECIALIST OUT")
        srv.get_pipeline_for_type.return_value = pipeline

        ch = MagicMock()
        body = json.dumps(
            {
                "demand": "data here",
                "task_id": "t4",
                "operation": "analyze",
                "analysis_type": "trend",
            }
        ).encode("utf-8")

        with self._patch_profiles():
            cb(ch, _make_method(6), _make_props(), body)

        pipeline.process_request.assert_awaited_once()
        rkwargs = pipeline.process_request.await_args.kwargs
        assert rkwargs["task_type"] == "analyze"
        assert srv.send_result.call_args.args[0] == "SPECIALIST OUT"
        ch.basic_ack.assert_called_once_with(delivery_tag=6)

    def test_pipeline_exception_emits_error_step_and_posts_error_result(
        self, fake_pika
    ):
        srv, cb = _start_consumer_and_get_callback(fake_pika)
        pipeline = MagicMock()
        pipeline.process_task = AsyncMock(side_effect=RuntimeError("pipeline boom"))
        srv.get_pipeline_for_type.return_value = pipeline

        ch = MagicMock()
        body = json.dumps(
            {"demand": "x", "task_id": "terr", "conversation_id": "cerr"}
        ).encode("utf-8")

        with self._patch_profiles(), patch.object(
            consumers, "agent_errors_total"
        ) as errs:
            cb(ch, _make_method(13), _make_props(), body)
            errs.labels.assert_any_call(error_type="task_processing")

        # An error result is POSTed back to MAS with the failure message...
        srv.send_result.assert_called_once()
        sent = srv.send_result.call_args.args[0]
        assert "Agent processing failed" in sent
        assert "pipeline boom" in sent
        # A step POST is fired (the fire-and-forget emitter calls send_step).
        srv.send_step.assert_called()
        # Error path still acks so the message is not redelivered forever.
        ch.basic_ack.assert_called_once_with(delivery_tag=13)

    def test_error_result_send_failure_is_swallowed(self, fake_pika):
        # send_result raising on the error path must not propagate; the message
        # is still acked.
        srv, cb = _start_consumer_and_get_callback(fake_pika)
        pipeline = MagicMock()
        pipeline.process_task = AsyncMock(side_effect=RuntimeError("boom"))
        srv.get_pipeline_for_type.return_value = pipeline
        srv.send_result.side_effect = RuntimeError("MAS unreachable")

        ch = MagicMock()
        body = json.dumps({"demand": "x", "task_id": "t"}).encode("utf-8")

        with self._patch_profiles():
            cb(ch, _make_method(14), _make_props(), body)  # must not raise

        ch.basic_ack.assert_called_once_with(delivery_tag=14)

    def test_step_emitter_spawns_thread_and_posts(self, fake_pika):
        # Exercise the _emit_step closure: it should start a daemon thread that
        # calls server.send_step. We patch threading.Thread to run inline.
        srv, cb = _start_consumer_and_get_callback(fake_pika)
        pipeline = MagicMock()
        pipeline.process_task = AsyncMock(side_effect=RuntimeError("boom"))
        srv.get_pipeline_for_type.return_value = pipeline

        ch = MagicMock()
        body = json.dumps({"demand": "x", "task_id": "t", "conversation_id": "c"}).encode(
            "utf-8"
        )

        class _InlineThread:
            def __init__(self, target=None, daemon=None):
                self._target = target

            def start(self):
                self._target()

        with self._patch_profiles(), patch.object(
            consumers.threading, "Thread", _InlineThread
        ):
            cb(ch, _make_method(15), _make_props(), body)

        # send_step was invoked synchronously through the inline thread with
        # the conversation/task context bound at emit time.
        srv.send_step.assert_called()
        step_kwargs = srv.send_step.call_args
        assert step_kwargs.args[1] == "c"  # conversation_id
        assert step_kwargs.args[2] == "t"  # task_id

    def test_step_emitter_swallows_send_step_errors(self, fake_pika):
        srv, cb = _start_consumer_and_get_callback(fake_pika)
        pipeline = MagicMock()
        pipeline.process_task = AsyncMock(side_effect=RuntimeError("boom"))
        srv.get_pipeline_for_type.return_value = pipeline
        srv.send_step.side_effect = RuntimeError("step post failed")

        ch = MagicMock()
        body = json.dumps({"demand": "x", "task_id": "t"}).encode("utf-8")

        class _InlineThread:
            def __init__(self, target=None, daemon=None):
                self._target = target

            def start(self):
                self._target()  # error inside is caught by _post's try/except

        with self._patch_profiles(), patch.object(
            consumers.threading, "Thread", _InlineThread
        ):
            cb(ch, _make_method(16), _make_props(), body)  # must not raise

        ch.basic_ack.assert_called_once_with(delivery_tag=16)

    def test_active_profile_binds_persona(self, fake_pika):
        # When a profile matches the assigned agent, its persona/name are bound
        # to the contextvars during processing.
        srv, cb = _start_consumer_and_get_callback(fake_pika)
        pipeline = MagicMock()
        captured = {}

        async def _proc(_task):
            from agent_server import profiles

            captured["persona"] = profiles.current_persona.get()
            captured["name"] = profiles.current_agent_name.get()
            return {"response": "OK"}

        pipeline.process_task = AsyncMock(side_effect=_proc)
        srv.get_pipeline_for_type.return_value = pipeline

        active = SimpleNamespace(system_prompt="BE A PIRATE", name="Pirate")
        ch = MagicMock()
        body = json.dumps(
            {"demand": "x", "task_id": "t", "assigned_agent_id": "a1"}
        ).encode("utf-8")

        with self._patch_profiles(active_profile=active):
            cb(ch, _make_method(17), _make_props(), body)

        assert captured["persona"] == "BE A PIRATE"
        assert captured["name"] == "Pirate"
        # And it is reset after the task (no leak).
        from agent_server import profiles

        assert profiles.current_persona.get() is None

    def test_unsupported_queue_type_raises_inside_processing(self, fake_pika):
        # A queue type that is neither "general" nor a known specialist (and
        # carries an operation, so no general fallback) hits the
        # `raise ValueError(Unsupported queue type)` branch, which is caught
        # by the surrounding try/except and surfaced as an error result.
        srv, cb = _start_consumer_and_get_callback(fake_pika, types=["weird"])
        pipeline = MagicMock()
        srv.get_pipeline_for_type.return_value = pipeline

        ch = MagicMock()
        body = json.dumps(
            {"demand": "x", "task_id": "tw", "operation": "do"}
        ).encode("utf-8")

        with self._patch_profiles():
            cb(ch, _make_method(30), _make_props(), body)

        # Unsupported type -> ValueError -> error result POSTed, message acked.
        srv.send_result.assert_called_once()
        sent = srv.send_result.call_args.args[0]
        assert "Unsupported queue type" in sent
        ch.basic_ack.assert_called_once_with(delivery_tag=30)

    def test_emit_step_failure_on_error_path_is_swallowed(self, fake_pika):
        # On the exception path the error-step emit is wrapped in its own
        # try/except. Force _emit_step to raise (Thread() blows up) and confirm
        # the handler still posts the error result and acks.
        srv, cb = _start_consumer_and_get_callback(fake_pika)
        pipeline = MagicMock()
        pipeline.process_task = AsyncMock(side_effect=RuntimeError("boom"))
        srv.get_pipeline_for_type.return_value = pipeline

        ch = MagicMock()
        body = json.dumps({"demand": "x", "task_id": "te"}).encode("utf-8")

        with self._patch_profiles(), patch.object(
            consumers.threading, "Thread", side_effect=RuntimeError("no threads")
        ):
            cb(ch, _make_method(31), _make_props(), body)  # must not raise

        srv.send_result.assert_called_once()
        assert "Agent processing failed" in srv.send_result.call_args.args[0]
        ch.basic_ack.assert_called_once_with(delivery_tag=31)

    def test_contextvar_reset_failure_is_swallowed(self, fake_pika):
        # The finally block resets three contextvars and guards against
        # LookupError/ValueError if a token is stale. Swap one contextvar for a
        # stub whose .reset raises ValueError; the guard must swallow it so the
        # handler still posts the result and acks.
        srv, cb = _start_consumer_and_get_callback(fake_pika)
        pipeline = MagicMock()
        pipeline.process_task = AsyncMock(return_value={"response": "OK"})
        srv.get_pipeline_for_type.return_value = pipeline

        from agent_server import profiles

        bad_var = MagicMock()
        bad_var.set.return_value = "tok"
        bad_var.reset.side_effect = ValueError("stale token")

        ch = MagicMock()
        body = json.dumps({"demand": "x", "task_id": "tc"}).encode("utf-8")

        with self._patch_profiles(), patch.object(
            profiles, "current_step_emitter", bad_var
        ):
            cb(ch, _make_method(32), _make_props(), body)  # must not raise

        bad_var.reset.assert_called_once_with("tok")
        # Success result still went out and the message was acked.
        srv.send_result.assert_called_once()
        ch.basic_ack.assert_called_once_with(delivery_tag=32)

    def test_inline_file_attached_to_task_dict(self, fake_pika):
        srv, cb = _start_consumer_and_get_callback(fake_pika)
        pipeline = MagicMock()
        pipeline.process_task = AsyncMock(return_value={"response": "OK"})
        srv.get_pipeline_for_type.return_value = pipeline

        ch = MagicMock()
        body = json.dumps(
            {
                "demand": "use the file",
                "task_id": "tf",
                "files": [
                    {
                        "source": "inline",
                        "filename": "notes.txt",
                        "content_b64": _b64("FILE BODY"),
                    }
                ],
            }
        ).encode("utf-8")

        with self._patch_profiles():
            cb(ch, _make_method(18), _make_props(), body)

        task_arg = pipeline.process_task.await_args.args[0]
        # The resolved file is attached and its text prepended to the demand.
        assert task_arg["filename"] == "notes.txt"
        assert task_arg["file_content"] == "FILE BODY"
        assert "FILE BODY" in task_arg["query"]
        assert "use the file" in task_arg["query"]
        assert task_arg["files"][0]["filename"] == "notes.txt"


# --------------------------------------------------------------------------- #
# _consume_agent_messages
# --------------------------------------------------------------------------- #
def _start_agent_consumer(fake_pika, agent_id="agent-77"):
    srv = MagicMock()
    srv.AGENT_ID = agent_id
    with patch("agent_server.server", srv, create=True), patch(
        "agent_server.delegation_bridge._process_delegation_message"
    ) as proc:
        consumers._consume_agent_messages_session()
    return srv, proc, fake_pika.callback_for(f"agent_comm_{agent_id}")


class TestConsumeAgentMessages:
    def test_returns_early_when_agent_id_missing(self):
        srv = MagicMock()
        srv.AGENT_ID = None
        with patch("agent_server.server", srv, create=True), patch.object(
            consumers, "pika"
        ) as pk:
            consumers._consume_agent_messages_session()
            pk.BlockingConnection.assert_not_called()

    def test_declares_queue_and_starts_consuming(self, fake_pika):
        srv = MagicMock()
        srv.AGENT_ID = "agent-77"
        with patch("agent_server.server", srv, create=True), patch(
            "agent_server.delegation_bridge._process_delegation_message"
        ):
            consumers._consume_agent_messages_session()

        fake_pika.channel.queue_declare.assert_called_once()
        assert (
            fake_pika.channel.queue_declare.call_args.kwargs["queue"]
            == "agent_comm_agent-77"
        )
        fake_pika.channel.basic_qos.assert_called_once_with(prefetch_count=1)
        fake_pika.channel.start_consuming.assert_called_once()

    def test_connection_error_is_caught(self, fake_pika):
        srv = MagicMock()
        srv.AGENT_ID = "agent-77"
        fake_pika.BlockingConnection.side_effect = RuntimeError("down")
        with patch("agent_server.server", srv, create=True), patch(
            "agent_server.delegation_bridge._process_delegation_message"
        ):
            consumers._consume_agent_messages_session()  # must not raise

    def test_delegation_message_dispatched(self, fake_pika):
        srv, proc, cb = _start_agent_consumer(fake_pika)
        ch = MagicMock()
        payload = {
            "message_type": "delegation",
            "id": "m-1",
            "sender_agent_id": "boss",
            "task": "subtask",
        }
        cb(ch, _make_method(21), _make_props(), json.dumps(payload).encode("utf-8"))

        proc.assert_called_once_with(payload)
        ch.basic_ack.assert_called_once_with(delivery_tag=21)

    def test_unknown_message_type_acked_without_dispatch(self, fake_pika):
        srv, proc, cb = _start_agent_consumer(fake_pika)
        ch = MagicMock()
        payload = {"message_type": "gossip", "id": "m-2"}
        cb(ch, _make_method(22), _make_props(), json.dumps(payload).encode("utf-8"))

        proc.assert_not_called()
        ch.basic_ack.assert_called_once_with(delivery_tag=22)

    def test_malformed_json_acked_and_not_dispatched(self, fake_pika):
        srv, proc, cb = _start_agent_consumer(fake_pika)
        ch = MagicMock()
        cb(ch, _make_method(23), _make_props(), b"<<<not json>>>")

        proc.assert_not_called()
        ch.basic_ack.assert_called_once_with(delivery_tag=23)

    def test_empty_body_treated_as_empty_payload(self, fake_pika):
        srv, proc, cb = _start_agent_consumer(fake_pika)
        ch = MagicMock()
        # Empty body -> payload {} -> unknown type -> ack, no dispatch.
        cb(ch, _make_method(24), _make_props(), b"")

        proc.assert_not_called()
        ch.basic_ack.assert_called_once_with(delivery_tag=24)
