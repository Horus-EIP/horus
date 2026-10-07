from __future__ import annotations

import threading
from unittest.mock import patch

import pytest

from core.task_events import publish_task_event, read_task_events
from db.models import Conversations, Task, TaskResult
from tasks import routes
from tasks.idempotency import IDEMPOTENCY_TTL_SECONDS, idempotency_record_key
from tasks.task_jobs import task_jobs

QUESTION = "Summarise the Q4 2025 financial report"
OTHER_USER = {"id": 4, "user_id": "4", "username": "other", "role": "user"}


def _chat_task(**over):
    body = {"demand": QUESTION, "conversation_id": 7, "skills_required": []}
    body.update(over)
    return body


def _stored(db, task_id):
    db.expire_all()
    return db.get(Task, task_id)


def _event_kinds(task_id):
    return [(event["type"], event["data"].get("status")) for event in read_task_events(task_id)]


@pytest.fixture
def routed_to_finance():
    with (
        patch.object(routes, "select_agent_by_mode", return_value=(None, None, None, [])),
        patch.object(
            routes, "route_task", return_value=("agent-finance", QUESTION, None, [])
        ),
        patch.object(routes, "_publish_task_to_work_queue") as publish,
        patch.object(routes, "add_messages", return_value={"id": 41}),
    ):
        yield publish


