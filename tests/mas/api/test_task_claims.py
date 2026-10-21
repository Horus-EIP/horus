from __future__ import annotations

from unittest.mock import patch

import httpx
import pytest
from fastapi import FastAPI

from auth.auth_tool_functions import verify_agent_api_key
from core.task_events import read_task_events
from db.database import get_db
from db.models import Agents, Task, TaskResult
from db.models.agent_types import AgentTypes
from tasks import routes

WORKER = "agent-container-1"
TIMEOUT_TEXT = (
    "The model did not finish its answer within 900s, so this request was stopped."
)


def _stored(db, task_id):
    db.expire_all()
    return db.get(Task, task_id)


def _add_agent(db, agent_id, agent_type):
    db.add(Agents(id=agent_id, name=agent_id, type=agent_type, api_key=f"hash-{agent_id}"))
    db.commit()


def _add_task(
    db,
    task_id,
    *,
    status="running",
    parent_task_id=None,
    claimed_by=None,
    claim_run=None,
    future_actions=None,
    agent_id="agent-1",
):
    db.add(
        Task(
            id=task_id,
            conversation_id=7,
            agent_id=agent_id,
            status=status,
            query="What was Q4 revenue?",
            parent_task_id=parent_task_id,
            claimed_by=claimed_by,
            claim_run=claim_run,
        )
    )
    db.add(
        TaskResult(
            id=f"result-{task_id}",
            task_id=task_id,
            history=[],
            future_actions=future_actions or [],
        )
    )
    db.commit()


@pytest.fixture
def agent_client(routing_db):
    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[get_db] = lambda: routing_db
    app.dependency_overrides[verify_agent_api_key] = lambda: ("agent-1", "key")
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://mas")


@pytest.fixture
def agent_client_for(routing_db):
    def _factory(agent_id):
        app = FastAPI()
        app.include_router(routes.router)
        app.dependency_overrides[get_db] = lambda: routing_db
        app.dependency_overrides[verify_agent_api_key] = lambda: (agent_id, "key")
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://mas"
        )

    return _factory


@pytest.fixture
def chat_messages():
    with patch.object(routes, "add_messages", return_value={"id": 5}) as add_messages:
        yield add_messages


async def _post_claim(client, task_id, run="run-1", agent_id="agent-1"):
    return await client.post(
        f"/tasks/{task_id}/claim",
        json={"agent_id": agent_id, "worker_id": WORKER, "run_id": run},
    )


async def _claim(client, task_id, run="run-1", agent_id="agent-1"):
    async with client:
        return await _post_claim(client, task_id, run=run, agent_id=agent_id)


