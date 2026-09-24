"""Coverage-focused unit tests for ``agent_server.delegation_bridge``.

The module handles agent-to-agent delegation: a payload routed to us over
RabbitMQ is run through the local RAG pipeline and the answer is POSTed back
to MAS. Everything here is hermetic — no broker, no HTTP, no event loop work
escapes the process:

* The lazily-imported ``agent_server.server`` is patched *on the package
  attribute* (``patch("agent_server.server", fake, create=True)``) rather than
  via ``sys.modules`` so the real server module surviving in the full suite is
  never clobbered.
* ``requests.post`` is patched on the module under test.
* ``rag_pipeline.process_task`` is a coroutine driven through the module's own
  ``asyncio.run_until_complete`` call (we let the real loop machinery run; it
  is cheap and exercises the get-running-loop / new-loop branches).
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from agent_server import delegation_bridge as db


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _make_pipeline(*, response="ANSWER", react_agent=None, raises=None):
    """Build a fake rag_pipeline whose ``process_task`` is a coroutine.

    ``react_agent`` is attached as a plain attribute so the
    ``hasattr(..., "react_agent")`` + truthiness checks in the module behave
    realistically. Pass ``raises`` to make ``process_task`` blow up.
    """
    pipeline = SimpleNamespace()
    pipeline.react_agent = react_agent

    async def _process_task(task_dict):
        pipeline.last_task = task_dict
        if raises is not None:
            raise raises
        return {"response": response}

    pipeline.process_task = _process_task
    return pipeline


def _make_server(*, rag_pipeline=None, agent_id="agent-9", headers=None):
    srv = SimpleNamespace()
    srv.rag_pipeline = rag_pipeline
    srv.AGENT_ID = agent_id
    srv._build_headers = MagicMock(return_value=headers or {"X-Api-Key": "k"})
    return srv


def _patch_server(srv):
    return patch("agent_server.server", srv, create=True)


# --------------------------------------------------------------------------- #
# _format_delegation_context
# --------------------------------------------------------------------------- #
class TestFormatDelegationContext:
    def test_empty_list_returns_empty_string(self):
        assert db._format_delegation_context([]) == ""

    def test_single_entry_without_data_has_no_data_line(self):
        out = db._format_delegation_context(
            [{"agent_id": "alpha", "request": "do X"}]
        )
        assert out.startswith("Prior delegation context:\n")
        assert "[Agent 1 — alpha]" in out
        assert "Request: do X" in out
        # No data dict -> the "Data:" line is omitted entirely.
        assert "Data:" not in out

    def test_entry_with_data_serialises_json(self):
        out = db._format_delegation_context(
            [{"agent_id": "beta", "request": "fetch", "data": {"k": "v", "n": 3}}]
        )
        assert "[Agent 1 — beta]" in out
        assert "Data: " in out
        # The data dict is JSON-encoded verbatim.
        assert json.dumps({"k": "v", "n": 3}) in out

    def test_missing_keys_fall_back_to_defaults(self):
        # No agent_id / request / data keys at all.
        out = db._format_delegation_context([{}])
        assert "[Agent 1 — unknown]" in out
        assert "Request: " in out
        assert "Data:" not in out

    def test_multiple_entries_are_numbered_and_joined(self):
        out = db._format_delegation_context(
            [
                {"agent_id": "a1", "request": "r1"},
                {"agent_id": "a2", "request": "r2", "data": {"x": 1}},
            ]
        )
        assert "[Agent 1 — a1]" in out
        assert "[Agent 2 — a2]" in out
        # Sections joined by a newline; second carries its data line.
        assert out.index("[Agent 1 — a1]") < out.index("[Agent 2 — a2]")
        assert json.dumps({"x": 1}) in out


# --------------------------------------------------------------------------- #
# _send_delegation_result
# --------------------------------------------------------------------------- #
class TestSendDelegationResult:
    def test_success_posts_expected_payload_and_headers(self):
        srv = _make_server(agent_id="agent-42", headers={"X-Api-Key": "secret"})
        resp = SimpleNamespace(status_code=200, text="ok")
        with _patch_server(srv), patch.object(
            db.requests, "post", return_value=resp
        ) as post:
            db._send_delegation_result("deleg-1", "the result")

        post.assert_called_once()
        # URL is built from ORCHESTRATOR_URL + the delegation-result path.
        url = post.call_args.args[0]
        assert url == f"{db.ORCHESTRATOR_URL}/rabbitmq/delegation-result"
        sent = post.call_args.kwargs["json"]
        assert sent == {
            "delegation_id": "deleg-1",
            "result": "the result",
            "agent_id": "agent-42",
        }
        # Headers come from server._build_headers(include_api_key=True).
        srv._build_headers.assert_called_once_with(include_api_key=True)
        assert post.call_args.kwargs["headers"] == {"X-Api-Key": "secret"}
        assert post.call_args.kwargs["timeout"] == 10

    def test_non_200_status_logs_warning_but_does_not_raise(self):
        srv = _make_server()
        resp = SimpleNamespace(status_code=503, text="unavailable")
        with _patch_server(srv), patch.object(
            db.requests, "post", return_value=resp
        ), patch.object(db.logger, "warning") as warn:
            db._send_delegation_result("deleg-2", "r")
        warn.assert_called_once()
        # The warning carries the failing status code.
        assert "503" in warn.call_args.args[0]

    def test_request_exception_is_swallowed_and_logged(self):
        srv = _make_server()
        with _patch_server(srv), patch.object(
            db.requests, "post", side_effect=RuntimeError("connection refused")
        ), patch.object(db.logger, "error") as err:
            # Must not propagate.
            db._send_delegation_result("deleg-3", "r")
        err.assert_called_once()
        assert "Error sending delegation result" in err.call_args.args[0]
        # exc_info=True is passed so the traceback is captured.
        assert err.call_args.kwargs.get("exc_info") is True


# --------------------------------------------------------------------------- #
# _process_delegation_message
# --------------------------------------------------------------------------- #
class TestProcessDelegationMessage:
    def test_no_rag_pipeline_sends_unsupported_message_and_returns(self):
        srv = _make_server(rag_pipeline=None)
        payload = {"id": "m1", "content": {"request": "hi"}}
        with _patch_server(srv), patch.object(
            db, "_send_delegation_result"
        ) as send:
            db._process_delegation_message(payload)

        # Early-return path: the fixed "only supported for general" notice is
        # sent back keyed by the message id and the pipeline is never touched.
        send.assert_called_once()
        assert send.call_args.args[0] == "m1"
        assert "AGENT_TYPE=general" in send.call_args.args[1]

    def test_success_builds_react_task_and_sends_response(self):
        pipeline = _make_pipeline(response="RAG ANSWER")
        srv = _make_server(rag_pipeline=pipeline)
        payload = {
            "id": "msg-7",
            "sender_agent_id": "boss",
            "content": {"request": "summarise"},
        }
        with _patch_server(srv), patch.object(
            db, "_send_delegation_result"
        ) as send:
            db._process_delegation_message(payload)

        # The task dict is built in react mode with a delegation-prefixed id.
        assert pipeline.last_task["task_id"] == "delegation_msg-7"
        assert pipeline.last_task["mode"] == "react"
        # No data / no prior context -> query is just the request text.
        assert pipeline.last_task["query"] == "summarise"
        # The pipeline response is forwarded back to MAS.
        send.assert_called_once_with("msg-7", "RAG ANSWER")

    def test_data_is_appended_to_query(self):
        pipeline = _make_pipeline()
        srv = _make_server(rag_pipeline=pipeline)
        payload = {
            "id": "m2",
            "content": {"request": "analyse", "data": {"revenue": 100}},
        }
        with _patch_server(srv), patch.object(db, "_send_delegation_result"):
            db._process_delegation_message(payload)

        q = pipeline.last_task["query"]
        assert q.startswith("analyse")
        # The data dict is JSON-appended under a "Data:" marker.
        assert "Data: " in q
        assert json.dumps({"revenue": 100}) in q

    def test_prior_context_is_prepended_to_query(self):
        pipeline = _make_pipeline()
        srv = _make_server(rag_pipeline=pipeline)
        payload = {
            "id": "m3",
            "content": {"request": "continue"},
            "delegation_context": [{"agent_id": "prev", "request": "earlier ask"}],
        }
        with _patch_server(srv), patch.object(db, "_send_delegation_result"):
            db._process_delegation_message(payload)

        q = pipeline.last_task["query"]
        # Prior context block leads, current request follows after the divider.
        assert q.startswith("Prior delegation context:")
        assert "[Agent 1 — prev]" in q
        assert "Current request:" in q
        assert q.rstrip().endswith("continue")

    def test_data_and_context_combine_in_query(self):
        pipeline = _make_pipeline()
        srv = _make_server(rag_pipeline=pipeline)
        payload = {
            "id": "m4",
            "content": {"request": "both", "data": {"a": 1}},
            "delegation_context": [{"agent_id": "p", "request": "ctx"}],
        }
        with _patch_server(srv), patch.object(db, "_send_delegation_result"):
            db._process_delegation_message(payload)

        q = pipeline.last_task["query"]
        # Context wraps the (request + data) combined block.
        assert q.startswith("Prior delegation context:")
        assert "both" in q
        assert json.dumps({"a": 1}) in q

    def test_react_agent_incoming_context_set_then_cleared(self):
        ctx = [{"agent_id": "x", "request": "r"}]
        react_agent = SimpleNamespace(_incoming_delegation_context="STALE")
        captured = {}

        pipeline = SimpleNamespace(react_agent=react_agent)

        async def _process_task(task_dict):
            # During processing the incoming context must be bound.
            captured["during"] = react_agent._incoming_delegation_context
            return {"response": "ok"}

        pipeline.process_task = _process_task
        srv = _make_server(rag_pipeline=pipeline)
        payload = {"id": "m5", "content": {"request": "go"}, "delegation_context": ctx}

        with _patch_server(srv), patch.object(db, "_send_delegation_result"):
            db._process_delegation_message(payload)

        # Bound to the incoming context while running...
        assert captured["during"] == ctx
        # ...and reset to None in the finally block afterwards (no leak).
        assert react_agent._incoming_delegation_context is None

    def test_pipeline_exception_sends_failure_message_and_clears_context(self):
        react_agent = SimpleNamespace(_incoming_delegation_context=None)
        pipeline = _make_pipeline(
            react_agent=react_agent, raises=RuntimeError("model exploded")
        )
        srv = _make_server(rag_pipeline=pipeline)
        payload = {"id": "m6", "content": {"request": "boom"}}

        with _patch_server(srv), patch.object(
            db, "_send_delegation_result"
        ) as send, patch.object(db.logger, "error") as err:
            db._process_delegation_message(payload)

        # The exception is caught and surfaced as the delegation result text.
        send.assert_called_once()
        assert send.call_args.args[0] == "m6"
        assert "Delegation processing failed" in send.call_args.args[1]
        assert "model exploded" in send.call_args.args[1]
        err.assert_called_once()
        # finally still clears the react agent's incoming context after a failure.
        assert react_agent._incoming_delegation_context is None

    def test_no_react_agent_attribute_skips_context_binding(self):
        # rag_pipeline with no react_agent attribute at all: the hasattr guard
        # is False so the context-binding branch is skipped on both set + reset.
        pipeline = SimpleNamespace()

        async def _process_task(task_dict):
            return {"response": "noreact"}

        pipeline.process_task = _process_task
        srv = _make_server(rag_pipeline=pipeline)
        payload = {
            "id": "m7",
            "content": {"request": "q"},
            "delegation_context": [{"agent_id": "z", "request": "r"}],
        }

        with _patch_server(srv), patch.object(
            db, "_send_delegation_result"
        ) as send:
            db._process_delegation_message(payload)

        send.assert_called_once_with("m7", "noreact")
        # No react_agent attribute was added by the module.
        assert not hasattr(pipeline, "react_agent")

    def test_react_agent_falsy_skips_context_binding(self):
        # react_agent present but falsy (None): the truthiness guard is False
        # so the attribute is never assigned even though hasattr is True.
        pipeline = _make_pipeline(response="FALSY OK", react_agent=None)
        srv = _make_server(rag_pipeline=pipeline)
        payload = {
            "id": "m8",
            "content": {"request": "q"},
            "delegation_context": [{"agent_id": "z", "request": "r"}],
        }
        with _patch_server(srv), patch.object(
            db, "_send_delegation_result"
        ) as send:
            db._process_delegation_message(payload)
        # Pipeline still ran; result forwarded; react_agent stayed None untouched.
        send.assert_called_once_with("m8", "FALSY OK")
        assert pipeline.react_agent is None

    def test_missing_response_key_yields_empty_result_text(self):
        # process_task returns a dict without "response" -> result_text == "".
        pipeline = SimpleNamespace(react_agent=None)

        async def _process_task(task_dict):
            return {"other": "value"}

        pipeline.process_task = _process_task
        srv = _make_server(rag_pipeline=pipeline)
        payload = {"id": "m9", "content": {"request": "q"}}
        with _patch_server(srv), patch.object(
            db, "_send_delegation_result"
        ) as send:
            db._process_delegation_message(payload)
        send.assert_called_once_with("m9", "")

    def test_empty_payload_uses_all_defaults(self):
        # Completely empty payload: content {}, ids "" — exercises every
        # ``.get(..., default)`` branch and still reaches the pipeline.
        pipeline = _make_pipeline(response="EMPTY OK")
        srv = _make_server(rag_pipeline=pipeline)
        with _patch_server(srv), patch.object(
            db, "_send_delegation_result"
        ) as send:
            db._process_delegation_message({})

        assert pipeline.last_task["task_id"] == "delegation_"
        assert pipeline.last_task["query"] == ""
        send.assert_called_once_with("", "EMPTY OK")

    @pytest.mark.filterwarnings("ignore::RuntimeWarning")
    def test_reuses_running_loop_instead_of_creating_one(self):
        # When a loop is already running, ``asyncio.get_running_loop()`` succeeds
        # and the module reuses it rather than building a fresh one (covering the
        # try-branch of the get-running-loop guard). Driving ``run_until_complete``
        # on the already-running loop raises RuntimeError, which the surrounding
        # try/except turns into a failure result — so we assert both: no new loop
        # was created, and the failure is reported (not propagated).
        pipeline = _make_pipeline(response="LOOP OK")
        srv = _make_server(rag_pipeline=pipeline)
        payload = {"id": "mloop", "content": {"request": "q"}}

        async def _driver():
            with _patch_server(srv), patch.object(
                db, "_send_delegation_result"
            ) as send, patch.object(db.asyncio, "new_event_loop") as new_loop:
                db._process_delegation_message(payload)
                # A loop was already running -> no fresh loop is created.
                new_loop.assert_not_called()
                send.assert_called_once()
                assert send.call_args.args[0] == "mloop"
                assert "Delegation processing failed" in send.call_args.args[1]

        import asyncio as _aio

        _aio.run(_driver())
