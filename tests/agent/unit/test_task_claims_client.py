from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests

from agent_server import server
from agent_server.consumers import TaskClaim


def _response(status_code: int, json_data=None, text: str = ""):
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = {} if json_data is None else json_data
    response.text = text
    return response


@pytest.fixture
def mas(monkeypatch):
    monkeypatch.setattr(server, "_build_headers", lambda **_kwargs: {"X-API-Key": "a:k"})
    post = MagicMock(return_value=_response(200))
    monkeypatch.setattr(server.requests, "post", post)
    return post


class TestClaimTask:
    def test_a_claim_names_this_worker_and_its_run(self, mas):
        assert server.claim_task("task-1", "agent-9") is TaskClaim.CLAIMED

        url = mas.call_args.args[0]
        body = mas.call_args.kwargs["json"]
        assert url.endswith("/tasks/task-1/claim")
        assert body == {
            "agent_id": "agent-9",
            "worker_id": server.WORKER_ID,
            "run_id": server.WORKER_RUN_ID,
        }
        assert mas.call_args.kwargs["timeout"] == server._CLAIM_TIMEOUT_SECONDS

    @pytest.mark.parametrize("status_code", [404, 409])
    def test_a_task_mas_will_not_run_is_refused(self, mas, status_code):
        mas.return_value = _response(status_code, text="Task was already claimed")

        assert server.claim_task("task-1", "agent-9") is TaskClaim.REFUSED

    @pytest.mark.parametrize("status_code", [403, 422])
    def test_a_claim_mas_will_never_accept_is_refused_not_retried(self, mas, status_code):
        mas.return_value = _response(status_code, {"detail": "not allowed"})

        assert server.claim_task("task-1", "agent-9") is TaskClaim.REFUSED

    def test_a_task_mas_does_not_know_is_refused(self, mas):
        mas.return_value = _response(404, {"detail": "Task not found"})

        assert server.claim_task("task-1", "agent-9") is TaskClaim.REFUSED

    def test_a_mas_without_the_claim_endpoint_lets_the_task_run(self, mas):
        mas.return_value = _response(404, {"detail": "Not Found"})

        assert server.claim_task("task-1", "agent-9") is TaskClaim.CLAIMED

    @pytest.mark.parametrize("status_code", [500, 503])
    def test_a_server_error_leaves_the_claim_unconfirmed(self, mas, status_code):
        mas.return_value = _response(status_code)

        assert server.claim_task("task-1", "agent-9") is TaskClaim.UNAVAILABLE

    def test_an_unreachable_mas_leaves_the_claim_unconfirmed(self, mas):
        mas.side_effect = requests.exceptions.ConnectionError("refused")

        assert server.claim_task("task-1", "agent-9") is TaskClaim.UNAVAILABLE

    def test_an_expired_token_is_renewed_once(self, mas, monkeypatch):
        monkeypatch.setattr(server, "ORCHESTRATOR_TOKEN", None)
        mas.side_effect = [_response(401), _response(200)]
        with patch.object(server, "_invalidate_cached_mas_token") as invalidate:
            assert server.claim_task("task-1", "agent-9") is TaskClaim.CLAIMED
        invalidate.assert_called_once()
        assert mas.call_count == 2


class TestAbandonedClaims:
    def test_mas_is_told_which_run_is_current(self, mas):
        mas.return_value = _response(200, {"failed": ["t-1", "t-2"]})

        assert server.fail_abandoned_claims() == ["t-1", "t-2"]

        assert mas.call_args.args[0].endswith("/tasks/abandoned-claims")
        assert mas.call_args.kwargs["json"] == {
            "worker_id": server.WORKER_ID,
            "run_id": server.WORKER_RUN_ID,
        }

    def test_an_unreachable_mas_does_not_stop_the_start(self, mas):
        mas.side_effect = requests.exceptions.ConnectionError("refused")

        assert server.fail_abandoned_claims() == []

    def test_a_refusal_does_not_stop_the_start(self, mas):
        mas.return_value = _response(403, text="not allowed")

        assert server.fail_abandoned_claims() == []


class TestWorkerIdentity:
    def test_each_process_run_has_its_own_id(self):
        assert server.WORKER_ID
        assert len(server.WORKER_RUN_ID) == 32


class TestFailedResult:
    def test_a_failed_task_is_sent_with_its_status_and_reason(self, mas):
        server.send_result(
            "The model did not finish its answer within 900s",
            "conv-1",
            "task-1",
            status="failed",
            reason="timeout",
        )

        body = mas.call_args.kwargs["json"]
        assert body["status"] == "failed"
        assert body["reason"] == "timeout"

    def test_an_answer_is_sent_as_completed_without_a_reason(self, mas):
        server.send_result("ANSWER", "conv-1", "task-1")

        body = mas.call_args.kwargs["json"]
        assert body["status"] == "completed"
        assert "reason" not in body
