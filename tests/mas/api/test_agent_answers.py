from __future__ import annotations

import json
from unittest.mock import patch

import httpx
import pytest
from fastapi import FastAPI

from auth.auth_tool_functions import get_current_user, verify_agent_api_key
from core.task_events import read_task_events
from db.database import get_db
from db.models import Messages, Task, TaskResult
from tasks import agent_answers, routes

WORKER = "agent-container-1"
QUESTION = "What was the Q4 2025 revenue?"
Q4_SOURCE = {
    "doc_id": "doc-q4",
    "chunk_id": "doc-q4:3",
    "title": "1_Q4_2025_Financial_Report.md",
    "page": 2,
}
EXPENSE_SOURCE = {
    "doc_id": "doc-expense",
    "chunk_id": "doc-expense:0",
    "title": "4_Expense_Policy.md",
    "page": None,
}
HANDBOOK_SOURCE = {
    "doc_id": "doc-handbook",
    "chunk_id": "doc-handbook:7",
    "title": "2_Employee_Handbook.md",
    "page": None,
}


def _stored(db, task_id):
    db.expire_all()
    return db.get(Task, task_id)


def _add_task(
    db,
    task_id,
    *,
    query=QUESTION,
    parent_task_id=None,
    order=0,
    history=None,
    future_actions=None,
    sources=None,
    status="running",
):
    db.add(
        Task(
            id=task_id,
            conversation_id=7,
            agent_id="agent-1",
            status=status,
            query=query,
            parent_task_id=parent_task_id,
            order=order,
            claimed_by=WORKER,
            claim_run="run-1",
        )
    )
    db.add(
        TaskResult(
            id=f"result-{task_id}",
            task_id=task_id,
            history=history if history is not None else [{"role": "user", "message": query}],
            future_actions=future_actions or [],
            sources=sources,
        )
    )
    db.commit()


def _dispatched(task_id, demand=QUESTION, **extra):
    payload = {
        "conversation_id": 7,
        "task_id": task_id,
        "demand": demand,
        "skill_used": None,
        "files": [],
        "assigned_agent_id": "agent-1",
        **extra,
    }
    agent_answers.remember_dispatch(task_id, payload)
    return payload


@pytest.fixture
def agent_client(routing_db):
    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[get_db] = lambda: routing_db
    app.dependency_overrides[verify_agent_api_key] = lambda: ("agent-1", "key")
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://mas")


@pytest.fixture
def user_client(routing_db):
    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[get_db] = lambda: routing_db
    app.dependency_overrides[get_current_user] = lambda: {
        "id": 3,
        "username": "user",
        "role": "user",
    }
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://mas")


@pytest.fixture
def work_queue():
    with patch.object(routes, "_publish_task_to_work_queue") as publish:
        yield publish


async def _report(client, task_id, **over):
    body = {
        "task_id": task_id,
        "agent_id": "agent-1",
        "agent_name": "Finance-Analyst",
        "result": "Q4 2025 revenue was $4.2M.",
        "status": "completed",
        **over,
    }
    async with client:
        return await client.post("/tasks/task-result/", json=body)


def _not_found(**over):
    return {
        "result": "The passages do not give the Q4 2025 revenue.",
        "status": "not_found",
        "reason": "not_in_documents",
        "sources": [],
        **over,
    }


def _events(task_id, kind=None):
    return [event for event in read_task_events(task_id) if kind is None or event["type"] == kind]


class TestAnswerSources:
    async def test_an_answer_keeps_the_sources_it_cites(
        self, agent_client, routing_db, work_queue
    ):
        _add_task(routing_db, "t1")

        response = await _report(agent_client, "t1", sources=[Q4_SOURCE])

        assert response.status_code == 200
        task = _stored(routing_db, "t1")
        assert task.status == "completed"
        assert task.result.sources == [Q4_SOURCE]
        (result,) = _events("t1", "result")
        assert result["data"]["sources"] == [Q4_SOURCE]
        message = routing_db.query(Messages).filter(Messages.conversation_id == 7).one()
        assert message.sources == [Q4_SOURCE]

    async def test_the_task_detail_returns_the_sources(
        self, agent_client, user_client, routing_db, work_queue
    ):
        _add_task(routing_db, "t1")
        await _report(agent_client, "t1", sources=[Q4_SOURCE])

        async with user_client:
            detail = (await user_client.get("/tasks/t1")).json()

        assert detail["sources"] == [Q4_SOURCE]

    async def test_a_source_page_is_a_number(self, agent_client, routing_db, work_queue):
        _add_task(routing_db, "t1")

        await _report(agent_client, "t1", sources=[{**Q4_SOURCE, "page": "2"}])

        assert _stored(routing_db, "t1").result.sources == [Q4_SOURCE]

    async def test_a_chain_keeps_every_source_once(self, agent_client, routing_db, work_queue):
        _add_task(routing_db, "root")
        _add_task(
            routing_db,
            "step-1",
            parent_task_id="root",
            order=1,
            status="completed",
            sources=[Q4_SOURCE, EXPENSE_SOURCE],
        )
        _add_task(routing_db, "step-2", parent_task_id="root", order=2)

        with patch.object(routes, "aggregate_results", return_value="Combined briefing"):
            await _report(agent_client, "step-2", sources=[EXPENSE_SOURCE, HANDBOOK_SOURCE])

        root = _stored(routing_db, "root")
        assert root.status == "completed"
        assert root.result.sources == [Q4_SOURCE, EXPENSE_SOURCE, HANDBOOK_SOURCE]
        (result,) = _events("root", "result")
        assert result["data"]["content"] == "Combined briefing"
        assert result["data"]["sources"] == [Q4_SOURCE, EXPENSE_SOURCE, HANDBOOK_SOURCE]


