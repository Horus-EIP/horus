from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from core.rabbitmq_manager import WorkQueueFull
from core.task_events import read_task_events
from db.models import Task, TaskResult
from tasks import routes
from tasks.task_jobs import task_jobs
from tasks.work_queue_line import work_queue_line

QUEUE = "horus.work.finance"
QUESTION = "Summarise the Q4 2025 financial report"


def _stored(db, task_id):
    db.expire_all()
    return db.get(Task, task_id)


def _busy_events(task_id):
    return [
        event
        for event in read_task_events(task_id)
        if event["data"].get("status") == routes.BUSY_STATUS
    ]


def _add_task(db, task_id, *, status="queued", parent_task_id=None, agent_id="agent-finance"):
    db.add(
        Task(
            id=task_id,
            conversation_id=7,
            agent_id=agent_id,
            status=status,
            query=QUESTION,
            parent_task_id=parent_task_id,
        )
    )
    db.add(TaskResult(id=f"result-{task_id}", task_id=task_id, history=[], future_actions=[]))
    db.commit()


def _dispatch(task_id, root_id=None):
    return routes._WorkDispatch(
        "agent-finance", {"task_id": task_id}, task_id, root_id or task_id, 7
    )


@pytest.fixture(autouse=True)
def empty_line():
    work_queue_line._waiting.clear()
    work_queue_line._depth.clear()
    yield
    work_queue_line._waiting.clear()
    work_queue_line._depth.clear()


@pytest.fixture
def finance_queue():
    with patch.object(routes, "_work_queue_key", return_value=QUEUE):
        yield


@pytest.fixture
def no_wait(monkeypatch):
    monkeypatch.setattr(routes, "BUSY_RETRY_INTERVAL_S", 0)


class TestFullQueueOnSubmit:
    async def test_a_full_queue_tells_the_user_busy_with_a_position_before_any_wait(
        self, submit_task, routing_db, as_user, monkeypatch, finance_queue
    ):
        seen_at_first_wait: dict = {}
        real_sleep = asyncio.sleep

        async def first_wait_records(seconds):
            if seconds == routes.BUSY_RETRY_INTERVAL_S and not seen_at_first_wait:
                (task_id,) = work_queue_line._waiting[QUEUE]
                seen_at_first_wait["busy"] = _busy_events(task_id)
                seen_at_first_wait["status"] = _stored(routing_db, task_id).status
            await real_sleep(0)

        monkeypatch.setattr(routes.asyncio, "sleep", first_wait_records)
        with (
            patch.object(routes, "select_agent_by_mode", return_value=(None, None, None, [])),
            patch.object(routes, "route_task", return_value=("agent-finance", QUESTION, None, [])),
            patch.object(
                routes,
                "_publish_task_to_work_queue",
                side_effect=[WorkQueueFull(QUEUE, 10), None],
            ) as publish,
            patch.object(routes, "add_messages", return_value={"id": 41}),
        ):
            submitted = await submit_task(
                {"demand": QUESTION, "conversation_id": 7, "skills_required": []},
                user=as_user,
            )

        task_id = submitted.response.json()["task_id"]
        (busy,) = seen_at_first_wait["busy"]
        assert busy["type"] == "progress"
        assert busy["stage"] == "queued"
        assert busy["data"]["position"] == 11
        assert busy["data"]["detail"] == "Busy, position 11"
        assert seen_at_first_wait["status"] == "queued"
        assert publish.call_count == 2
        assert _stored(routing_db, task_id).status == "running"
        assert work_queue_line.has_waiting(QUEUE) is False
        statuses = [event["data"].get("status") for event in read_task_events(task_id)]
        assert statuses.index("busy") < statuses.index("running")


