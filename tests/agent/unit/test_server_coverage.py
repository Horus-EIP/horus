"""Behavioural coverage for ``agent_server.server``.

Hermetic: ``tests/agent/conftest.py`` already stubs langchain/transformers/torch
via ``sys.modules`` so importing the server (which pulls in the RAG pipeline and
specialised agents) does not download models or hit the network.

What's exercised here:

* HTTP surface via ``TestClient`` — ``GET /capabilities``, ``GET /metrics``,
  ``POST /task`` (general + specialist success paths, validation 422, the
  auto-generated ``task_id`` path, correlation-ID propagation, and the
  exception path that re-raises into a 500).
* The MAS-facing helpers that ``requests`` drives — token caching / login /
  failure, header building, profile registration (200 / 409-reclaim /
  409-suffix-fallback / error / exception), heartbeat (success / 401-retry /
  non-200 / exception), ``send_result`` and ``send_step`` (success / non-200 /
  exception), and the ``lifespan`` startup that spins up the daemon threads.

Every ``requests`` call is mocked; assertions check observable behaviour
(status codes, response bodies, the URL/payload/headers actually sent,
mutated module state) — never "a mock returned a mock".

Module-level globals (``PROFILES``, ``AGENT_ID`` …) are mutated by the code
under test, so each test that touches them snapshots and restores via the
``restore_module_state`` fixture.
"""

from __future__ import annotations

import copy
import threading
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from agent_server import server