class TestQueuedSubmission:
    async def test_new_task_answers_202_with_a_queued_task_before_routing_runs(
        self, routing_db, mas_client, monkeypatch, as_user
    ):
        monkeypatch.setattr(routes, "SessionLocal", lambda: routing_db)
        release_router = threading.Event()

        def slow_router(demand, _db, **_kwargs):
            release_router.wait(5)
            return ("agent-finance", demand, None, [])

        with (
            patch.object(routes, "select_agent_by_mode", return_value=(None, None, None, [])),
            patch.object(routes, "route_task", side_effect=slow_router),
            patch.object(routes, "_publish_task_to_work_queue") as publish,
            patch.object(routes, "add_messages", return_value={"id": 41}),
        ):
            async with mas_client(as_user) as client:
                response = await client.post("/tasks/new_task/", json=_chat_task())
                task_id = response.json()["task_id"]
                queued = _stored(routing_db, task_id)
                queued_status = queued.status
                queued_owner = queued.owner_username
                dispatched_while_routing = publish.called
                release_router.set()
                await task_jobs.drain()

        assert response.status_code == 202
        assert response.json() == {"task_id": task_id, "status": "queued", "conversation_id": 7}
        assert queued_status == "queued"
        assert queued_owner == "user"
        assert dispatched_while_routing is False
        routed = _stored(routing_db, task_id)
        assert routed.status == "running"
        assert routed.agent_id == "agent-finance"
        (_db, agent_id, payload), _kwargs = publish.call_args
        assert agent_id == "agent-finance"
        assert payload["task_id"] == task_id

    async def test_routing_runs_in_the_background_job_with_its_own_session(
        self, routing_db, mas_client, monkeypatch, as_user, routed_to_finance
    ):
        sessions_opened = []

        def open_session():
            sessions_opened.append(routing_db)
            return routing_db

        monkeypatch.setattr(routes, "SessionLocal", open_session)
        async with mas_client(as_user) as client:
            response = await client.post("/tasks/new_task/", json=_chat_task())
        await task_jobs.drain()

        assert response.status_code == 202
        assert len(sessions_opened) == 1
        routed_to_finance.assert_called_once()

    async def test_the_cheap_router_decides_in_the_background_job_with_the_task_id(
        self, submit_task, as_user
    ):
        with (
            patch.object(routes, "select_agent_by_mode", return_value=(None, None, None, [])),
            patch.object(
                routes, "route_task", return_value=("agent-finance", QUESTION, None, [])
            ) as route_task,
            patch.object(routes, "_publish_task_to_work_queue"),
            patch.object(routes, "add_messages", return_value={"id": 41}),
        ):
            submitted = await submit_task(_chat_task(), user=as_user)

        task_id = submitted.response.json()["task_id"]
        demand, _db = route_task.call_args.args
        assert demand == QUESTION
        assert route_task.call_args.kwargs == {"task_id": task_id}

    async def test_user_message_is_saved_when_the_task_is_queued(
        self, submit_task, as_user, routed_to_finance
    ):
        with patch.object(routes, "add_messages", return_value={"id": 41}) as add_messages:
            await submit_task(_chat_task(), user=as_user)

        assert add_messages.call_args_list[0].args[:3] == ("user", QUESTION, 7)

    async def test_queued_routing_and_dispatch_are_stored_as_events(
        self, submit_task, as_user, routed_to_finance
    ):
        submitted = await submit_task(_chat_task(), user=as_user)
        task_id = submitted.response.json()["task_id"]

        assert _event_kinds(task_id) == [
            ("progress", "queued"),
            ("progress", "routing"),
            ("progress", "running"),
        ]
        stages = [event["stage"] for event in read_task_events(task_id)]
        assert stages == ["queued", "routing", "retrieval"]

    async def test_direct_answer_completes_the_queued_task_with_a_result_event(
        self, submit_task, routing_db, as_user
    ):
        with (
            patch.object(routes, "select_agent_by_mode", return_value=(None, None, None, [])),
            patch.object(routes, "route_task", return_value=(None, None, "Hello!", [])),
            patch.object(routes, "_publish_task_to_work_queue") as publish,
            patch.object(routes, "add_messages", return_value={"id": 52}),
        ):
            submitted = await submit_task(_chat_task(demand="hello"), user=as_user)

        task_id = submitted.response.json()["task_id"]
        task = _stored(routing_db, task_id)
        assert task.status == "completed"
        assert task.result.result_data == "Hello!"
        publish.assert_not_called()
        result = read_task_events(task_id)[-1]
        assert result["type"] == "result"
        assert result["data"]["content"] == "Hello!"
        assert result["data"]["route"] == "direct_answer"
        assert result["data"]["message_id"] == 52

    async def test_unroutable_task_fails_with_the_reason_as_an_error_event(
        self, submit_task, routing_db, as_user
    ):
        with (
            patch.object(routes, "select_agent_by_mode", return_value=(None, None, None, [])),
            patch.object(routes, "route_task", return_value=(None, None, None, [])),
            patch.object(routes, "decompose_task", return_value=(None, [])),
            patch.object(routes, "add_messages", return_value={"id": 53}),
        ):
            submitted = await submit_task(_chat_task(), user=as_user)

        task_id = submitted.response.json()["task_id"]
        task = _stored(routing_db, task_id)
        assert task.status == "failed"
        assert task.result.result_data.startswith("No agents are currently registered")
        error = read_task_events(task_id)[-1]
        assert error["type"] == "error"
        assert error["data"]["status"] == "failed"
        assert error["data"]["content"].startswith("No agents are currently registered")

    async def test_routing_crash_fails_the_task_instead_of_leaving_it_queued(
        self, submit_task, routing_db, as_user
    ):
        with (
            patch.object(routes, "select_agent_by_mode", side_effect=RuntimeError("router down")),
            patch.object(routes, "add_messages", return_value={"id": 54}),
        ):
            submitted = await submit_task(_chat_task(), user=as_user)

        task_id = submitted.response.json()["task_id"]
        task = _stored(routing_db, task_id)
        assert task.status == "failed"
        assert "router down" in task.result.result_data
        assert read_task_events(task_id)[-1]["type"] == "error"

    async def test_task_cancelled_while_routing_is_never_dispatched(
        self, routing_db, mas_client, monkeypatch, as_user
    ):
        monkeypatch.setattr(routes, "SessionLocal", lambda: routing_db)
        release_router = threading.Event()

        def slow_router(demand, _db, **_kwargs):
            release_router.wait(5)
            return ("agent-finance", demand, None, [])

        with (
            patch.object(routes, "select_agent_by_mode", return_value=(None, None, None, [])),
            patch.object(routes, "route_task", side_effect=slow_router),
            patch.object(routes, "_publish_task_to_work_queue") as publish,
            patch.object(routes, "add_messages", return_value={"id": 41}),
            patch("tasks.task_crud.rabbitmq_instance"),
        ):
            async with mas_client(as_user) as client:
                response = await client.post("/tasks/new_task/", json=_chat_task())
                task_id = response.json()["task_id"]
                cancelled = await client.patch(f"/tasks/{task_id}/cancel")
                release_router.set()
                await task_jobs.drain()

        assert cancelled.status_code == 200
        publish.assert_not_called()
        assert _stored(routing_db, task_id).status == "canceled"
        assert ("error", "cancelled") in _event_kinds(task_id)

    async def test_invalid_inline_file_is_rejected_before_a_task_is_stored(
        self, submit_task, routing_db, as_user
    ):
        submitted = await submit_task(
            _chat_task(inline_files=[{"filename": "bad.bin", "content_b64": "!!!"}]),
            user=as_user,
        )

        assert submitted.response.status_code == 400
        assert routing_db.query(Task).count() == 0


