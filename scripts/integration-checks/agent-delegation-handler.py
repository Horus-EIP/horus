"""
test_delegation_handler.py
--------------------------
Unit tests for the DelegationHandler and DelegationChainTracker.

Covers:
    - Chain tracking and loop prevention
    - Delegation requests to MAS (mocked HTTP)
    - Timeout handling
    - Error handling
    - History tracking
"""

from unittest.mock import MagicMock, Mock, patch

import pytest

from ai_agents.delegation_handler import (
    DEFAULT_MAX_DEPTH,
    DelegationChainTracker,
    DelegationHandler,
    DelegationRecord,
)

# ---------------------------------------------------------------------------
# DelegationChainTracker tests
# ---------------------------------------------------------------------------

class TestDelegationChainTracker:
    def test_empty_chain(self):
        tracker = DelegationChainTracker()
        assert tracker.depth == 0
        assert tracker.can_delegate() is True

    def test_add_to_chain(self):
        tracker = DelegationChainTracker()
        tracker.add("agent-a")
        assert tracker.depth == 1
        assert "agent-a" in tracker.chain

    def test_depth_limit(self):
        tracker = DelegationChainTracker(max_depth=3)
        for i in range(3):
            tracker.add(f"agent-{i}")
        assert tracker.can_delegate() is False

    def test_loop_detection(self):
        tracker = DelegationChainTracker()
        tracker.add("agent-a")
        tracker.add("agent-b")
        assert tracker.has_loop("agent-a") is True
        assert tracker.has_loop("agent-c") is False

    def test_default_max_depth(self):
        tracker = DelegationChainTracker()
        assert tracker.max_depth == DEFAULT_MAX_DEPTH


# ---------------------------------------------------------------------------
# DelegationHandler tests
# ---------------------------------------------------------------------------