class TestClaim:
    async def test_the_first_claim_records_the_worker_and_starts_the_task(
        self, agent_client, routing_db
    ):
        _add_task(routing_db, "t1", status="queued")

        response = await _claim(agent_client, "t1")

        assert response.status_code == 200
        task = _stored(routing_db, "t1")
        assert task.status == "running"
        assert (task.claimed_by, task.claim_run) == (WORKER, "run-1")
        assert task.started_at is not None

    async def test_a_claim_by_another_run_is_refused(self, agent_client, routing_db):
        _add_task(routing_db, "t1", claimed_by=WORKER, claim_run="run-1")

        response = await _claim(agent_client, "t1", run="run-2")

        assert response.status_code == 409
        assert _stored(routing_db, "t1").claim_run == "run-1"

    async def test_a_claim_whose_answer_was_lost_can_be_sent_again_by_the_same_run(
        self, agent_client, routing_db
    ):
        _add_task(routing_db, "t1", status="queued")
        async with agent_client:
            first = await _post_claim(agent_client, "t1")
            started_at = _stored(routing_db, "t1").started_at
            again = await _post_claim(agent_client, "t1")

        assert (first.status_code, again.status_code) == (200, 200)
        task = _stored(routing_db, "t1")
        assert (task.claimed_by, task.claim_run) == (WORKER, "run-1")
        assert task.started_at == started_at

    async def test_a_claim_by_another_worker_is_refused(self, agent_client, routing_db):
        _add_task(routing_db, "t1", claimed_by="agent-container-2", claim_run="run-1")

        response = await _claim(agent_client, "t1")

        assert response.status_code == 409
        assert _stored(routing_db, "t1").claimed_by == "agent-container-2"

    @pytest.mark.parametrize("status", ["canceled", "completed", "failed"])
    async def test_a_finished_or_cancelled_task_is_not_run(
        self, agent_client, routing_db, status
    ):
        _add_task(routing_db, "t1", status=status)

        response = await _claim(agent_client, "t1")

        assert response.status_code == 409
        assert _stored(routing_db, "t1").claimed_by is None

    async def test_an_unknown_task_cannot_be_claimed(self, agent_client):
        assert (await _claim(agent_client, "missing")).status_code == 404

    async def test_only_the_assigned_agent_can_claim(self, agent_client, routing_db):
        _add_task(routing_db, "t1")

        response = await _claim(agent_client, "t1", agent_id="agent-2")

        assert response.status_code == 403

    async def test_a_worker_outside_the_assignee_pool_is_refused(self, agent_client, routing_db):
        _add_agent(routing_db, "agent-1", AgentTypes.GENERAL)
        _add_agent(routing_db, "agent-writer", AgentTypes.WRITER)
        _add_task(routing_db, "t1", agent_id="agent-writer")

        response = await _claim(agent_client, "t1", agent_id="agent-writer")

        assert response.status_code == 403
        assert _stored(routing_db, "t1").status == "running"

    async def test_a_task_whose_agent_left_the_directory_fails_at_once(
        self, agent_client, routing_db, chat_messages
    ):
        _add_agent(routing_db, "agent-1", AgentTypes.GENERAL)
        _add_task(routing_db, "root", agent_id="manager")
        _add_task(routing_db, "step-1", parent_task_id="root", agent_id="agent-before-restart")

        response = await _claim(agent_client, "step-1", agent_id="agent-before-restart")

        assert response.status_code == 409
        assert _stored(routing_db, "step-1").status == "failed"
        assert _stored(routing_db, "step-1").claimed_by is None
        assert _stored(routing_db, "root").status == "failed"
        (event,) = read_task_events("root")
        assert event["type"] == "error"
        assert event["data"]["reason"] == routes.AGENT_UNREGISTERED_REASON
        assert event["data"]["content"] == routes.AGENT_UNREGISTERED_TEXT
        chat_messages.assert_called_once()


class TestAbandonedClaims:
    async def test_worker_id_for_an_agent_of_another_type_fails_none_of_its_tasks(
        self, agent_client_for, routing_db, chat_messages
    ):
        _add_agent(routing_db, "agent-1", AgentTypes.GENERAL)
        _add_agent(routing_db, "agent-writer", AgentTypes.WRITER)
        _add_task(
            routing_db,
            "general-task",
            claimed_by=WORKER,
            claim_run="run-old",
            agent_id="agent-1",
        )

        client = agent_client_for("agent-writer")
        async with client:
            response = await client.post(
                "/tasks/abandoned-claims",
                json={"worker_id": WORKER, "run_id": "run-new"},
            )

        assert response.status_code == 200
        assert response.json() == {"failed": []}
        assert _stored(routing_db, "general-task").status == "running"
        chat_messages.assert_not_called()

    async def test_tasks_left_by_an_earlier_run_of_the_worker_fail(
        self, agent_client, routing_db, chat_messages
    ):
        _add_agent(routing_db, "agent-1", AgentTypes.GENERAL)
        _add_task(routing_db, "old", claimed_by=WORKER, claim_run="run-old")
        _add_task(routing_db, "current", claimed_by=WORKER, claim_run="run-new")
        _add_task(routing_db, "other-worker", claimed_by="agent-container-2", claim_run="x")
        _add_task(routing_db, "done", status="completed", claimed_by=WORKER, claim_run="run-old")

        async with agent_client:
            response = await agent_client.post(
                "/tasks/abandoned-claims", json={"worker_id": WORKER, "run_id": "run-new"}
            )

        assert response.json() == {"failed": ["old"]}
        old = _stored(routing_db, "old")
        assert old.status == "failed"
        assert old.result.result_data == routes.AGENT_RESTARTED_TEXT
        assert _stored(routing_db, "current").status == "running"
        assert _stored(routing_db, "other-worker").status == "running"
        assert _stored(routing_db, "done").status == "completed"
        (event,) = read_task_events("old")
        assert event["type"] == "error"
        assert event["data"]["status"] == "failed"
        assert event["data"]["reason"] == routes.AGENT_RESTARTED_REASON
        chat_messages.assert_called_once()

    async def test_an_abandoned_chain_step_fails_its_whole_request(
        self, agent_client, routing_db, chat_messages
    ):
        _add_task(routing_db, "root")
        _add_task(routing_db, "step-1", parent_task_id="root", claimed_by=WORKER, claim_run="old")

        async with agent_client:
            await agent_client.post(
                "/tasks/abandoned-claims", json={"worker_id": WORKER, "run_id": "new"}
            )

        assert _stored(routing_db, "root").status == "failed"
        assert _stored(routing_db, "step-1").status == "failed"
        assert [event["type"] for event in read_task_events("root")] == ["error"]
        assert read_task_events("step-1") == []

    async def test_tasks_claimed_by_a_recreated_container_fail_once_its_agents_are_gone(
        self, agent_client, routing_db, chat_messages
    ):
        _add_agent(routing_db, "agent-1", AgentTypes.GENERAL)
        _add_task(
            routing_db,
            "orphan",
            claimed_by="old-container-host",
            claim_run="run-old",
            agent_id="agent-before-recreate",
        )
        _add_task(routing_db, "alive", claimed_by="agent-container-2", claim_run="x")
        _add_task(routing_db, "waiting", status="queued", agent_id="agent-before-recreate")

        async with agent_client:
            response = await agent_client.post(
                "/tasks/abandoned-claims", json={"worker_id": WORKER, "run_id": "run-new"}
            )

        assert response.json() == {"failed": ["orphan"]}
        assert _stored(routing_db, "orphan").status == "failed"
        assert _stored(routing_db, "alive").status == "running"
        assert _stored(routing_db, "waiting").status == "queued"
        (event,) = read_task_events("orphan")
        assert event["data"]["reason"] == routes.AGENT_RESTARTED_REASON