class TestNotFound:
    async def test_the_first_not_found_is_tried_again_with_another_query(
        self, agent_client, routing_db, work_queue
    ):
        _add_task(routing_db, "t1")
        _dispatched("t1")

        response = await _report(agent_client, "t1", **_not_found())

        assert response.status_code == 200
        work_queue.assert_called_once()
        _db, agent_id, payload = work_queue.call_args.args
        assert agent_id == "agent-1"
        assert payload["attempt"] == 2
        assert payload["retrieval_query"] == "Q4 2025 revenue"
        assert payload["demand"] == QUESTION
        task = _stored(routing_db, "t1")
        assert task.status == "running"
        assert (task.claimed_by, task.claim_run) == (None, None)
        assert task.result.history[-1] == {
            "role": "assistant",
            "message": "The passages do not give the Q4 2025 revenue.",
            "status": "not_found",
            "reason": "not_in_documents",
            "attempt": 1,
        }
        (retrying,) = _events("t1", "progress")
        assert retrying["data"]["status"] == "retrying"
        assert retrying["data"]["attempt"] == 2
        assert _events("t1", "result") == []
        assert routing_db.query(Messages).count() == 0

    async def test_a_second_not_found_ends_with_an_honest_answer(
        self, agent_client, routing_db, work_queue
    ):
        _add_task(routing_db, "t1")
        _dispatched("t1", attempt=2, retrieval_query="Q4 2025 revenue")

        await _report(agent_client, "t1", **_not_found())

        work_queue.assert_not_called()
        task = _stored(routing_db, "t1")
        assert task.status == "completed"
        assert task.result.result_data == agent_answers.NOT_IN_DOCUMENTS_TEXT
        (result,) = _events("t1", "result")
        assert result["data"]["content"] == agent_answers.NOT_IN_DOCUMENTS_TEXT
        assert result["data"]["sources"] == []
        message = routing_db.query(Messages).one()
        assert message.content == agent_answers.NOT_IN_DOCUMENTS_TEXT

    async def test_without_another_query_the_answer_is_honest_at_once(
        self, agent_client, routing_db, work_queue
    ):
        _add_task(routing_db, "t1", query="revenue")
        _dispatched("t1", demand="revenue")

        await _report(agent_client, "t1", **_not_found())

        work_queue.assert_not_called()
        assert _stored(routing_db, "t1").result.result_data == agent_answers.NOT_IN_DOCUMENTS_TEXT

    async def test_an_answer_not_found_after_a_restart_of_mas_is_honest_at_once(
        self, agent_client, routing_db, work_queue
    ):
        _add_task(routing_db, "t1")

        await _report(agent_client, "t1", **_not_found())

        work_queue.assert_not_called()
        assert _stored(routing_db, "t1").status == "completed"

    async def test_a_chain_step_is_tried_again_with_the_user_question(
        self, agent_client, routing_db, work_queue
    ):
        _add_task(routing_db, "root", query="How did Q4 revenue compare with the budget?")
        _add_task(
            routing_db,
            "step-1",
            query="=== Original user demand ===\n...transcript...",
            parent_task_id="root",
            order=1,
            future_actions=[["agent-2", "write the summary"]],
        )
        _dispatched(
            "step-1",
            demand="=== Original user demand ===\n...transcript...",
            retrieval_query="find the Q4 revenue",
        )

        await _report(agent_client, "step-1", **_not_found())

        payload = work_queue.call_args.args[2]
        assert payload["retrieval_query"] == "How did Q4 revenue compare with the budget?"
        (retrying,) = _events("root", "progress")
        assert retrying["data"]["status"] == "retrying"

    async def test_a_step_of_a_cancelled_request_is_not_tried_again(
        self, agent_client, routing_db, work_queue
    ):
        _add_task(routing_db, "root", status="canceled")
        _add_task(routing_db, "step-1", parent_task_id="root", order=1)
        _dispatched("step-1", retrieval_query="find the Q4 revenue")

        with patch.object(routes, "aggregate_results", return_value="Combined briefing"):
            await _report(agent_client, "step-1", **_not_found())

        work_queue.assert_not_called()
        statuses = [event["data"].get("status") for event in _events("root", "progress")]
        assert "retrying" not in statuses

    async def test_a_task_with_inline_files_is_not_tried_again(
        self, agent_client, routing_db, work_queue
    ):
        _add_task(routing_db, "t1")
        _dispatched(
            "t1",
            files=[{"source": "inline", "filename": "notes.txt", "content_b64": "bm90ZXM="}],
        )

        await _report(agent_client, "t1", **_not_found())

        work_queue.assert_not_called()
        assert _stored(routing_db, "t1").status == "completed"

    async def test_a_late_not_found_after_a_cancel_starts_nothing(
        self, agent_client, routing_db, work_queue
    ):
        _add_task(routing_db, "t1", status="canceled")
        _dispatched("t1")

        await _report(agent_client, "t1", **_not_found())

        work_queue.assert_not_called()
        assert _events("t1", "progress") == []


    async def test_a_second_attempt_that_cannot_be_published_fails_the_task(
        self, agent_client, routing_db
    ):
        _add_task(routing_db, "t1")
        _dispatched("t1")

        with patch.object(
            routes,
            "_publish_task_to_work_queue",
            side_effect=RuntimeError("RabbitMQ could not route a task"),
        ):
            response = await _report(agent_client, "t1", **_not_found())

        assert response.status_code == 200
        assert _stored(routing_db, "t1").status == "failed"
        (error,) = _events("t1", "error")
        assert error["data"]["reason"] == "dispatch_failed"