class TestIdempotencyKey:
    async def test_same_key_returns_the_same_task_and_never_creates_a_second_one(
        self, submit_task, routing_db, as_user, routed_to_finance
    ):
        headers = {"Idempotency-Key": "submit-1"}

        first = await submit_task(_chat_task(), user=as_user, headers=headers)
        retry = await submit_task(_chat_task(), user=as_user, headers=headers)

        assert first.response.status_code == retry.response.status_code == 202
        assert retry.response.json()["task_id"] == first.response.json()["task_id"]
        assert retry.response.json()["status"] == "running"
        assert retry.response.headers["Idempotent-Replayed"] == "true"
        assert retry.outcome is None
        assert routing_db.query(Task).count() == 1
        assert routing_db.query(TaskResult).count() == 1
        routed_to_finance.assert_called_once()

    async def test_keys_are_scoped_per_user(
        self, submit_task, routing_db, as_user, as_manager, routed_to_finance
    ):
        headers = {"Idempotency-Key": "submit-1"}
        routing_db.add(Conversations(id=9, owner_username="manager", name="Team review"))
        routing_db.commit()

        mine = await submit_task(_chat_task(), user=as_user, headers=headers)
        theirs = await submit_task(
            _chat_task(conversation_id=9), user=as_manager, headers=headers
        )

        assert mine.response.json()["task_id"] != theirs.response.json()["task_id"]
        assert routing_db.query(Task).count() == 2

    async def test_different_keys_create_different_tasks(
        self, submit_task, routing_db, as_user, routed_to_finance
    ):
        await submit_task(_chat_task(), user=as_user, headers={"Idempotency-Key": "a"})
        await submit_task(_chat_task(), user=as_user, headers={"Idempotency-Key": "b"})

        assert routing_db.query(Task).count() == 2

    async def test_key_is_kept_for_24_hours(
        self, submit_task, task_event_store, as_user, routed_to_finance
    ):
        first = await submit_task(
            _chat_task(), user=as_user, headers={"Idempotency-Key": "submit-1"}
        )

        record = idempotency_record_key(as_user["id"], "submit-1")
        assert task_event_store.get(record) == first.response.json()["task_id"]
        assert IDEMPOTENCY_TTL_SECONDS - 5 < task_event_store.ttl(record) <= IDEMPOTENCY_TTL_SECONDS
        assert IDEMPOTENCY_TTL_SECONDS == 24 * 60 * 60

    async def test_a_failed_insert_releases_the_key_for_the_retry(
        self, submit_task, routing_db, as_user, routed_to_finance
    ):
        headers = {"Idempotency-Key": "submit-1"}
        with patch.object(routes, "insert_queued_task", side_effect=RuntimeError("db down")):
            failed = await submit_task(_chat_task(), user=as_user, headers=headers)

        retry = await submit_task(_chat_task(), user=as_user, headers=headers)

        assert failed.response.status_code == 500
        assert retry.response.status_code == 202
        assert retry.response.headers.get("Idempotent-Replayed") is None
        assert routing_db.query(Task).count() == 1

    async def test_an_oversized_key_is_rejected(self, submit_task, as_user):
        submitted = await submit_task(
            _chat_task(), user=as_user, headers={"Idempotency-Key": "k" * 201}
        )

        assert submitted.response.status_code == 422