class TestDelegationHandler:
    @pytest.fixture
    def handler(self):
        return DelegationHandler(
            agent_id="agent-a",
            orchestrator_url="http://mas:8000",
            auth_headers_fn=lambda: {"Authorization": "Bearer test-token"},
            max_depth=5,
            timeout_seconds=10.0,
        )

    @patch("ai_agents.delegation_handler.requests.post")
    def test_delegation_success(self, mock_post, handler):
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "delegation_id": "del-123",
            "status": "completed",
            "result": "Total: $600",
            "agent_id": "agent-b",
        }
        mock_post.return_value = mock_response

        result = handler.delegate("analyst", "Calculate totals", {"amount": 600})

        assert result["status"] == "completed"
        assert result["result"] == "Total: $600"
        assert result["agent_id"] == "agent-b"
        mock_post.assert_called_once()

    @patch("ai_agents.delegation_handler.requests.post")
    def test_delegation_error_response(self, mock_post, handler):
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "delegation_id": "del-456",
            "status": "error",
            "error": "No agent available",
        }
        mock_post.return_value = mock_response

        result = handler.delegate("nonexistent", "Do something")
        assert result["status"] == "error"
        assert "No agent" in result["error"]

    @patch("ai_agents.delegation_handler.requests.post")
    def test_delegation_http_failure(self, mock_post, handler):
        mock_response = Mock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        mock_post.return_value = mock_response

        result = handler.delegate("analyst", "Task")
        assert result["status"] == "error"
        assert "500" in result["error"]

    @patch("ai_agents.delegation_handler.requests.post")
    def test_delegation_timeout(self, mock_post, handler):
        import requests
        mock_post.side_effect = requests.Timeout("Request timed out")

        result = handler.delegate("analyst", "Slow task")
        assert result["status"] == "timeout"

    @patch("ai_agents.delegation_handler.requests.post")
    def test_delegation_exception(self, mock_post, handler):
        mock_post.side_effect = ConnectionError("Network unreachable")

        result = handler.delegate("analyst", "Task")
        assert result["status"] == "error"
        assert "exception" in result["error"].lower() or "Network" in result["error"]

    def test_delegation_depth_limit(self, handler):
        for i in range(5):
            handler.chain_tracker.add(f"agent-{i}")

        result = handler.delegate("analyst", "Task")
        assert result["status"] == "error"
        assert "depth" in result["error"].lower()

    @patch("ai_agents.delegation_handler.requests.post")
    def test_delegation_history(self, mock_post, handler):
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "delegation_id": "del-789",
            "status": "completed",
            "result": "Done",
            "agent_id": "agent-b",
        }
        mock_post.return_value = mock_response

        handler.delegate("analyst", "Task 1")
        handler.delegate("researcher", "Task 2")

        history = handler.get_history()
        assert len(history) == 2
        assert history[0]["to_agent_type"] == "analyst"
        assert history[1]["to_agent_type"] == "researcher"

    @patch("ai_agents.delegation_handler.requests.post")
    def test_delegation_sends_correct_payload(self, mock_post, handler):
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "delegation_id": "del-x",
            "status": "completed",
            "result": "Ok",
        }
        mock_post.return_value = mock_response

        handler.delegate(
            "analyst",
            "Calculate total",
            {"amounts": [100, 200]},
            conversation_id="conv-1",
        )

        call_args = mock_post.call_args
        payload = call_args.kwargs.get("json") or call_args[1].get("json")
        assert payload["sender_agent_id"] == "agent-a"
        assert payload["to_agent_type"] == "analyst"
        assert payload["request"] == "Calculate total"
        assert payload["data"]["amounts"] == [100, 200]
        assert payload["conversation_id"] == "conv-1"

    @patch("ai_agents.delegation_handler.requests.post")
    def test_delegation_context_accumulated(self, mock_post, handler):
        """Context from upstream agents is forwarded with the current entry appended."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "delegation_id": "del-ctx",
            "status": "completed",
            "result": "Ok",
        }
        mock_post.return_value = mock_response

        prior = [
            {"agent_id": "agent-0", "request": "Initial search", "data": {"q": "x"}},
        ]

        handler.delegate(
            "analyst",
            "Calculate total",
            {"amounts": [100]},
            delegation_context=prior,
        )

        call_args = mock_post.call_args
        payload = call_args.kwargs.get("json") or call_args[1].get("json")
        ctx = payload["delegation_context"]
        assert len(ctx) == 2
        assert ctx[0]["agent_id"] == "agent-0"
        assert ctx[0]["request"] == "Initial search"
        assert ctx[1]["agent_id"] == "agent-a"
        assert ctx[1]["request"] == "Calculate total"
        assert ctx[1]["data"] == {"amounts": [100]}

    @patch("ai_agents.delegation_handler.requests.post")
    def test_delegation_context_empty_by_default(self, mock_post, handler):
        """When no prior context is provided, the payload still includes the sender entry."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "delegation_id": "del-y",
            "status": "completed",
            "result": "Ok",
        }
        mock_post.return_value = mock_response

        handler.delegate("analyst", "Solo task")

        call_args = mock_post.call_args
        payload = call_args.kwargs.get("json") or call_args[1].get("json")
        ctx = payload["delegation_context"]
        assert len(ctx) == 1
        assert ctx[0]["agent_id"] == "agent-a"
        assert ctx[0]["request"] == "Solo task"

    @patch("ai_agents.delegation_handler.requests.post")
    def test_delegation_includes_auth_headers(self, mock_post, handler):
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "delegation_id": "del-x",
            "status": "completed",
            "result": "Ok",
        }
        mock_post.return_value = mock_response

        handler.delegate("analyst", "Task")

        call_args = mock_post.call_args
        headers = call_args.kwargs.get("headers") or call_args[1].get("headers")
        assert headers["Authorization"] == "Bearer test-token"
        assert headers["Content-Type"] == "application/json"

    def test_reset_chain(self, handler):
        handler.chain_tracker.add("agent-1")
        handler.chain_tracker.add("agent-2")
        assert handler.chain_tracker.depth == 2
        handler.reset_chain()
        assert handler.chain_tracker.depth == 0
        assert handler.chain_tracker.can_delegate() is True


class TestDelegationRecord:
    def test_create_record(self):
        record = DelegationRecord(
            delegation_id="del-1",
            to_agent_type="analyst",
            request="Do work",
        )
        assert record.status == "pending"
        assert record.result is None
        assert record.error is None
