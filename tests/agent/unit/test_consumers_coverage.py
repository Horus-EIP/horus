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
import threading
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pika.exceptions import AMQPError, ChannelClosedByBroker

from agent_server import consumers
from ai_agents.generation_stop import GenerationTimedOut


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
        self.channel.basic_get.side_effect = self._next_delivery
        self.consumed: list = []  # list[(queue, callback)]
        self.deliveries: list = []
        self.pulled: list[str] = []
        self.connection = MagicMock(name="connection")
        self.connection.channel.return_value = self.channel
        self.PlainCredentials = MagicMock(name="PlainCredentials")
        self.ConnectionParameters = MagicMock(name="ConnectionParameters")
        self.BlockingConnection = MagicMock(name="BlockingConnection", return_value=self.connection)

    def _record_consume(self, *, queue, on_message_callback):
        self.consumed.append((queue, on_message_callback))

    def _next_delivery(self, *, queue, auto_ack):
        self.pulled.append(queue)
        for index, (delivery_queue, delivery) in enumerate(self.deliveries):
            if delivery_queue == queue:
                del self.deliveries[index]
                return delivery
        if not self.deliveries:
            consumers._stop_pulling.set()
        return None, None, None

    def callback_for(self, queue_substr: str):
        for q, cb in self.consumed:
            if queue_substr in q:
                return cb
        raise AssertionError(f"no consumer registered for {queue_substr!r}")


@pytest.fixture
def fake_pika():
    fp = _FakePika()
    consumers._stop_pulling.clear()
    with patch.object(consumers, "pika", fp):
        yield fp
    consumers._stop_pulling.clear()