class TestWaitingLine:
    async def test_a_request_behind_a_waiting_one_joins_the_line_without_publishing(
        self, routing_db, finance_queue
    ):
        _add_task(routing_db, "second")
        work_queue_line.join(QUEUE, "first", 10)

        with patch.object(routes, "_publish_task_to_work_queue") as publish:
            handed = await routes._publish_unless_full(routing_db, _dispatch("second"))

        assert handed is False
        publish.assert_not_called()
        assert work_queue_line.position(QUEUE, "second") == 12
        (busy,) = _busy_events("second")
        assert busy["data"]["position"] == 12

    async def test_requests_leave_the_line_in_the_order_they_joined(
        self, routing_db, finance_queue, no_wait
    ):
        for task_id in ("first", "second"):
            _add_task(routing_db, task_id)
            work_queue_line.join(QUEUE, task_id, 10)
        published: list[str] = []
        attempts = {"count": 0}

        def publish(_db, _agent_id, payload):
            attempts["count"] += 1
            if attempts["count"] == 1:
                raise WorkQueueFull(QUEUE, 10)
            published.append(payload["task_id"])

        with patch.object(routes, "_publish_task_to_work_queue", side_effect=publish):
            results = await asyncio.gather(
                routes._wait_for_room(routing_db, _dispatch("second")),
                routes._wait_for_room(routing_db, _dispatch("first")),
            )

        assert results == [True, True]
        assert published == ["first", "second"]
        assert work_queue_line.has_waiting(QUEUE) is False

    async def test_the_position_is_reported_again_only_when_it_changes(
        self, routing_db, finance_queue, no_wait
    ):
        _add_task(routing_db, "only")
        work_queue_line.join(QUEUE, "only", 10)
        depths = iter([10, 9, None])

        def publish(_db, _agent_id, _payload):
            depth = next(depths)
            if depth is not None:
                raise WorkQueueFull(QUEUE, depth)

        with patch.object(routes, "_publish_task_to_work_queue", side_effect=publish):
            assert await routes._wait_for_room(routing_db, _dispatch("only")) is True

        assert [event["data"]["position"] for event in _busy_events("only")] == [10]

    async def test_a_waiting_request_holds_no_database_connection_between_tries(
        self, routing_db, finance_queue, monkeypatch
    ):
        _add_task(routing_db, "only")
        work_queue_line.join(QUEUE, "only", 10)
        in_transaction_while_waiting: list[bool] = []
        real_sleep = asyncio.sleep

        async def record(_seconds):
            in_transaction_while_waiting.append(routing_db.in_transaction())
            await real_sleep(0)

        monkeypatch.setattr(routes.asyncio, "sleep", record)
        with patch.object(
            routes,
            "_publish_task_to_work_queue",
            side_effect=[WorkQueueFull(QUEUE, 10), WorkQueueFull(QUEUE, 10), None],
        ):
            assert await routes._wait_for_room(routing_db, _dispatch("only")) is True

        assert in_transaction_while_waiting == [False, False, False]

    async def test_a_request_cancelled_while_waiting_is_never_published(
        self, routing_db, finance_queue, no_wait
    ):
        _add_task(routing_db, "cancelled", status="canceled")
        work_queue_line.join(QUEUE, "cancelled", 10)

        with patch.object(routes, "_publish_task_to_work_queue") as publish:
            handed = await routes._wait_for_room(routing_db, _dispatch("cancelled"))

        assert handed is False
        publish.assert_not_called()
        assert work_queue_line.has_waiting(QUEUE) is False

    async def test_a_waiting_chain_step_of_a_cancelled_request_is_cancelled_too(
        self, routing_db, finance_queue, no_wait
    ):
        _add_task(routing_db, "root", status="canceled")
        _add_task(routing_db, "step-2", status="queued", parent_task_id="root")
        work_queue_line.join(QUEUE, "step-2", 10)

        with patch.object(routes, "_publish_task_to_work_queue") as publish:
            handed = await routes._wait_for_room(routing_db, _dispatch("step-2", root_id="root"))

        assert handed is False
        publish.assert_not_called()
        step = _stored(routing_db, "step-2")
        assert step.status == "canceled"
        assert step.completed_at is not None


class TestChainStepInLine:
    async def test_a_chain_step_waits_in_the_background_then_runs(
        self, routing_db, finance_queue, no_wait, monkeypatch
    ):
        monkeypatch.setattr(routes, "SessionLocal", lambda: routing_db)
        _add_task(routing_db, "root", status="running")
        _add_task(routing_db, "step-2", status="running", parent_task_id="root")
        dispatch = _dispatch("step-2", root_id="root")

        with patch.object(
            routes,
            "_publish_task_to_work_queue",
            side_effect=[WorkQueueFull(QUEUE, 10), WorkQueueFull(QUEUE, 10), None],
        ) as publish:
            handed_now = await routes._publish_unless_full(routing_db, dispatch)
            waiting_statuses = (
                _stored(routing_db, "root").status,
                _stored(routing_db, "step-2").status,
            )
            task_jobs.submit("step-2", routes._wait_for_room_job(dispatch))
            await task_jobs.drain()

        assert handed_now is False
        assert waiting_statuses == ("queued", "queued")
        assert publish.call_count == 3
        assert _stored(routing_db, "root").status == "running"
        assert _stored(routing_db, "step-2").status == "running"
        assert _busy_events("root")
        assert _busy_events("step-2") == []
        last = read_task_events("root")[-1]
        assert last["data"]["status"] == "running"
        assert last["data"]["detail"] == "Assigned to agent-finance"
        assert "position" not in last["data"]

    async def test_a_chain_step_that_cannot_be_handed_over_fails_the_request(
        self, routing_db, finance_queue, no_wait, monkeypatch
    ):
        monkeypatch.setattr(routes, "SessionLocal", lambda: routing_db)
        monkeypatch.setattr(routes, "add_messages", lambda *_args, **_kwargs: {"id": 3})
        routing_db.close = lambda: None
        _add_task(routing_db, "root", status="queued")
        _add_task(routing_db, "step-2", status="queued", parent_task_id="root")
        work_queue_line.join(QUEUE, "step-2", 10)

        with patch.object(
            routes, "_publish_task_to_work_queue", side_effect=RuntimeError("broker gone")
        ):
            handed = await routes._wait_for_room_job(_dispatch("step-2", root_id="root"))

        assert handed is False
        assert _stored(routing_db, "root").status == "failed"
        assert _stored(routing_db, "step-2").status == "failed"
        (error,) = read_task_events("root")
        assert error["type"] == "error"
        assert error["data"]["reason"] == "dispatch_failed"
        assert "broker gone" in error["data"]["content"]