class TestFailedAnswer:
    async def test_an_unreadable_answer_is_tried_once_more(
        self, agent_client, routing_db, work_queue
    ):
        _add_task(routing_db, "t1")
        _dispatched("t1")

        await _report(
            agent_client,
            "t1",
            result="The model's answer could not be read.",
            status="failed",
            reason="invalid_output",
        )

        payload = work_queue.call_args.args[2]
        assert payload["attempt"] == 2
        assert _stored(routing_db, "t1").status == "running"
        assert _events("t1", "error") == []

    async def test_a_second_failure_fails_the_task(self, agent_client, routing_db, work_queue):
        _add_task(routing_db, "t1")
        _dispatched("t1", attempt=2)

        await _report(
            agent_client,
            "t1",
            result="The model's answer could not be read.",
            status="failed",
            reason="invalid_output",
        )

        work_queue.assert_not_called()
        assert _stored(routing_db, "t1").status == "failed"
        (error,) = _events("t1", "error")
        assert error["data"]["reason"] == "invalid_output"

    async def test_a_timed_out_answer_is_not_tried_again(
        self, agent_client, routing_db, work_queue
    ):
        _add_task(routing_db, "t1")
        _dispatched("t1")

        await _report(
            agent_client,
            "t1",
            result="The model took too long to respond.",
            status="failed",
            reason="timeout",
        )

        work_queue.assert_not_called()
        assert _stored(routing_db, "t1").status == "failed"


class TestDispatchRecord:
    async def test_a_dispatch_keeps_what_a_second_attempt_needs(self, routing_db):
        payload = {
            "conversation_id": 7,
            "task_id": "t1",
            "demand": QUESTION,
            "files": [{"source": "knowledge_store", "filename": "q4.md", "doc_id": "doc-q4"}],
            "assigned_agent_id": "agent-9",
            "assigned_agent_api_key": "secret-key",
        }

        agent_answers.remember_dispatch("t1", payload)
        record = agent_answers.recall_dispatch("t1")

        assert record["attempt"] == 1
        assert "assigned_agent_api_key" not in record["payload"]
        assert record["payload"]["files"] == payload["files"]
        stored = agent_answers.redis_db.get(agent_answers.dispatch_record_key("t1"))
        assert "secret-key" not in stored
        assert json.loads(stored)["payload"]["demand"] == QUESTION

    async def test_the_content_of_inline_files_is_never_kept(self, routing_db):
        agent_answers.remember_dispatch(
            "t1",
            {
                "task_id": "t1",
                "demand": QUESTION,
                "files": [{"source": "inline", "filename": "a.txt", "content_b64": "c2VjcmV0"}],
            },
        )

        stored = agent_answers.redis_db.get(agent_answers.dispatch_record_key("t1"))
        assert "c2VjcmV0" not in stored
        assert agent_answers.recall_dispatch("t1")["payload"] is None

    async def test_a_store_outage_only_costs_the_second_attempt(self, monkeypatch):
        class _Down:
            def set(self, *_args, **_kwargs):
                raise ConnectionError("redis down")

            def get(self, *_args, **_kwargs):
                raise ConnectionError("redis down")

        monkeypatch.setattr(agent_answers, "redis_db", _Down())

        agent_answers.remember_dispatch("t1", {"task_id": "t1", "demand": QUESTION})

        assert agent_answers.recall_dispatch("t1") is None