async def _report(client, task_id, **over):
    body = {
        "task_id": task_id,
        "agent_id": "agent-1",
        "result": TIMEOUT_TEXT,
        "status": "failed",
        "reason": "timeout",
        "agent_name": "General-Assistant",
    }
    body.update(over)
    async with client:
        return await client.post("/tasks/task-result/", json=body)


class TestFailedResult:
    async def test_a_timed_out_answer_fails_the_task_with_a_stored_error_event(
        self, agent_client, routing_db, chat_messages
    ):
        _add_task(routing_db, "t1", claimed_by=WORKER, claim_run="run-1")

        with patch.object(routes, "aggregate_results") as aggregate:
            response = await _report(agent_client, "t1")

        assert response.status_code == 200
        task = _stored(routing_db, "t1")
        assert task.status == "failed"
        assert task.result.result_data == TIMEOUT_TEXT
        (event,) = read_task_events("t1")
        assert event["type"] == "error"
        assert event["data"]["status"] == "failed"
        assert event["data"]["reason"] == "timeout"
        assert event["data"]["content"] == TIMEOUT_TEXT
        assert event["data"]["agent_name"] == "General-Assistant"
        aggregate.assert_not_called()
        assert chat_messages.call_args.args[:2] == ("assistant", TIMEOUT_TEXT)

    async def test_a_failed_chain_step_fails_the_request_and_stops_the_chain(
        self, agent_client, routing_db, chat_messages
    ):
        _add_task(routing_db, "root")
        _add_task(
            routing_db,
            "step-1",
            parent_task_id="root",
            future_actions=[["agent-2", "write the summary"]],
        )

        with patch.object(routes, "_publish_task_to_work_queue") as publish, patch.object(
            routes, "manager_review_step"
        ) as review:
            await _report(agent_client, "step-1")

        assert _stored(routing_db, "root").status == "failed"
        assert _stored(routing_db, "step-1").result.future_actions == []
        publish.assert_not_called()
        review.assert_not_called()
        assert [event["type"] for event in read_task_events("root")] == ["error"]

    async def test_a_failure_after_the_task_timed_out_adds_no_second_message(
        self, agent_client, routing_db, chat_messages
    ):
        _add_task(routing_db, "t1", status="canceled")

        response = await _report(agent_client, "t1")

        assert response.status_code == 200
        assert _stored(routing_db, "t1").status == "canceled"
        assert read_task_events("t1") == []
        chat_messages.assert_not_called()

    async def test_an_answer_without_a_status_still_completes_the_task(
        self, agent_client, routing_db, chat_messages
    ):
        _add_task(routing_db, "t1")

        async with agent_client:
            response = await agent_client.post(
                "/tasks/task-result/",
                json={"task_id": "t1", "agent_id": "agent-1", "result": "Q4 revenue was $4.2M."},
            )

        assert response.status_code == 200
        assert _stored(routing_db, "t1").status == "completed"
        assert read_task_events("t1")[-1]["type"] == "result"