def _owned_task(db, task_id, *, owner="user", conversation_id=7):
    db.add(
        Task(
            id=task_id,
            agent_id="agent-finance",
            status="running",
            query=QUESTION,
            conversation_id=conversation_id,
            owner_username=owner,
        )
    )
    db.commit()


async def _publish_steps(task_id, count):
    for index in range(count):
        await publish_task_event(
            task_id,
            "progress",
            conversation_id=None,
            data={"type": "task_step", "step_type": "retrieval.start", "title": f"step {index}"},
            stage="retrieval",
        )


class TestTaskEventsEndpoint:
    async def test_events_since_returns_only_the_missed_events_in_order(
        self, routing_db, mas_client, as_user
    ):
        _owned_task(routing_db, "t-1")
        await _publish_steps("t-1", 4)

        async with mas_client(as_user) as client:
            response = await client.get("/tasks/t-1/events", params={"since": 2})

        body = response.json()
        assert response.status_code == 200
        assert [event["seq"] for event in body["events"]] == [3, 4]
        assert body["last_seq"] == 4
        assert body["has_more"] is False
        assert body["status"] == "running"
        assert body["events"][0]["data"]["title"] == "step 2"

    async def test_events_are_paged_with_limit(self, routing_db, mas_client, as_user):
        _owned_task(routing_db, "t-1")
        await _publish_steps("t-1", 3)

        async with mas_client(as_user) as client:
            first = (await client.get("/tasks/t-1/events", params={"limit": 2})).json()
            rest = (
                await client.get("/tasks/t-1/events", params={"since": first["last_seq"]})
            ).json()

        assert [event["seq"] for event in first["events"]] == [1, 2]
        assert first["has_more"] is True
        assert [event["seq"] for event in rest["events"]] == [3]

    async def test_another_users_task_events_are_forbidden(
        self, routing_db, mas_client, as_manager
    ):
        _owned_task(routing_db, "t-1", owner="user")

        async with mas_client(OTHER_USER) as client:
            response = await client.get("/tasks/t-1/events")
        async with mas_client(as_manager) as client:
            managed = await client.get("/tasks/t-1/events")

        assert response.status_code == 403
        assert managed.status_code == 200

    async def test_an_admin_reads_any_task_events(self, routing_db, mas_client, as_admin):
        _owned_task(routing_db, "t-1", owner="user")
        await _publish_steps("t-1", 1)

        async with mas_client(as_admin) as client:
            response = await client.get("/tasks/t-1/events")

        assert response.status_code == 200
        assert len(response.json()["events"]) == 1

    async def test_a_task_without_an_owner_belongs_to_its_conversation_owner(
        self, routing_db, mas_client, as_user
    ):
        _owned_task(routing_db, "legacy", owner=None, conversation_id=7)

        async with mas_client(as_user) as client:
            mine = await client.get("/tasks/legacy/events")
        async with mas_client(OTHER_USER) as client:
            theirs = await client.get("/tasks/legacy/events")

        assert mine.status_code == 200
        assert theirs.status_code == 403

    async def test_a_standalone_task_without_an_owner_is_admin_only(
        self, routing_db, mas_client, as_user
    ):
        _owned_task(routing_db, "orphan", owner=None, conversation_id=None)

        async with mas_client(as_user) as client:
            response = await client.get("/tasks/orphan/events")

        assert response.status_code == 403

    async def test_unknown_task_events_return_404(self, mas_client, as_admin):
        async with mas_client(as_admin) as client:
            response = await client.get("/tasks/ghost/events")

        assert response.status_code == 404

    async def test_unavailable_event_store_returns_503(
        self, routing_db, mas_client, as_user, monkeypatch
    ):
        _owned_task(routing_db, "t-1")

        def store_down(*_args):
            raise ConnectionError("redis down")

        monkeypatch.setattr(routes, "read_task_events", store_down)
        async with mas_client(as_user) as client:
            response = await client.get("/tasks/t-1/events")

        assert response.status_code == 503