class _InlineWorkers:
    max_workers = 1

    def __init__(self, free: bool = True):
        self.free = free
        self.jobs = 0

    def has_free_slot(self):
        return self.free

    def has_started(self, _task_id):
        return False

    def submit(self, job, _task_id=None):
        self.jobs += 1
        job()


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
        client.resolve_by_filename = AsyncMock(
            return_value={"query": "__file__:report.pdf", "data": "KS body"}
        )
        with patch(
            "ai_agents.knowledge_store_client.KnowledgeStoreClient",
            return_value=client,
        ):
            out = await consumers._resolve_attached_files(files)
        client.resolve_by_filename.assert_awaited_once_with("report.pdf")
        assert out == [{"filename": "report.pdf", "source": "knowledge_store", "text": "KS body"}]

    async def test_knowledge_store_text_survives_the_real_client(self, monkeypatch):
        import ai_agents.knowledge_store_client as ksc

        response = MagicMock(status_code=200)
        response.json.return_value = {
            "text": "KS body",
            "matched_titles": ["report.pdf"],
            "doc_ids": ["d1"],
        }
        http = MagicMock()
        http.__aenter__.return_value = http
        http.get = AsyncMock(return_value=response)
        monkeypatch.setattr(ksc.httpx, "AsyncClient", MagicMock(return_value=http))
        files = [{"source": "knowledge_store", "filename": "report.pdf"}]
        out = await consumers._resolve_attached_files(files)
        assert out[0]["text"].endswith("KS body")
        assert "report.pdf" in out[0]["text"]

    async def test_knowledge_store_ref_with_doc_id_is_resolved_by_its_doc_id(self):
        """Regression F25 (B-48).

        What: two knowledge-store documents can share a filename, so an attached
        ref must reach the copy the user picked, by its doc_id.
        How: resolve a ref that carries a doc_id and check the client fetches
        that id and never searches by filename.
        When: found in ATP v7 (18/09/2026), fixed in 0b93375; resolved by doc_id
        since 8670bec (B-97), which renamed this test.
        """
        files = [{"source": "knowledge_store", "filename": "report.pdf", "doc_id": "abc123"}]
        client = MagicMock()
        client.resolve_by_doc_id = AsyncMock(
            return_value={"query": "__doc__:abc123", "data": "the second report.pdf"}
        )
        client.resolve_by_filename = AsyncMock(return_value=None)
        with patch(
            "ai_agents.knowledge_store_client.KnowledgeStoreClient",
            return_value=client,
        ):
            out = await consumers._resolve_attached_files(files)
        client.resolve_by_doc_id.assert_awaited_once_with("abc123")
        client.resolve_by_filename.assert_not_called()
        assert out == [
            {
                "filename": "report.pdf",
                "source": "knowledge_store",
                "text": "the second report.pdf",
                "doc_id": "abc123",
            }
        ]

    async def test_a_doc_id_the_store_does_not_know_falls_back_to_the_filename(self):
        files = [{"source": "knowledge_store", "filename": "report.pdf", "doc_id": "gone"}]
        client = MagicMock()
        client.resolve_by_doc_id = AsyncMock(return_value={"query": "__doc__:gone", "data": ""})
        client.resolve_by_filename = AsyncMock(
            return_value={"query": "__file__:report.pdf", "data": "by name"}
        )
        with patch(
            "ai_agents.knowledge_store_client.KnowledgeStoreClient",
            return_value=client,
        ):
            out = await consumers._resolve_attached_files(files)
        client.resolve_by_filename.assert_awaited_once_with("report.pdf")
        assert out[0]["text"] == "by name"
        assert out[0]["doc_id"] == "gone"

    async def test_a_failing_doc_id_lookup_falls_back_to_the_filename(self):
        files = [{"source": "knowledge_store", "filename": "report.pdf", "doc_id": "abc123"}]
        client = MagicMock()
        client.resolve_by_doc_id = AsyncMock(side_effect=RuntimeError("ks down"))
        client.resolve_by_filename = AsyncMock(
            return_value={"query": "__file__:report.pdf", "data": "by name"}
        )
        with patch(
            "ai_agents.knowledge_store_client.KnowledgeStoreClient",
            return_value=client,
        ):
            out = await consumers._resolve_attached_files(files)
        assert out[0]["text"] == "by name"

    async def test_knowledge_store_none_hit_yields_empty_text(self):
        files = [{"source": "knowledge_store", "filename": "missing.pdf"}]
        client = MagicMock()
        client.resolve_by_filename = AsyncMock(return_value=None)
        with patch(
            "ai_agents.knowledge_store_client.KnowledgeStoreClient",
            return_value=client,
        ):
            out = await consumers._resolve_attached_files(files)
        assert out == [{"filename": "missing.pdf", "source": "knowledge_store", "text": ""}]

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
        with (
            patch("agent_server.server", srv, create=True),
            patch("agent_server.profiles.unique_agent_types", return_value=["general"]),
        ):
            # No pika usage expected: bail out before connecting.
            with patch.object(consumers, "pika") as pk:
                consumers._consume_messages_session()
                pk.BlockingConnection.assert_not_called()

    def test_checks_each_type_queue_and_pulls_from_it(self, fake_pika):
        srv = MagicMock()
        srv.AGENT_ID = "agent-1"
        srv.work_queue_name_for_type.side_effect = lambda t: f"work_{t}"
        with (
            patch("agent_server.server", srv, create=True),
            patch(
                "agent_server.profiles.unique_agent_types",
                return_value=["general", "analyst"],
            ),
        ):
            assert consumers._consume_messages_session() is True

        declared = [
            (c.kwargs["queue"], c.kwargs["passive"])
            for c in fake_pika.channel.queue_declare.call_args_list
        ]
        assert declared == [("work_general", True), ("work_analyst", True)]
        assert set(fake_pika.pulled) == {"work_general", "work_analyst"}
        fake_pika.channel.basic_consume.assert_not_called()

    def test_empty_types_falls_back_to_general(self, fake_pika):
        srv = MagicMock()
        srv.AGENT_ID = "agent-1"
        srv.work_queue_name_for_type.side_effect = lambda t: f"work_{t}"
        with (
            patch("agent_server.server", srv, create=True),
            patch("agent_server.profiles.unique_agent_types", return_value=[]),
        ):
            consumers._consume_messages_session()
        assert set(fake_pika.pulled) == {"work_general"}

    def test_a_missing_queue_is_declared_with_the_length_limit(self, fake_pika, monkeypatch):
        monkeypatch.setenv("WORK_QUEUE_MAX_LENGTH", "25")
        fake_pika.channel.queue_declare.side_effect = [
            ChannelClosedByBroker(404, "NOT_FOUND - no queue 'work_general'"),
            None,
        ]

        consumers._declare_work_queue(fake_pika.connection, fake_pika.channel, "work_general")

        declared = fake_pika.channel.queue_declare.call_args_list[1].kwargs
        assert declared["durable"] is True
        assert declared["arguments"] == {
            "x-max-priority": 10,
            "x-max-length": 25,
            "x-overflow": "reject-publish",
        }

    def test_a_queue_declared_with_other_arguments_is_used_as_it_is(self, fake_pika):
        fake_pika.channel.queue_declare.side_effect = [
            ChannelClosedByBroker(404, "NOT_FOUND"),
            ChannelClosedByBroker(406, "PRECONDITION_FAILED - inequivalent arg"),
            None,
        ]

        consumers._declare_work_queue(fake_pika.connection, fake_pika.channel, "work_general")

        last = fake_pika.channel.queue_declare.call_args_list[-1].kwargs
        assert last == {"queue": "work_general", "passive": True}

    def test_any_other_broker_refusal_ends_the_session(self, fake_pika):
        fake_pika.channel.queue_declare.side_effect = ChannelClosedByBroker(403, "ACCESS_REFUSED")
        with pytest.raises(ChannelClosedByBroker):
            consumers._declare_work_queue(fake_pika.connection, fake_pika.channel, "work_x")

    def test_connection_error_is_caught_and_counted(self, fake_pika):
        srv = MagicMock()
        srv.AGENT_ID = "agent-1"
        srv.work_queue_name_for_type.side_effect = lambda t: f"work_{t}"
        fake_pika.BlockingConnection.side_effect = RuntimeError("broker unreachable")
        with (
            patch("agent_server.server", srv, create=True),
            patch("agent_server.profiles.unique_agent_types", return_value=["general"]),
            patch.object(consumers, "agent_errors_total") as errs,
        ):
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
    types = types or ["general"]
    srv = MagicMock()
    srv.AGENT_ID = agent_id
    srv.work_queue_name_for_type.side_effect = lambda t: f"work_{t}"
    srv.claim_task.return_value = consumers.TaskClaim.CLAIMED

    def deliver(ch, method, properties, body):
        with patch("agent_server.server", srv, create=True):
            return consumers._handle_delivery(
                ch, method, properties, body, types[0], _InlineWorkers()
            )

    return srv, deliver


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

    def test_completion_log_line_reports_the_peak_rss(self, fake_pika):
        srv, cb = _start_consumer_and_get_callback(fake_pika)
        pipeline = MagicMock()
        pipeline.process_task = AsyncMock(return_value={"response": "ANSWER"})
        srv.get_pipeline_for_type.return_value = pipeline
        body = json.dumps({"demand": "q", "task_id": "task-42"}).encode("utf-8")

        with (
            self._patch_profiles(),
            patch.object(consumers, "peak_rss_mb", return_value="4321"),
            patch.object(consumers, "logger") as log,
        ):
            cb(MagicMock(), _make_method(11), _make_props(), body)

        completion = [
            call.args
            for call in log.info.call_args_list
            if call.args and str(call.args[0]).startswith("Task processed")
        ]
        assert completion == [
            (
                "Task processed (%s): task_id=%s duration=%.2fs peak_rss_mb=%s",
                "general",
                "task-42",
                completion[0][3],
                "4321",
            )
        ]

    def test_failure_log_line_reports_the_peak_rss(self, fake_pika):
        srv, cb = _start_consumer_and_get_callback(fake_pika)
        pipeline = MagicMock()
        pipeline.process_task = AsyncMock(side_effect=RuntimeError("boom"))
        srv.get_pipeline_for_type.return_value = pipeline
        body = json.dumps({"demand": "q", "task_id": "task-43"}).encode("utf-8")

        with (
            self._patch_profiles(),
            patch.object(consumers, "peak_rss_mb", return_value="4321"),
            patch.object(consumers, "logger") as log,
        ):
            cb(MagicMock(), _make_method(12), _make_props(), body)

        log.error.assert_any_call(
            "Task processing failed: task_id=%s error=%s peak_rss_mb=%s",
            "task-43",
            "boom",
            "4321",
            exc_info=True,
        )

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

        with self._patch_profiles(), patch.object(consumers, "set_correlation_id") as set_corr:
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

    def test_specialist_without_operation_falls_back_to_general_pipeline(self, fake_pika):
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

    def test_pipeline_exception_emits_error_step_and_posts_error_result(self, fake_pika):
        srv, cb = _start_consumer_and_get_callback(fake_pika)
        pipeline = MagicMock()
        pipeline.process_task = AsyncMock(side_effect=RuntimeError("pipeline boom"))
        srv.get_pipeline_for_type.return_value = pipeline

        ch = MagicMock()
        body = json.dumps({"demand": "x", "task_id": "terr", "conversation_id": "cerr"}).encode(
            "utf-8"
        )

        with self._patch_profiles(), patch.object(consumers, "agent_errors_total") as errs:
            cb(ch, _make_method(13), _make_props(), body)
            errs.labels.assert_any_call(error_type="task_processing")

        # An error result is POSTed back to MAS with the failure message...
        srv.send_result.assert_called_once()
        sent = srv.send_result.call_args.args[0]
        assert "Agent processing failed" in sent
        assert "pipeline boom" in sent
        assert srv.send_result.call_args.kwargs["status"] == "failed"
        assert srv.send_result.call_args.kwargs["reason"] == "error"
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
        body = json.dumps({"demand": "x", "task_id": "t", "conversation_id": "c"}).encode("utf-8")

        class _InlineThread:
            def __init__(self, target=None, daemon=None):
                self._target = target

            def start(self):
                self._target()

        with self._patch_profiles(), patch.object(consumers.threading, "Thread", _InlineThread):
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

        with self._patch_profiles(), patch.object(consumers.threading, "Thread", _InlineThread):
            cb(ch, _make_method(16), _make_props(), body)  # must not raise

        ch.basic_ack.assert_called_once_with(delivery_tag=16)

    def test_streamed_steps_reach_mas_in_the_order_they_were_emitted(self, fake_pika):
        srv, cb = _start_consumer_and_get_callback(fake_pika)
        posted: list[int] = []
        all_posted = threading.Event()

        def first_post_is_slow(event, *_args, **_kwargs):
            index = event["metadata"]["index"]
            if index == 0:
                time.sleep(0.3)
            posted.append(index)
            if len(posted) == 3:
                all_posted.set()

        srv.send_step.side_effect = first_post_is_slow

        async def stream_three_deltas(_task):
            from agent_server.profiles import current_step_emitter

            emit = current_step_emitter.get()
            for index in range(3):
                emit({"step_type": "reasoning.delta", "metadata": {"index": index}})
            return {"response": "ANSWER"}

        pipeline = MagicMock()
        pipeline.process_task = stream_three_deltas
        srv.get_pipeline_for_type.return_value = pipeline
        body = json.dumps({"demand": "x", "task_id": "t", "conversation_id": "c"})

        with self._patch_profiles():
            cb(MagicMock(), _make_method(18), _make_props(), body.encode("utf-8"))

        assert all_posted.wait(5)
        assert posted == [0, 1, 2]

    def test_a_failed_step_post_does_not_stop_the_later_ones(self, fake_pika):
        srv, cb = _start_consumer_and_get_callback(fake_pika)
        posted: list[int] = []
        delivered = threading.Event()

        def first_post_fails(event, *_args, **_kwargs):
            index = event["metadata"]["index"]
            if index == 0:
                raise RuntimeError("MAS unreachable")
            posted.append(index)
            delivered.set()

        srv.send_step.side_effect = first_post_fails

        async def stream_two_deltas(_task):
            from agent_server.profiles import current_step_emitter

            emit = current_step_emitter.get()
            for index in range(2):
                emit({"step_type": "reasoning.delta", "metadata": {"index": index}})
            return {"response": "ANSWER"}

        pipeline = MagicMock()
        pipeline.process_task = stream_two_deltas
        srv.get_pipeline_for_type.return_value = pipeline
        body = json.dumps({"demand": "x", "task_id": "t", "conversation_id": "c"})

        with self._patch_profiles():
            cb(MagicMock(), _make_method(19), _make_props(), body.encode("utf-8"))

        assert delivered.wait(5)
        assert posted == [1]

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
            captured["tools"] = profiles.current_tools.get()
            return {"response": "OK"}

        pipeline.process_task = AsyncMock(side_effect=_proc)
        srv.get_pipeline_for_type.return_value = pipeline

        active = SimpleNamespace(
            system_prompt="BE A PIRATE", name="Pirate", tools=("search_knowledge", "calc")
        )
        ch = MagicMock()
        body = json.dumps({"demand": "x", "task_id": "t", "assigned_agent_id": "a1"}).encode(
            "utf-8"
        )

        with self._patch_profiles(active_profile=active):
            cb(ch, _make_method(17), _make_props(), body)

        assert captured["persona"] == "BE A PIRATE"
        assert captured["name"] == "Pirate"
        assert captured["tools"] == ("search_knowledge", "calc")
        # And it is reset after the task (no leak).
        from agent_server import profiles

        assert profiles.current_persona.get() is None
        assert profiles.current_tools.get() is None

    def test_unsupported_queue_type_raises_inside_processing(self, fake_pika):
        # A queue type that is neither "general" nor a known specialist (and
        # carries an operation, so no general fallback) hits the
        # `raise ValueError(Unsupported queue type)` branch, which is caught
        # by the surrounding try/except and surfaced as an error result.
        srv, cb = _start_consumer_and_get_callback(fake_pika, types=["weird"])
        pipeline = MagicMock()
        srv.get_pipeline_for_type.return_value = pipeline

        ch = MagicMock()
        body = json.dumps({"demand": "x", "task_id": "tw", "operation": "do"}).encode("utf-8")

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

        with (
            self._patch_profiles(),
            patch.object(consumers.threading, "Thread", side_effect=RuntimeError("no threads")),
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

        with self._patch_profiles(), patch.object(profiles, "current_step_emitter", bad_var):
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

    def test_attached_file_text_is_handed_over_once_as_context(self, fake_pika):
        srv, cb = _start_consumer_and_get_callback(fake_pika)
        pipeline = MagicMock()
        pipeline.process_task = AsyncMock(return_value={"response": "OK"})
        srv.get_pipeline_for_type.return_value = pipeline
        client = MagicMock()
        client.resolve_by_filename = AsyncMock(
            return_value={"query": "__file__:q4.md", "data": "Q4 REVENUE 4.2M"}
        )
        body = json.dumps(
            {
                "demand": "what was the revenue?",
                "task_id": "tk",
                "files": [{"source": "knowledge_store", "filename": "q4.md"}],
            }
        ).encode("utf-8")

        with (
            self._patch_profiles(),
            patch(
                "ai_agents.knowledge_store_client.KnowledgeStoreClient",
                return_value=client,
            ),
        ):
            cb(MagicMock(), _make_method(19), _make_props(), body)

        task_arg = pipeline.process_task.await_args.args[0]
        assert task_arg["demand"] == "what was the revenue?"
        assert "[file: q4.md (source=knowledge_store)]" in task_arg["attached_context"]
        assert task_arg["attached_context"].count("Q4 REVENUE 4.2M") == 1
        assert "Q4 REVENUE 4.2M" not in task_arg["demand"]

    def test_unreadable_attachments_give_no_attached_context(self, fake_pika):
        srv, cb = _start_consumer_and_get_callback(fake_pika)
        pipeline = MagicMock()
        pipeline.process_task = AsyncMock(return_value={"response": "OK"})
        srv.get_pipeline_for_type.return_value = pipeline
        client = MagicMock()
        client.resolve_by_filename = AsyncMock(
            return_value={"query": "__file__:gone.md", "data": ""}
        )
        body = json.dumps(
            {
                "demand": "what does it say?",
                "task_id": "tg",
                "files": [{"source": "knowledge_store", "filename": "gone.md"}],
            }
        ).encode("utf-8")

        with (
            self._patch_profiles(),
            patch(
                "ai_agents.knowledge_store_client.KnowledgeStoreClient",
                return_value=client,
            ),
        ):
            cb(MagicMock(), _make_method(20), _make_props(), body)

        task_arg = pipeline.process_task.await_args.args[0]
        assert task_arg["attached_context"] is None
        assert "(no content available)" in task_arg["query"]


def _general_pipeline(srv, **process_task):
    pipeline = MagicMock()
    pipeline.process_task = AsyncMock(**process_task)
    srv.get_pipeline_for_type.return_value = pipeline
    return pipeline


def _task_body(**over):
    body = {"demand": "q", "task_id": "task-1", "conversation_id": "conv-1"}
    body.update(over)
    return json.dumps(body).encode("utf-8")


class TestTaskClaims:
    def test_the_task_is_claimed_before_its_message_is_acknowledged(self, fake_pika):
        srv, cb = _start_consumer_and_get_callback(fake_pika)
        _general_pipeline(srv, return_value={"response": "ANSWER"})
        order = []

        def claim(*_args):
            order.append("claim")
            return consumers.TaskClaim.CLAIMED

        srv.claim_task.side_effect = claim
        ch = MagicMock()
        ch.basic_ack.side_effect = lambda **_kwargs: order.append("ack")

        cb(ch, _make_method(3), _make_props(), _task_body(assigned_agent_id="agent-9"))

        srv.claim_task.assert_called_once_with("task-1", "agent-9")
        assert order == ["claim", "ack"]
        srv.send_result.assert_called_once()

    def test_a_refused_claim_drops_the_message_without_running_the_task(self, fake_pika):
        srv, cb = _start_consumer_and_get_callback(fake_pika)
        pipeline = _general_pipeline(srv, return_value={"response": "ANSWER"})
        srv.claim_task.return_value = consumers.TaskClaim.REFUSED
        ch = MagicMock()

        pause = cb(ch, _make_method(4), _make_props(), _task_body())

        assert pause == 0.0
        ch.basic_ack.assert_called_once_with(delivery_tag=4)
        pipeline.process_task.assert_not_called()
        srv.send_result.assert_not_called()

    def test_an_unconfirmed_claim_puts_the_message_back_and_backs_off(self, fake_pika):
        srv, cb = _start_consumer_and_get_callback(fake_pika)
        pipeline = _general_pipeline(srv, return_value={"response": "ANSWER"})
        srv.claim_task.return_value = consumers.TaskClaim.UNAVAILABLE
        ch = MagicMock()

        pause = cb(ch, _make_method(5), _make_props(), _task_body())

        assert pause == consumers._CLAIM_RETRY_SECONDS
        ch.basic_nack.assert_called_once_with(delivery_tag=5, requeue=True)
        ch.basic_ack.assert_not_called()
        pipeline.process_task.assert_not_called()

    def test_a_claimed_task_still_runs_when_its_acknowledgement_fails(self, fake_pika):
        srv, cb = _start_consumer_and_get_callback(fake_pika)
        pipeline = _general_pipeline(srv, return_value={"response": "ANSWER"})
        ch = MagicMock()
        ch.basic_ack.side_effect = AMQPError("channel closed")

        with pytest.raises(AMQPError):
            cb(ch, _make_method(6), _make_props(), _task_body())

        pipeline.process_task.assert_awaited_once()
        srv.send_result.assert_called_once()

    def test_a_message_without_task_id_runs_without_a_claim(self, fake_pika):
        srv, cb = _start_consumer_and_get_callback(fake_pika)
        _general_pipeline(srv, return_value={"response": "ANSWER"})

        cb(MagicMock(), _make_method(7), _make_props(), json.dumps({"demand": "q"}).encode())

        srv.claim_task.assert_not_called()
        srv.send_result.assert_called_once()


class TestTimedOutAnswer:
    def test_a_timed_out_answer_is_reported_as_failed_not_as_an_answer(self, fake_pika):
        srv, cb = _start_consumer_and_get_callback(fake_pika)
        _general_pipeline(srv, side_effect=GenerationTimedOut(900))

        class _InlineThread:
            def __init__(self, target=None, daemon=None):
                self._target = target

            def start(self):
                self._target()

        with patch.object(consumers.threading, "Thread", _InlineThread):
            cb(MagicMock(), _make_method(8), _make_props(), _task_body())

        srv.send_result.assert_called_once()
        sent = srv.send_result.call_args
        assert "within 900s" in sent.args[0]
        assert sent.kwargs["status"] == "failed"
        assert sent.kwargs["reason"] == "timeout"
        step = srv.send_step.call_args.args[0]
        assert step["step_type"] == "error"
        assert step["title"] == "Answer timed out"


SOURCE = {"doc_id": "doc-q4", "chunk_id": "doc-q4:3", "title": "q4.md", "page": 2}


def _contract_result(status, answer, sources=(), reason=None):
    return {
        "response": answer,
        "status": "completed",
        "agent_answer": {
            "status": status,
            "answer": answer,
            "sources": list(sources),
            "reason": reason,
        },
    }


class TestAnswerContract:
    def test_an_answer_carries_the_sources_it_cites(self, fake_pika):
        srv, cb = _start_consumer_and_get_callback(fake_pika)
        _general_pipeline(srv, return_value=_contract_result("ok", "Revenue was $4.2M.", [SOURCE]))

        cb(MagicMock(), _make_method(9), _make_props(), _task_body())

        sent = srv.send_result.call_args
        assert sent.args[:3] == ("Revenue was $4.2M.", "conv-1", "task-1")
        assert sent.kwargs["status"] == "completed"
        assert sent.kwargs["sources"] == [SOURCE]
        assert sent.kwargs["reason"] is None

    def test_an_answer_the_documents_do_not_contain_is_reported_as_not_found(self, fake_pika):
        srv, cb = _start_consumer_and_get_callback(fake_pika)
        _general_pipeline(
            srv,
            return_value=_contract_result(
                "not_found", "The documents don't say.", reason="not_in_documents"
            ),
        )

        cb(MagicMock(), _make_method(9), _make_props(), _task_body())

        sent = srv.send_result.call_args
        assert sent.kwargs["status"] == "not_found"
        assert sent.kwargs["reason"] == "not_in_documents"
        assert sent.kwargs["sources"] == []

    def test_an_unreadable_answer_is_reported_as_failed(self, fake_pika):
        srv, cb = _start_consumer_and_get_callback(fake_pika)
        _general_pipeline(
            srv,
            return_value=_contract_result(
                "failed", "The model's answer could not be read.", reason="invalid_output"
            ),
        )

        class _InlineThread:
            def __init__(self, target=None, daemon=None):
                self._target = target

            def start(self):
                self._target()

        with patch.object(consumers.threading, "Thread", _InlineThread):
            cb(MagicMock(), _make_method(9), _make_props(), _task_body())

        sent = srv.send_result.call_args
        assert sent.args[0] == "The model's answer could not be read."
        assert sent.kwargs["status"] == "failed"
        assert sent.kwargs["reason"] == "invalid_output"
        step = srv.send_step.call_args.args[0]
        assert (step["step_type"], step["title"]) == ("error", "Answer failed")

    def test_a_specialist_answer_has_no_sources(self, fake_pika):
        srv, cb = _start_consumer_and_get_callback(fake_pika, types=["writer"])
        specialist = MagicMock()
        specialist.process_request = AsyncMock(return_value="Draft memo")
        srv.get_pipeline_for_type.return_value = specialist

        cb(MagicMock(), _make_method(9), _make_props(), _task_body(operation="write"))

        sent = srv.send_result.call_args
        assert sent.args[0] == "Draft memo"
        assert (sent.kwargs["status"], sent.kwargs["sources"]) == ("completed", [])


class TestDeliveryKey:
    def test_the_first_attempt_is_keyed_by_the_task_id(self):
        assert consumers._delivery_key("t1", None) == "t1"
        assert consumers._delivery_key("t1", 1) == "t1"
        assert consumers._delivery_key("t1", "not a number") == "t1"

    def test_a_later_attempt_has_its_own_key(self):
        assert consumers._delivery_key("t1", 2) == "t1#attempt-2"
        assert consumers._delivery_key("t1", "2") == "t1#attempt-2"


class TestPullLoop:
    def _deliver(self, fake_pika, queue, tag, body):
        fake_pika.deliveries.append((queue, (_make_method(tag), _make_props(), body)))

    def test_nothing_is_pulled_while_every_worker_is_busy(self, fake_pika):
        fake_pika.connection.process_data_events.side_effect = lambda **_kwargs: (
            consumers._stop_pulling.set()
        )

        consumers._pull_tasks(
            fake_pika.connection,
            fake_pika.channel,
            {"work_general": "general"},
            _InlineWorkers(free=False),
        )

        fake_pika.channel.basic_get.assert_not_called()
        fake_pika.connection.process_data_events.assert_called_once_with(
            time_limit=consumers._IDLE_POLL_SECONDS
        )

    def test_empty_queues_keep_the_connection_serviced(self, fake_pika):
        consumers._pull_tasks(
            fake_pika.connection,
            fake_pika.channel,
            {"work_general": "general", "work_writer": "writer"},
            _InlineWorkers(),
        )

        assert fake_pika.pulled == ["work_general", "work_writer"]
        fake_pika.connection.process_data_events.assert_called_with(
            time_limit=consumers._IDLE_POLL_SECONDS
        )

    def test_the_next_scan_starts_after_the_queue_that_delivered(self, fake_pika):
        self._deliver(fake_pika, "work_general", 1, b"{}")
        self._deliver(fake_pika, "work_general", 2, b"{}")
        self._deliver(fake_pika, "work_writer", 3, b"{}")
        handled = []

        def handle(_channel, method, _properties, _body, queue_type, _workers):
            handled.append((queue_type, method.delivery_tag))
            return 0.0

        with patch.object(consumers, "_handle_delivery", side_effect=handle):
            consumers._pull_tasks(
                fake_pika.connection,
                fake_pika.channel,
                {"work_general": "general", "work_writer": "writer"},
                _InlineWorkers(),
            )

        assert handled == [("general", 1), ("writer", 3), ("general", 2)]

    def test_the_loop_waits_as_long_as_a_delivery_asks(self, fake_pika):
        self._deliver(fake_pika, "work_general", 1, b"{}")

        with patch.object(
            consumers, "_handle_delivery", return_value=consumers._CLAIM_RETRY_SECONDS
        ):
            consumers._pull_tasks(
                fake_pika.connection,
                fake_pika.channel,
                {"work_general": "general"},
                _InlineWorkers(),
            )

        fake_pika.connection.process_data_events.assert_any_call(
            time_limit=consumers._CLAIM_RETRY_SECONDS
        )


class TestTaskWorkerPool:
    def test_a_slot_stays_busy_until_its_task_ends(self):
        pool = consumers.TaskWorkerPool(1)
        release = threading.Event()
        pool.submit(lambda: release.wait(5))

        busy_while_running = pool.has_free_slot()
        release.set()
        deadline = time.monotonic() + 5
        while not pool.has_free_slot() and time.monotonic() < deadline:
            time.sleep(0.01)

        assert busy_while_running is False
        assert pool.has_free_slot() is True

    def test_the_number_of_tasks_at_a_time_comes_from_the_environment(self, monkeypatch):
        monkeypatch.setenv("AGENT_MAX_CONCURRENT_TASKS", "3")
        assert consumers._positive_int_env("AGENT_MAX_CONCURRENT_TASKS", 1) == 3
        monkeypatch.setenv("AGENT_MAX_CONCURRENT_TASKS", "many")
        assert consumers._positive_int_env("AGENT_MAX_CONCURRENT_TASKS", 1) == 1
        monkeypatch.setenv("AGENT_MAX_CONCURRENT_TASKS", "0")
        assert consumers._positive_int_env("AGENT_MAX_CONCURRENT_TASKS", 1) == 1


# --------------------------------------------------------------------------- #
# _consume_agent_messages
# --------------------------------------------------------------------------- #
def _start_agent_consumer(fake_pika, agent_id="agent-77"):
    srv = MagicMock()
    srv.AGENT_ID = agent_id
    with (
        patch("agent_server.server", srv, create=True),
        patch("agent_server.delegation_bridge._process_delegation_message") as proc,
    ):
        consumers._consume_agent_messages_session()
    return srv, proc, fake_pika.callback_for(f"agent_comm_{agent_id}")


class TestConsumeAgentMessages:
    def test_returns_early_when_agent_id_missing(self):
        srv = MagicMock()
        srv.AGENT_ID = None
        with patch("agent_server.server", srv, create=True), patch.object(consumers, "pika") as pk:
            consumers._consume_agent_messages_session()
            pk.BlockingConnection.assert_not_called()

    def test_declares_queue_and_starts_consuming(self, fake_pika):
        srv = MagicMock()
        srv.AGENT_ID = "agent-77"
        with (
            patch("agent_server.server", srv, create=True),
            patch("agent_server.delegation_bridge._process_delegation_message"),
        ):
            consumers._consume_agent_messages_session()

        fake_pika.channel.queue_declare.assert_called_once()
        assert fake_pika.channel.queue_declare.call_args.kwargs["queue"] == "agent_comm_agent-77"
        fake_pika.channel.basic_qos.assert_called_once_with(prefetch_count=1)
        fake_pika.channel.start_consuming.assert_called_once()

    def test_connection_error_is_caught(self, fake_pika):
        srv = MagicMock()
        srv.AGENT_ID = "agent-77"
        fake_pika.BlockingConnection.side_effect = RuntimeError("down")
        with (
            patch("agent_server.server", srv, create=True),
            patch("agent_server.delegation_bridge._process_delegation_message"),
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