# --------------------------------------------------------------------------- #
# Helpers / fixtures
# --------------------------------------------------------------------------- #
def _make_response(status_code: int = 200, json_data=None, text: str = ""):
    """A stand-in for ``requests.Response`` good enough for the server code."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = {} if json_data is None else json_data
    resp.text = text
    return resp


@pytest.fixture
def client():
    return TestClient(server.app)


@pytest.fixture
def client_no_reraise():
    """Client that converts unhandled endpoint exceptions into 500 responses.

    The ``/task`` route deliberately re-raises on failure; a real ASGI server
    turns that into a 500. The default ``TestClient`` would instead propagate
    the exception into the test, so we disable that to assert the HTTP status.
    """
    return TestClient(server.app, raise_server_exceptions=False)


@pytest.fixture
def restore_module_state():
    """Snapshot + restore module globals the code under test mutates."""
    saved_agent_id = server.AGENT_ID
    saved_api_key = server.AGENT_API_KEY
    saved_token = server._AUTH_TOKEN
    # Deep-copy each profile's mutable fields so registration tests can't leak.
    saved_profiles = [copy.copy(p) for p in server.PROFILES]
    saved_profiles_ref = list(server.PROFILES)
    yield
    server.AGENT_ID = saved_agent_id
    server.AGENT_API_KEY = saved_api_key
    server._AUTH_TOKEN = saved_token
    server.PROFILES[:] = saved_profiles_ref
    for live, snap in zip(server.PROFILES, saved_profiles):
        live.agent_id = snap.agent_id
        live.api_key = snap.api_key
        live.name = snap.name
        live.type = snap.type
        live.skills = snap.skills


# --------------------------------------------------------------------------- #
# Pure helpers
# --------------------------------------------------------------------------- #
class TestSmallHelpers:
    def test_get_pipeline_for_type_known_and_default(self):
        assert server.get_pipeline_for_type("general") is server.pipelines["general"]
        assert server.get_pipeline_for_type("analyst") is server.pipelines["analyst"]
        # Unknown / empty / None all fall back to the general pipeline.
        assert server.get_pipeline_for_type("nope") is server.pipelines["general"]
        assert server.get_pipeline_for_type("") is server.pipelines["general"]
        assert server.get_pipeline_for_type(None) is server.pipelines["general"]

    def test_work_queue_name_for_type(self):
        assert server.work_queue_name_for_type("analyst").endswith(".analyst")
        # Empty -> general.
        assert server.work_queue_name_for_type("").endswith(".general")
        # Dotted type keeps only the last segment.
        assert server.work_queue_name_for_type("horus.work.writer").endswith(".writer")
        assert ".writer" in server.work_queue_name_for_type("a.b.WRITER")

    def test_invalidate_cached_mas_token(self, restore_module_state):
        server._AUTH_TOKEN = "cached"
        server._invalidate_cached_mas_token()
        assert server._AUTH_TOKEN is None


# --------------------------------------------------------------------------- #
# _get_orchestrator_token
# --------------------------------------------------------------------------- #
class TestGetOrchestratorToken:
    def test_returns_cached_token(self, restore_module_state):
        server._AUTH_TOKEN = "already-have-it"
        assert server._get_orchestrator_token() == "already-have-it"

    def test_uses_env_token_when_present(self, restore_module_state):
        server._AUTH_TOKEN = None
        with patch.object(server, "ORCHESTRATOR_TOKEN", "env-token"):
            assert server._get_orchestrator_token() == "env-token"
            # And it gets cached.
            assert server._AUTH_TOKEN == "env-token"

    def test_logs_in_with_username_password(self, restore_module_state):
        server._AUTH_TOKEN = None
        resp = _make_response(200, {"access_token": "fresh-jwt"})
        with (
            patch.object(server, "ORCHESTRATOR_TOKEN", None),
            patch.object(server, "ORCHESTRATOR_USERNAME", "u"),
            patch.object(server, "ORCHESTRATOR_PASSWORD", "p"),
            patch.object(server.requests, "post", return_value=resp) as mock_post,
        ):
            assert server._get_orchestrator_token() == "fresh-jwt"
        # Hit the /auth/token endpoint with form data.
        called_url = mock_post.call_args.args[0]
        assert called_url.endswith("/auth/token")
        assert mock_post.call_args.kwargs["data"] == {"username": "u", "password": "p"}

    def test_login_non_200_returns_none(self, restore_module_state):
        server._AUTH_TOKEN = None
        resp = _make_response(401, text="bad creds")
        with (
            patch.object(server, "ORCHESTRATOR_TOKEN", None),
            patch.object(server, "ORCHESTRATOR_USERNAME", "u"),
            patch.object(server, "ORCHESTRATOR_PASSWORD", "p"),
            patch.object(server.requests, "post", return_value=resp),
        ):
            assert server._get_orchestrator_token() is None
            assert server._AUTH_TOKEN is None

    def test_login_exception_returns_none(self, restore_module_state):
        server._AUTH_TOKEN = None
        with (
            patch.object(server, "ORCHESTRATOR_TOKEN", None),
            patch.object(server, "ORCHESTRATOR_USERNAME", "u"),
            patch.object(server, "ORCHESTRATOR_PASSWORD", "p"),
            patch.object(server.requests, "post", side_effect=ConnectionError("down")),
        ):
            assert server._get_orchestrator_token() is None

    def test_no_credentials_returns_none(self, restore_module_state):
        server._AUTH_TOKEN = None
        with (
            patch.object(server, "ORCHESTRATOR_TOKEN", None),
            patch.object(server, "ORCHESTRATOR_USERNAME", None),
            patch.object(server, "ORCHESTRATOR_PASSWORD", None),
        ):
            assert server._get_orchestrator_token() is None


# --------------------------------------------------------------------------- #
# _build_headers
# --------------------------------------------------------------------------- #
class TestBuildHeaders:
    def test_adds_bearer_when_token_available(self):
        with patch.object(server, "_get_orchestrator_token", return_value="tok"):
            headers = server._build_headers()
        assert headers["Authorization"] == "Bearer tok"
        assert "X-API-Key" not in headers

    def test_no_authorization_when_no_token(self):
        with patch.object(server, "_get_orchestrator_token", return_value=None):
            headers = server._build_headers()
        assert "Authorization" not in headers

    def test_includes_api_key_with_explicit_credentials(self):
        with patch.object(server, "_get_orchestrator_token", return_value=None):
            headers = server._build_headers(
                include_api_key=True, agent_id="aid-1", api_key="key-1"
            )
        assert headers["X-API-Key"] == "aid-1:key-1"
        assert headers["Agent-ID"] == "aid-1"

    def test_api_key_omitted_when_credentials_missing(self, restore_module_state):
        server.AGENT_ID = None
        server.AGENT_API_KEY = None
        with patch.object(server, "_get_orchestrator_token", return_value=None):
            headers = server._build_headers(include_api_key=True)
        assert "X-API-Key" not in headers

    def test_api_key_falls_back_to_module_globals(self, restore_module_state):
        server.AGENT_ID = "global-id"
        server.AGENT_API_KEY = "global-key"
        with patch.object(server, "_get_orchestrator_token", return_value=None):
            headers = server._build_headers(include_api_key=True)
        assert headers["X-API-Key"] == "global-id:global-key"


# --------------------------------------------------------------------------- #
# _register_one_profile
# --------------------------------------------------------------------------- #
class TestRegisterOneProfile:
    def _profile(self):
        from agent_server.profiles import AgentProfile

        return AgentProfile(
            name="Tester", type="general", skills=["s1"], description="d"
        )

    def test_success_sets_ids(self, restore_module_state):
        profile = self._profile()
        resp = _make_response(200, {"agent_id": "AID", "api_key": "AKEY"})
        with (
            patch.object(server, "_build_headers", return_value={}),
            patch.object(server.requests, "post", return_value=resp) as mock_post,
        ):
            assert server._register_one_profile(profile) is True
        assert profile.agent_id == "AID"
        assert profile.api_key == "AKEY"
        # Registered against the right endpoint with a JSON payload.
        assert mock_post.call_args.args[0].endswith("/agents/register")
        assert mock_post.call_args.kwargs["json"]["name"] == "Tester"

    def test_conflict_reclaims_name_then_succeeds(self, restore_module_state):
        profile = self._profile()
        register_resps = [
            _make_response(409, text="exists"),  # first register -> conflict
            _make_response(200, {"agent_id": "AID2", "api_key": "AKEY2"}),  # retry ok
        ]
        list_resp = _make_response(200, [{"name": "Tester", "id": "ghost-1"}])
        del_resp = _make_response(200)
        with (
            patch.object(server, "_build_headers", return_value={}),
            patch.object(server.requests, "post", side_effect=register_resps),
            patch.object(server.requests, "get", return_value=list_resp),
            patch.object(server.requests, "delete", return_value=del_resp) as mock_del,
        ):
            assert server._register_one_profile(profile) is True
        assert profile.agent_id == "AID2"
        # The stale ghost row was deleted.
        assert mock_del.call_args.args[0].endswith("/agents/unregister/ghost-1")

    def test_conflict_no_ghosts_falls_back_to_suffix(self, restore_module_state):
        profile = self._profile()
        register_resps = [
            _make_response(409, text="exists"),  # conflict on base name
            _make_response(200, {"agent_id": "AID3", "api_key": "AKEY3"}),  # suffix ok
        ]
        # Listing returns no rows matching the name -> nothing to delete.
        list_resp = _make_response(200, [{"name": "SomethingElse", "id": "x"}])
        with (
            patch.object(server, "_build_headers", return_value={}),
            patch.object(server.requests, "post", side_effect=register_resps) as mock_post,
            patch.object(server.requests, "get", return_value=list_resp),
            patch.object(server.requests, "delete") as mock_del,
        ):
            assert server._register_one_profile(profile) is True
        mock_del.assert_not_called()
        # Second attempt used a uniquified "Tester-xxxxxx" name.
        retried_name = mock_post.call_args_list[1].kwargs["json"]["name"]
        assert retried_name.startswith("Tester-") and retried_name != "Tester"

    def test_conflict_delete_failure_then_suffix(self, restore_module_state):
        profile = self._profile()
        register_resps = [
            _make_response(409, text="exists"),
            _make_response(200, {"agent_id": "AID4", "api_key": "AKEY4"}),
        ]
        list_resp = _make_response(200, [{"name": "Tester", "id": "ghost-2"}])
        del_resp = _make_response(500, text="forbidden")  # delete fails
        with (
            patch.object(server, "_build_headers", return_value={}),
            patch.object(server.requests, "post", side_effect=register_resps) as mock_post,
            patch.object(server.requests, "get", return_value=list_resp),
            patch.object(server.requests, "delete", return_value=del_resp),
        ):
            assert server._register_one_profile(profile) is True
        # delete failed -> deleted_any False -> suffix path
        retried_name = mock_post.call_args_list[1].kwargs["json"]["name"]
        assert retried_name.startswith("Tester-")

    def test_conflict_list_non_200_falls_back_to_suffix(self, restore_module_state):
        profile = self._profile()
        register_resps = [
            _make_response(409, text="exists"),
            _make_response(200, {"agent_id": "AID6", "api_key": "AKEY6"}),
        ]
        # Listing the agents returns a non-200 -> ghost discovery is skipped.
        list_resp = _make_response(403, text="forbidden")
        with (
            patch.object(server, "_build_headers", return_value={}),
            patch.object(server.requests, "post", side_effect=register_resps) as mock_post,
            patch.object(server.requests, "get", return_value=list_resp),
            patch.object(server.requests, "delete") as mock_del,
        ):
            assert server._register_one_profile(profile) is True
        mock_del.assert_not_called()
        retried_name = mock_post.call_args_list[1].kwargs["json"]["name"]
        assert retried_name.startswith("Tester-")

    def test_conflict_list_raises_then_suffix(self, restore_module_state):
        profile = self._profile()
        register_resps = [
            _make_response(409, text="exists"),
            _make_response(200, {"agent_id": "AID5", "api_key": "AKEY5"}),
        ]
        with (
            patch.object(server, "_build_headers", return_value={}),
            patch.object(server.requests, "post", side_effect=register_resps) as mock_post,
            patch.object(server.requests, "get", side_effect=RuntimeError("boom")),
            patch.object(server.requests, "delete") as mock_del,
        ):
            assert server._register_one_profile(profile) is True
        mock_del.assert_not_called()
        retried_name = mock_post.call_args_list[1].kwargs["json"]["name"]
        assert retried_name.startswith("Tester-")

    def test_error_status_returns_false(self, restore_module_state):
        profile = self._profile()
        resp = _make_response(500, text="server error")
        with (
            patch.object(server, "_build_headers", return_value={}),
            patch.object(server.requests, "post", return_value=resp),
            patch.object(server.agent_errors_total, "labels") as mock_labels,
        ):
            assert server._register_one_profile(profile) is False
        mock_labels.assert_called_with(error_type="registration")

    def test_exception_returns_false(self, restore_module_state):
        profile = self._profile()
        with (
            patch.object(server, "_build_headers", return_value={}),
            patch.object(server.requests, "post", side_effect=ConnectionError("x")),
            patch.object(server.agent_errors_total, "labels") as mock_labels,
        ):
            assert server._register_one_profile(profile) is False
        mock_labels.assert_called_with(error_type="registration")


# --------------------------------------------------------------------------- #
# register_profiles
# --------------------------------------------------------------------------- #
class TestRegisterProfiles:
    def test_registers_all_and_sets_globals(self, restore_module_state):
        # Reset every profile to unregistered so the loop actually registers.
        for p in server.PROFILES:
            p.agent_id = None
            p.api_key = None

        def fake_register(profile):
            profile.agent_id = f"id-{profile.name}"
            profile.api_key = f"key-{profile.name}"
            return True

        with (
            patch.object(server, "_register_one_profile", side_effect=fake_register),
            patch.object(server.agent_registered, "set") as mock_set,
        ):
            server.register_profiles()

        primary = server.get_primary_profile()
        assert server.AGENT_ID == primary.agent_id
        assert server.AGENT_API_KEY == primary.api_key
        mock_set.assert_called_with(1)

    def test_skips_already_registered_profiles(self, restore_module_state):
        for p in server.PROFILES:
            p.agent_id = "preset"
            p.api_key = "presetkey"
        with patch.object(server, "_register_one_profile") as mock_reg:
            server.register_profiles()
        # Everything already had an agent_id -> no registration attempts.
        mock_reg.assert_not_called()
        assert server.AGENT_ID == server.get_primary_profile().agent_id

    def test_retries_with_backoff_until_success(self, restore_module_state):
        for p in server.PROFILES:
            p.agent_id = None
            p.api_key = None

        calls = {"n": 0}

        def flaky_register(profile):
            # First full sweep fails for everyone; second sweep, primary wins.
            calls["n"] += 1
            if calls["n"] <= len(server.PROFILES):
                return False
            profile.agent_id = f"id-{profile.name}"
            profile.api_key = "k"
            return True

        with (
            patch.object(server, "_register_one_profile", side_effect=flaky_register),
            patch.object(server.time, "sleep") as mock_sleep,
            patch.object(server.agent_registered, "set"),
        ):
            server.register_profiles()
        # Slept at least once because the first sweep produced no successes.
        assert mock_sleep.called


# --------------------------------------------------------------------------- #
# Heartbeat
# --------------------------------------------------------------------------- #
class TestHeartbeat:
    def _profile(self, agent_id="hb-id", api_key="hb-key"):
        from agent_server.profiles import AgentProfile

        return AgentProfile(
            name="HB", type="general", skills=[], description="",
            agent_id=agent_id, api_key=api_key,
        )

    def test_skips_unregistered_profile(self):
        from agent_server.profiles import AgentProfile

        profile = AgentProfile(name="x", type="general", skills=[], description="")
        with patch.object(server.requests, "post") as mock_post:
            server._heartbeat_for_profile(profile)
        mock_post.assert_not_called()

    def test_success_increments_success_metric(self):
        profile = self._profile()
        resp = _make_response(200)
        with (
            patch.object(server, "_build_headers", return_value={}),
            patch.object(server.requests, "post", return_value=resp) as mock_post,
            patch.object(server.agent_heartbeat_total, "labels") as mock_labels,
        ):
            server._heartbeat_for_profile(profile)
        assert mock_post.call_args.args[0].endswith("/agents/heartbeat/hb-id")
        mock_labels.assert_called_with(status="success")

    def test_401_invalidates_token_and_retries(self, restore_module_state):
        profile = self._profile()
        responses = [_make_response(401, text="expired"), _make_response(200)]
        with (
            patch.object(server, "ORCHESTRATOR_TOKEN", None),
            patch.object(server, "_build_headers", return_value={}),
            patch.object(server.requests, "post", side_effect=responses) as mock_post,
            patch.object(server, "_invalidate_cached_mas_token") as mock_inval,
            patch.object(server.agent_heartbeat_total, "labels") as mock_labels,
        ):
            server._heartbeat_for_profile(profile)
        mock_inval.assert_called_once()
        assert mock_post.call_count == 2
        mock_labels.assert_called_with(status="success")

    def test_non_200_increments_error_metric(self):
        profile = self._profile()
        resp = _make_response(500, text="oops")
        with (
            patch.object(server, "ORCHESTRATOR_TOKEN", "fixed-token"),
            patch.object(server, "_build_headers", return_value={}),
            patch.object(server.requests, "post", return_value=resp),
            patch.object(server.agent_heartbeat_total, "labels") as mock_labels,
        ):
            server._heartbeat_for_profile(profile)
        mock_labels.assert_called_with(status="error")

    def test_exception_increments_error_metric(self):
        profile = self._profile()
        with (
            patch.object(server, "_build_headers", return_value={}),
            patch.object(server.requests, "post", side_effect=RuntimeError("net")),
            patch.object(server.agent_heartbeat_total, "labels") as mock_labels,
        ):
            server._heartbeat_for_profile(profile)
        mock_labels.assert_called_with(status="error")

    def test_send_heartbeat_iterates_profiles(self):
        with patch.object(server, "_heartbeat_for_profile") as mock_hb:
            server.send_heartbeat()
        assert mock_hb.call_count == len(server.PROFILES)

    def test_heartbeat_task_loops_then_stops(self):
        # Let the loop run one iteration, then break out via sleep raising.
        with (
            patch.object(server, "send_heartbeat") as mock_hb,
            patch.object(server.time, "sleep", side_effect=StopIteration),
        ):
            with pytest.raises(StopIteration):
                server.heartbeat_task()
        mock_hb.assert_called_once()


# --------------------------------------------------------------------------- #
# send_result
# --------------------------------------------------------------------------- #
class TestSendResult:
    def test_success_posts_expected_payload(self):
        resp = _make_response(200)
        with (
            patch.object(server, "_build_headers", return_value={"H": "1"}),
            patch.object(server.requests, "post", return_value=resp) as mock_post,
        ):
            server.send_result(
                "the answer", "conv-1", "task-1", skill_used="financial_analysis"
            )
        url = mock_post.call_args.args[0]
        payload = mock_post.call_args.kwargs["json"]
        assert url.endswith("/tasks/task-result/")
        assert payload["result"] == "the answer"
        assert payload["conversation_id"] == "conv-1"
        assert payload["task_id"] == "task-1"
        assert payload["skill_used"] == "financial_analysis"

    def test_the_sources_and_status_of_the_answer_are_posted(self):
        source = {"doc_id": "doc-q4", "chunk_id": "doc-q4:3", "title": "q4.md", "page": 2}
        resp = _make_response(200)
        with (
            patch.object(server, "_build_headers", return_value={}),
            patch.object(server.requests, "post", return_value=resp) as mock_post,
        ):
            server.send_result(
                "Revenue was $4.2M.",
                "conv-1",
                "task-1",
                status="not_found",
                reason="not_in_documents",
                sources=[source],
            )
        payload = mock_post.call_args.kwargs["json"]
        assert payload["status"] == "not_found"
        assert payload["reason"] == "not_in_documents"
        assert payload["sources"] == [source]

    def test_no_sources_field_is_posted_when_none_are_given(self):
        resp = _make_response(200)
        with (
            patch.object(server, "_build_headers", return_value={}),
            patch.object(server.requests, "post", return_value=resp) as mock_post,
        ):
            server.send_result("r", "c", "t")
        assert "sources" not in mock_post.call_args.kwargs["json"]

    def test_uses_matching_profile_for_assigned_agent(self, restore_module_state):
        target = server.PROFILES[1]
        target.agent_id = "assignee-xyz"
        resp = _make_response(200)
        with (
            patch.object(server, "_build_headers", return_value={}),
            patch.object(server.requests, "post", return_value=resp) as mock_post,
        ):
            server.send_result(
                "res", "conv", "task", assigned_agent_id="assignee-xyz"
            )
        payload = mock_post.call_args.kwargs["json"]
        assert payload["agent_id"] == "assignee-xyz"
        assert payload["agent_name"] == target.name

    def test_non_200_is_logged_not_raised(self):
        resp = _make_response(404, text="missing")
        with (
            patch.object(server, "_build_headers", return_value={}),
            patch.object(server.requests, "post", return_value=resp),
            patch.object(server.logger, "warning") as mock_warn,
        ):
            server.send_result("r", "c", "t")
        assert mock_warn.called

    def test_exception_is_swallowed(self):
        with (
            patch.object(server, "_build_headers", return_value={}),
            patch.object(server.requests, "post", side_effect=RuntimeError("net")),
            patch.object(server.logger, "error") as mock_err,
        ):
            # Must not raise.
            server.send_result("r", "c", "t")
        assert mock_err.called


# --------------------------------------------------------------------------- #
# send_step
# --------------------------------------------------------------------------- #
class TestSendStep:
    def test_success_posts_step_envelope(self):
        resp = _make_response(200)
        step = {
            "step_type": "thinking",
            "title": "T",
            "detail": "D",
            "metadata": {"k": "v"},
            "timestamp": "2026-01-01T00:00:00+00:00",
        }
        with (
            patch.object(server, "_build_headers", return_value={}),
            patch.object(server.requests, "post", return_value=resp) as mock_post,
        ):
            server.send_step(step, "conv-9", "task-9")
        url = mock_post.call_args.args[0]
        payload = mock_post.call_args.kwargs["json"]
        assert url.endswith("/tasks/task-step/")
        assert payload["step_type"] == "thinking"
        assert payload["title"] == "T"
        assert payload["conversation_id"] == "conv-9"
        assert payload["timestamp"] == "2026-01-01T00:00:00+00:00"

    def test_generates_timestamp_and_handles_none_conversation(self):
        resp = _make_response(200)
        with (
            patch.object(server, "_build_headers", return_value={}),
            patch.object(server.requests, "post", return_value=resp) as mock_post,
        ):
            server.send_step({"step_type": "x"}, None, "task-10")
        payload = mock_post.call_args.kwargs["json"]
        assert payload["conversation_id"] is None
        assert payload["timestamp"]  # auto-filled ISO timestamp
        assert payload["metadata"] == {}

    def test_4xx_logged_quietly_not_raised(self):
        resp = _make_response(404, text="no such endpoint" * 50)
        with (
            patch.object(server, "_build_headers", return_value={}),
            patch.object(server.requests, "post", return_value=resp),
            patch.object(server.logger, "debug") as mock_debug,
        ):
            server.send_step({"step_type": "y"}, "c", "t")
        assert mock_debug.called

    def test_exception_swallowed(self):
        with (
            patch.object(server, "_build_headers", return_value={}),
            patch.object(server.requests, "post", side_effect=RuntimeError("boom")),
        ):
            # No raise.
            server.send_step({"step_type": "z"}, "c", "t")


# --------------------------------------------------------------------------- #
# Lifespan
# --------------------------------------------------------------------------- #
class TestLifespan:
    @pytest.mark.asyncio
    async def test_lifespan_starts_background_threads(self):
        started = []

        class FakeThread:
            def __init__(self, target=None, daemon=None):
                self.target = target
                self.daemon = daemon

            def start(self):
                started.append(self.target)

        order = []
        with (
            patch.object(
                server, "register_agent", side_effect=lambda: order.append("register")
            ) as mock_register,
            patch.object(
                server,
                "fail_abandoned_claims",
                side_effect=lambda: order.append("abandoned") or [],
            ),
            patch.object(threading, "Thread", FakeThread),
        ):
            async with server.lifespan(server.app):
                pass

        mock_register.assert_called_once()
        assert order == ["register", "abandoned"]
        # Heartbeat + task consumer + agent-message consumer = 3 daemon threads.
        assert server.heartbeat_task in started
        assert server._consume_messages in started
        assert server._consume_agent_messages in started

    @pytest.mark.parametrize("mode, warned", [("mock", 1), ("local", 0), ("", 0)])
    async def test_mock_ai_mode_is_one_warning_at_start(self, monkeypatch, caplog, mode, warned):
        monkeypatch.setenv("HORUS_AI_MODE", mode)
        with (
            patch.object(server, "register_agent"),
            patch.object(server, "fail_abandoned_claims", return_value=[]),
            patch.object(threading, "Thread"),
            caplog.at_level("WARNING"),
        ):
            async with server.lifespan(server.app):
                pass
        warnings = [r for r in caplog.records if "Mock AI mode" in r.getMessage()]
        assert len(warnings) == warned
        assert all(r.levelname == "WARNING" for r in warnings)


# --------------------------------------------------------------------------- #
# HTTP endpoints
# --------------------------------------------------------------------------- #
class TestCapabilitiesEndpoint:
    def test_returns_capability_metadata(self, client):
        r = client.get("/capabilities")
        assert r.status_code == 200
        body = r.json()
        assert body["supports_delegation"] is True
        assert body["work_queue"] == server.WORK_QUEUE_NAME
        assert body["capabilities"] == server.AGENT_CAPABILITIES
        assert body["max_delegation_depth"] == server.MAX_DELEGATION_DEPTH


class TestMetricsEndpoint:
    def test_metrics_served(self, client):
        r = client.get("/metrics")
        assert r.status_code == 200


class TestTaskEndpoint:
    def test_empty_body_returns_422(self, client):
        assert client.post("/task", json={}).status_code == 422

    def test_general_success_returns_result(self, client, restore_module_state):
        server.AGENT_ID = "agent-007"
        fake_pipeline = MagicMock()

        async def fake_process_task(task_dict):
            return {"response": "general answer"}

        fake_pipeline.process_task = fake_process_task

        primary = MagicMock()
        primary.type = "general"
        with (
            patch.object(server, "get_primary_profile", return_value=primary),
            patch.object(server, "get_pipeline_for_type", return_value=fake_pipeline),
            patch.object(server, "send_result") as mock_send,
        ):
            r = client.post(
                "/task", json={"query": "hi", "conversation_id": "c-1"}
            )
        assert r.status_code == 200
        body = r.json()
        assert body == {"agent_id": "agent-007", "result": "general answer"}
        # Result was forwarded back to MAS.
        assert mock_send.called
        assert mock_send.call_args.args[0] == "general answer"

    def test_the_answer_contract_reaches_mas(self, client, restore_module_state):
        server.AGENT_ID = "agent-007"
        source = {"doc_id": "doc-q4", "chunk_id": "doc-q4:3", "title": "q4.md", "page": 2}
        fake_pipeline = MagicMock()

        async def fake_process_task(task_dict):
            return {
                "response": "Revenue was $4.2M.",
                "status": "completed",
                "agent_answer": {
                    "status": "ok",
                    "answer": "Revenue was $4.2M.",
                    "sources": [source],
                    "reason": None,
                },
            }

        fake_pipeline.process_task = fake_process_task
        primary = MagicMock()
        primary.type = "general"
        with (
            patch.object(server, "get_primary_profile", return_value=primary),
            patch.object(server, "get_pipeline_for_type", return_value=fake_pipeline),
            patch.object(server, "send_result") as mock_send,
        ):
            r = client.post("/task", json={"query": "q", "conversation_id": "c-1"})
        assert r.json()["result"] == "Revenue was $4.2M."
        assert mock_send.call_args.kwargs["status"] == "completed"
        assert mock_send.call_args.kwargs["sources"] == [source]

    def test_auto_generates_task_id_when_missing(self, client, restore_module_state):
        server.AGENT_ID = "agent-1"
        captured = {}
        fake_pipeline = MagicMock()

        async def fake_process_task(task_dict):
            captured["task_id"] = task_dict["task_id"]
            return {"response": "ok"}

        fake_pipeline.process_task = fake_process_task
        primary = MagicMock()
        primary.type = "general"
        with (
            patch.object(server, "get_primary_profile", return_value=primary),
            patch.object(server, "get_pipeline_for_type", return_value=fake_pipeline),
            patch.object(server, "send_result"),
        ):
            r = client.post("/task", json={"query": "q", "conversation_id": "c"})
        assert r.status_code == 200
        assert captured["task_id"].startswith("task_")

    def test_explicit_task_id_is_preserved(self, client, restore_module_state):
        server.AGENT_ID = "agent-keep"
        captured = {}
        fake_pipeline = MagicMock()

        async def fake_process_task(task_dict):
            captured["task_id"] = task_dict["task_id"]
            return {"response": "ok"}

        fake_pipeline.process_task = fake_process_task
        primary = MagicMock()
        primary.type = "general"
        with (
            patch.object(server, "get_primary_profile", return_value=primary),
            patch.object(server, "get_pipeline_for_type", return_value=fake_pipeline),
            patch.object(server, "send_result"),
        ):
            r = client.post(
                "/task",
                json={"query": "q", "conversation_id": "c", "task_id": "given-123"},
            )
        assert r.status_code == 200
        # The caller-supplied task_id is used verbatim (no auto-generation).
        assert captured["task_id"] == "given-123"

    def test_specialist_success_uses_process_request(self, client, restore_module_state):
        server.AGENT_ID = "writer-1"
        fake_pipeline = MagicMock()

        async def fake_process_request(task_type=None, data=None, extra_parameters=None):
            return "specialist output"

        fake_pipeline.process_request = fake_process_request
        primary = MagicMock()
        primary.type = "writer"
        with (
            patch.object(server, "get_primary_profile", return_value=primary),
            patch.object(server, "get_pipeline_for_type", return_value=fake_pipeline),
            patch.object(server, "send_result") as mock_send,
        ):
            r = client.post(
                "/task",
                json={"query": "draft this", "conversation_id": "c", "operation": "write"},
            )
        assert r.status_code == 200
        assert r.json()["result"] == "specialist output"
        assert mock_send.call_args.args[0] == "specialist output"

    def test_correlation_id_header_is_propagated(self, client, restore_module_state):
        server.AGENT_ID = "agent-corr"
        fake_pipeline = MagicMock()

        async def fake_process_task(task_dict):
            return {"response": "done"}

        fake_pipeline.process_task = fake_process_task
        primary = MagicMock()
        primary.type = "general"
        with (
            patch.object(server, "get_primary_profile", return_value=primary),
            patch.object(server, "get_pipeline_for_type", return_value=fake_pipeline),
            patch.object(server, "send_result"),
            patch.object(server, "set_correlation_id") as mock_set,
        ):
            r = client.post(
                "/task",
                json={"query": "q", "conversation_id": "c"},
                headers={"X-Correlation-ID": "corr-123"},
            )
        assert r.status_code == 200
        mock_set.assert_any_call("corr-123")

    def test_unknown_primary_type_raises_500(self, client_no_reraise, restore_module_state):
        server.AGENT_ID = "agent-x"
        fake_pipeline = MagicMock()
        primary = MagicMock()
        primary.type = "weird-type"
        with (
            patch.object(server, "get_primary_profile", return_value=primary),
            patch.object(server, "get_pipeline_for_type", return_value=fake_pipeline),
            patch.object(server, "send_result") as mock_send,
        ):
            r = client_no_reraise.post("/task", json={"query": "q", "conversation_id": "c"})
        assert r.status_code == 500
        mock_send.assert_not_called()

    def test_pipeline_exception_returns_500_and_counts_error(
        self, client_no_reraise, restore_module_state
    ):
        server.AGENT_ID = "agent-err"
        fake_pipeline = MagicMock()

        async def boom(task_dict):
            raise ValueError("pipeline blew up")

        fake_pipeline.process_task = boom
        primary = MagicMock()
        primary.type = "general"
        with (
            patch.object(server, "get_primary_profile", return_value=primary),
            patch.object(server, "get_pipeline_for_type", return_value=fake_pipeline),
            patch.object(server.agent_errors_total, "labels") as mock_labels,
        ):
            r = client_no_reraise.post("/task", json={"query": "q", "conversation_id": "c"})
        assert r.status_code == 500
        mock_labels.assert_called_with(error_type="task_processing")
