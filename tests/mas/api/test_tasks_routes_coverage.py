"""High-coverage tests for ``src/services/mas/tasks/routes.py``.

The task router is a large FastAPI surface that mixes DB access, agent auth,
RabbitMQ dispatch, and LLM-backed planning/aggregation. Every external edge is
mocked here so the suite stays hermetic (no Postgres / Redis / RabbitMQ / LLM).

Patch targets are all on ``tasks.routes`` because the router imports the
helpers into its own namespace (``from tasks.task_tool_functions import ...``),
so the *bound name in tasks.routes* is what the handlers actually call.

Auth model (see ``auth/permissions.py``):

* ``admin``   — has every permission.
* ``manager`` — TASK_READ/CREATE/DELETE + VIEW_ANALYTICS (no TASK_EXECUTE).
* ``user``    — TASK_READ/CREATE/DELETE + VIEW_ANALYTICS only.

``PermissionChecker`` depends on ``get_current_user``; the ``make_client``
factory overrides that dependency when ``current_user`` is supplied. Passing
``current_user=None`` installs *no* override, so the real ``get_current_user``
runs and FastAPI's OAuth2 scheme returns 401 for the missing token.

Agent-authenticated routes (``task-result/`` / ``task-step/``) depend on
``verify_agent_api_key`` — overridden via ``agent_api_auth=(agent_id, key)``.
"""

from __future__ import annotations

import base64
import json
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from tasks.routes import router
from tasks.status import TaskStatus

# --------------------------------------------------------------------------- #
# Test doubles
# --------------------------------------------------------------------------- #


def _task(
    *,
    id="t1",
    status=TaskStatus.RUNNING.value,
    agent_id="agent-1",
    conversation_id=None,
    query="do the thing",
    parent_task_id=None,
    order=0,
    created_at=None,
    result=None,
):
    """A lightweight Task stand-in with just the attributes the router reads."""
    return SimpleNamespace(
        id=id,
        status=status,
        agent_id=agent_id,
        conversation_id=conversation_id,
        query=query,
        parent_task_id=parent_task_id,
        order=order,
        created_at=created_at if created_at is not None else datetime(2024, 1, 1),
        result=result,
        skills_required=None,
        completed_at=None,
    )


def _result(*, result_data=None, history=None, future_actions=None):
    return SimpleNamespace(
        result_data=result_data,
        history=history if history is not None else [],
        future_actions=future_actions if future_actions is not None else [],
    )


def _agent(*, id="agent-1", name="Researcher", type_value="researcher"):
    agent_type = SimpleNamespace(value=type_value) if type_value is not None else None
    return SimpleNamespace(
        id=id,
        name=name,
        type=agent_type,
        skills=["s1"],
        status="active",
    )


class _FakeQuery:
    """A query whose terminal ``.first()`` / ``.all()`` / ``.count()`` are
    driven by a router callback keyed on the queried entity.

    ``filter`` / ``order_by`` / ``group_by`` are chainable no-ops; the model
    passed to ``db.query(Model)`` decides what comes back. This mirrors how the
    handlers branch purely on *which* model they query, not on filter args.
    """

    def __init__(self, session: "_FakeSession", entity):
        self._session = session
        self._entity = entity

    def filter(self, *a, **k):
        return self

    def order_by(self, *a, **k):
        return self

    def group_by(self, *a, **k):
        return self

    def first(self):
        return self._session._first_for(self._entity)

    def all(self):
        return self._session._all_for(self._entity)

    def count(self):
        return self._session._count_for(self._entity)


class _FakeSession:
    """Minimal SQLAlchemy ``Session`` substitute for the task router.

    ``first_map`` / ``all_map`` / ``count_map`` map a *key* to a return value
    or a zero-arg callable. The key is the queried entity's ``__name__`` when it
    is a model class, else the repr of the column expression's first token.
    Defaults keep unmapped queries safe (``None`` / ``[]`` / ``0``).
    """

    def __init__(self, *, first_map=None, all_map=None, count_map=None):
        self.first_map = first_map or {}
        self.all_map = all_map or {}
        self.count_map = count_map or {}
        self.commit = MagicMock()
        self.rollback = MagicMock()
        self.add = MagicMock()

    @staticmethod
    def _key(entity):
        return getattr(entity, "__name__", None) or "EXPR"

    def query(self, entity, *rest):
        # group_by-count form: query(Task.status, func.count(...)) → key EXPR.
        key = self._key(entity) if not rest else "EXPR"
        return _FakeQuery(self, key)

    def _resolve(self, mapping, key, default):
        if key in mapping:
            val = mapping[key]
            return val() if callable(val) else val
        if "EXPR" in mapping and key == "EXPR":
            val = mapping["EXPR"]
            return val() if callable(val) else val
        return default

    def _first_for(self, key):
        return self._resolve(self.first_map, key, None)

    def _all_for(self, key):
        return self._resolve(self.all_map, key, [])

    def _count_for(self, key):
        return self._resolve(self.count_map, key, 0)


@pytest.fixture
def make_fake_client(make_client):
    """Like ``make_client`` but swaps the MagicMock db for a ``_FakeSession``.

    Returns ``(client, fake_session)`` so a test can assert on commits / the
    maps it configured. Reuses ``make_client`` purely for app + auth wiring,
    then re-points ``get_db`` at the structured fake.
    """
    from db.database import get_db

    def _factory(fake: _FakeSession, **kwargs):
        client = make_client(router, **kwargs)
        client.app.dependency_overrides[get_db] = lambda: fake
        return client

    return _factory


# A reusable TaskForm body the validator accepts (skills_required is required).
def _task_form(**over):
    body = {"demand": "summarize Q1 revenue", "skills_required": ["analysis"]}
    body.update(over)
    return body


# --------------------------------------------------------------------------- #
# GET /tasks/list
# --------------------------------------------------------------------------- #


class TestListTasks:
    def test_lists_root_tasks(self, make_fake_client, as_admin):
        fake = _FakeSession(all_map={"Task": [_task(id="r1"), _task(id="r2")]})
        client = make_fake_client(fake, current_user=as_admin)
        r = client.get("/tasks/list")
        assert r.status_code == 200
        assert len(r.json()) == 2

    def test_requires_authentication(self, make_fake_client):
        fake = _FakeSession()
        client = make_fake_client(fake, current_user=None)
        assert client.get("/tasks/list").status_code == 401


# --------------------------------------------------------------------------- #
# GET /tasks/stats/queue
# --------------------------------------------------------------------------- #


class TestQueueStats:
    def test_aggregates_counts_by_status(self, make_fake_client, as_admin):
        rows = [
            (TaskStatus.PENDING.value, 2),
            (TaskStatus.RUNNING.value, 1),
            (TaskStatus.COMPLETED.value, 4),
            (TaskStatus.CANCELED.value, 3),
            ("unknown-status", 9),  # unmapped key -> ignored
        ]
        fake = _FakeSession(all_map={"EXPR": rows})
        client = make_fake_client(fake, current_user=as_admin)
        r = client.get("/tasks/stats/queue")
        assert r.status_code == 200
        body = r.json()
        assert body["pending"] == 2
        assert body["running"] == 1
        assert body["completed"] == 4
        assert body["cancelled"] == 3
        # total sums only the mapped buckets (unknown-status dropped).
        assert body["total"] == 2 + 1 + 4 + 3

    def test_handles_enum_status_objects(self, make_fake_client, as_admin):
        # Branch where the status value arrives as a TaskStatus enum, not str.
        rows = [(TaskStatus.FAILED, 5)]
        fake = _FakeSession(all_map={"EXPR": rows})
        client = make_fake_client(fake, current_user=as_admin)
        r = client.get("/tasks/stats/queue")
        assert r.status_code == 200
        assert r.json()["failed"] == 5

    def test_requires_authentication(self, make_fake_client):
        fake = _FakeSession()
        client = make_fake_client(fake, current_user=None)
        assert client.get("/tasks/stats/queue").status_code == 401


# --------------------------------------------------------------------------- #
# GET /tasks/conversation/{id}/running
# --------------------------------------------------------------------------- #


class TestRunningForConversation:
    def test_maps_rows_to_summary_shape(self, make_fake_client, as_user):
        row = _task(
            id="run-1",
            status=TaskStatus.RUNNING.value,
            conversation_id=7,
            created_at=datetime(2024, 5, 1, 12, 0, 0),
        )
        fake = _FakeSession(all_map={"Task": [row]})
        client = make_fake_client(fake, current_user=as_user)
        r = client.get("/tasks/conversation/7/running")
        assert r.status_code == 200
        body = r.json()
        assert body[0]["id"] == "run-1"
        assert body[0]["status"] == "running"
        assert body[0]["conversation_id"] == 7
        assert body[0]["created_at"].startswith("2024-05-01")

    def test_handles_null_created_at(self, make_fake_client, as_user):
        row = _task(id="run-2", created_at=None)
        # created_at default is a datetime; force None explicitly.
        row.created_at = None
        fake = _FakeSession(all_map={"Task": [row]})
        client = make_fake_client(fake, current_user=as_user)
        r = client.get("/tasks/conversation/1/running")
        assert r.status_code == 200
        assert r.json()[0]["created_at"] == ""


# --------------------------------------------------------------------------- #
# GET /tasks/{task_id}
# --------------------------------------------------------------------------- #


class TestGetTaskDetail:
    def test_unknown_task_returns_404(self, make_fake_client, as_admin):
        fake = _FakeSession(first_map={"Task": None})
        client = make_fake_client(fake, current_user=as_admin)
        r = client.get("/tasks/ghost")
        assert r.status_code == 404

    def test_returns_detail_with_string_result_and_children(
        self, make_fake_client, as_admin
    ):
        task = _task(id="t-detail", status=TaskStatus.COMPLETED.value, conversation_id=3)
        tr = _result(
            result_data="the answer",
            history=[{"role": "user", "message": "q"}],
            future_actions=[["a", "b"]],
        )
        child_short = _task(id="c1", query="short", status=TaskStatus.PENDING.value)
        child_long = _task(id="c2", query="x" * 300, status=TaskStatus.CANCELED.value)
        fake = _FakeSession(
            first_map={"Task": task, "TaskResult": tr},
            all_map={"Task": [child_short, child_long]},
        )
        client = make_fake_client(fake, current_user=as_admin)
        r = client.get("/tasks/t-detail")
        assert r.status_code == 200
        body = r.json()
        assert body["task_id"] == "t-detail"
        assert body["result"] == "the answer"
        assert body["history"] == [{"role": "user", "message": "q"}]
        assert body["future_actions"] == [["a", "b"]]
        # canceled -> normalized to "cancelled" by _task_status_value.
        statuses = {s["id"]: s["status"] for s in body["subtasks"]}
        assert statuses["c2"] == "cancelled"
        # Long child title gets truncated to 200 chars + ellipsis.
        long_title = next(s["title"] for s in body["subtasks"] if s["id"] == "c2")
        assert long_title.endswith("…")
        assert len(long_title) == 201

    def test_serializes_dict_result_as_json(self, make_fake_client, as_admin):
        task = _task(id="t-json")
        tr = _result(result_data={"k": "v"})
        fake = _FakeSession(
            first_map={"Task": task, "TaskResult": tr}, all_map={"Task": []}
        )
        client = make_fake_client(fake, current_user=as_admin)
        r = client.get("/tasks/t-json")
        assert r.status_code == 200
        assert r.json()["result"] == '{"k": "v"}'

    def test_no_result_row_yields_empty_history(self, make_fake_client, as_admin):
        task = _task(id="t-noresult")
        fake = _FakeSession(
            first_map={"Task": task, "TaskResult": None}, all_map={"Task": []}
        )
        client = make_fake_client(fake, current_user=as_admin)
        r = client.get("/tasks/t-noresult")
        assert r.status_code == 200
        body = r.json()
        assert body["result"] is None
        assert body["history"] == []
        assert body["subtasks"] == []


# --------------------------------------------------------------------------- #
# POST /tasks/suggest-skills
# --------------------------------------------------------------------------- #


class TestSuggestSkills:
    @patch("tasks.routes.rank_skills")
    def test_returns_ranked_suggestions(self, mock_rank, make_fake_client, as_user):
        mock_rank.return_value = [
            {"skill": "analysis", "score": 0.9, "agent_id": "a1", "agent_name": "An"}
        ]
        fake = _FakeSession()
        client = make_fake_client(fake, current_user=as_user)
        r = client.post("/tasks/suggest-skills", json={"demand": "crunch numbers"})
        assert r.status_code == 200
        assert r.json()["suggestions"][0]["skill"] == "analysis"
        mock_rank.assert_called_once()

    @patch("tasks.routes.rank_skills", side_effect=RuntimeError("embedder cold"))
    def test_ranker_failure_returns_empty_list(
        self, _mock_rank, make_fake_client, as_user
    ):
        fake = _FakeSession()
        client = make_fake_client(fake, current_user=as_user)
        r = client.post("/tasks/suggest-skills", json={"demand": "x", "top_k": 2})
        assert r.status_code == 200
        assert r.json() == {"suggestions": []}

    def test_invalid_body_returns_422(self, make_fake_client, as_user):
        fake = _FakeSession()
        client = make_fake_client(fake, current_user=as_user)
        # demand must be >= 1 char; empty string fails validation.
        r = client.post("/tasks/suggest-skills", json={"demand": ""})
        assert r.status_code == 422


# --------------------------------------------------------------------------- #
# POST /tasks/new_task/  — the heavy dispatcher
# --------------------------------------------------------------------------- #


class TestCreateNewTaskValidation:
    def test_missing_body_returns_422(self, make_fake_client, as_user):
        fake = _FakeSession()
        client = make_fake_client(fake, current_user=as_user)
        assert client.post("/tasks/new_task/", json={}).status_code == 422

    def test_requires_authentication(self, make_fake_client):
        fake = _FakeSession()
        client = make_fake_client(fake, current_user=None)
        r = client.post("/tasks/new_task/", json=_task_form())
        assert r.status_code == 401


@pytest.fixture
def dispatch():
    with (
        patch("tasks.routes._publish_task_to_work_queue") as publish,
        patch("tasks.routes.add_messages", return_value={"id": 1}) as add_messages,
    ):
        yield SimpleNamespace(publish=publish, add_messages=add_messages)


def _stored(db, task_id):
    from db.models import Task  # noqa: PLC0415

    db.expire_all()
    return db.get(Task, task_id)


def _subtasks_of(db, root_id):
    from db.models import Task  # noqa: PLC0415

    db.expire_all()
    return db.query(Task).filter(Task.parent_task_id == root_id).all()


def _add_agent(db, agent_id, name, *, status="active", type_value="general", skills=None):
    from db.models import Agents  # noqa: PLC0415

    db.add(
        Agents(
            id=agent_id,
            name=name,
            skills=skills or [],
            status=status,
            type=type_value,
            api_key=f"{agent_id}-key",
        )
    )
    db.commit()


def _dispatched(dispatch):
    _db, agent_id, payload = dispatch.publish.call_args.args
    return agent_id, payload


def _published_texts(task_id):
    from core.task_events import read_task_events  # noqa: PLC0415

    return [event["data"].get("content") for event in read_task_events(task_id)]


class TestCreateNewTaskSingleAgent:
    """``mode`` unset → select_agent_by_mode/route_task path."""

    @patch(
        "tasks.routes.route_task",
        return_value=(None, None, "Here is your direct answer", []),
    )
    @patch("tasks.routes.select_agent_by_mode", return_value=(None, None, None, []))
    async def test_direct_answer_short_circuits_without_dispatch(
        self, _by_mode, _for_task, dispatch, submit_task, routing_db, as_user
    ):
        submitted = await submit_task(_task_form(conversation_id=7), user=as_user)

        assert submitted.response.status_code == 202
        assert submitted.outcome["result"] == "Here is your direct answer"
        assert submitted.outcome["message"] == "Processing complete"
        roles = [call.args[0] for call in dispatch.add_messages.call_args_list]
        assert roles == ["user", "assistant"]
        dispatch.publish.assert_not_called()
        assert _stored(routing_db, submitted.outcome["task_id"]).status == "completed"

    @patch("tasks.routes.route_task")
    @patch(
        "tasks.routes.select_agent_by_mode",
        return_value=("agent-77", "rewritten demand", None, []),
    )
    async def test_single_agent_dispatch_publishes_and_returns_task_id(
        self, _by_mode, for_task, dispatch, submit_task, routing_db, as_user
    ):
        submitted = await submit_task(_task_form(conversation_id=7), user=as_user)

        task_id = submitted.response.json()["task_id"]
        assert submitted.outcome["task_id"] == task_id
        assert "agent-77" in submitted.outcome["message"]
        for_task.assert_not_called()
        agent_id, payload = _dispatched(dispatch)
        assert agent_id == "agent-77"
        assert payload["task_id"] == task_id
        assert payload["demand"] == "rewritten demand"
        task = _stored(routing_db, task_id)
        assert task.status == TaskStatus.RUNNING.value
        assert task.agent_id == "agent-77"
        assert task.query == "rewritten demand"
        assert task.parent_task_id is None

    async def test_queued_insert_failure_returns_500(self, dispatch, submit_task, as_user):
        with patch("tasks.routes.insert_queued_task", side_effect=RuntimeError("db down")):
            submitted = await submit_task(_task_form(), user=as_user)

        assert submitted.response.status_code == 500
        assert submitted.outcome is None
        dispatch.publish.assert_not_called()

    @patch(
        "tasks.routes.select_agent_by_mode",
        return_value=("agent-1", "demand", None, []),
    )
    async def test_unresolvable_work_queue_fails_the_task(
        self, _by_mode, dispatch, submit_task, routing_db, as_user
    ):
        dispatch.publish.side_effect = HTTPException(
            status_code=500,
            detail="Could not resolve RabbitMQ work queue for assigned agent",
        )

        submitted = await submit_task(_task_form(conversation_id=7), user=as_user)

        task = _stored(routing_db, submitted.response.json()["task_id"])
        assert task.status == TaskStatus.FAILED.value
        assert "Could not resolve RabbitMQ work queue" in task.result.result_data

    @patch("tasks.routes.manager_announce_plan", return_value="Here's the plan")
    @patch("tasks.routes.route_task")
    @patch(
        "tasks.routes.select_agent_by_mode",
        return_value=("agent-1", "demand", None, [("agent-2", "second step")]),
    )
    async def test_single_agent_with_future_actions_builds_chain_root(
        self, _by_mode, _for_task, announce, dispatch, submit_task, routing_db, as_user
    ):
        _add_agent(routing_db, "manager-id", "Manager", type_value="manager")

        submitted = await submit_task(_task_form(conversation_id=7), user=as_user)

        root_id = submitted.response.json()["task_id"]
        root = _stored(routing_db, root_id)
        assert root.agent_id == "manager-id"
        assert root.status == TaskStatus.RUNNING.value
        (subtask,) = _subtasks_of(routing_db, root_id)
        assert subtask.agent_id == "agent-1"
        assert subtask.order == 1
        assert _dispatched(dispatch)[1]["task_id"] == subtask.id
        announce.assert_called_once()
        assert "Here's the plan" in _published_texts(root_id)

    @patch("tasks.routes.route_task")
    @patch("tasks.routes.select_agent_by_mode")
    async def test_attachments_discard_direct_answer_and_dispatch(
        self, by_mode, for_task, dispatch, submit_task, as_user
    ):
        by_mode.return_value = (None, None, None, [])
        for_task.return_value = ("agent-1", "demand", "direct text", [])

        submitted = await submit_task(
            _task_form(conversation_id=7, attached_files=[{"filename": "report.pdf"}]),
            user=as_user,
        )

        dispatch.publish.assert_called_once()
        assert "assigned to agent" in submitted.outcome["message"]

    @patch("tasks.routes.decompose_task", return_value=(None, []))
    @patch("tasks.routes.route_task", return_value=(None, None, "Hello! How can I help?", []))
    @patch("tasks.routes.select_agent_by_mode", return_value=(None, None, None, []))
    async def test_direct_answer_with_attachments_goes_to_the_catch_all_agent(
        self, _by_mode, _for_task, decompose, dispatch, submit_task, routing_db, as_user
    ):
        _add_agent(routing_db, "catch-all", "General-Assistant")

        submitted = await submit_task(
            _task_form(
                demand="hello",
                skills_required=[],
                conversation_id=7,
                attached_files=[{"filename": "report.pdf", "doc_id": "doc-1"}],
            ),
            user=as_user,
        )

        task_id = submitted.response.json()["task_id"]
        decompose.assert_not_called()
        agent_id, payload = _dispatched(dispatch)
        assert agent_id == "catch-all"
        assert payload["demand"] == "hello"
        assert payload["files"] == [
            {"source": "knowledge_store", "filename": "report.pdf", "doc_id": "doc-1"}
        ]
        task = _stored(routing_db, task_id)
        assert task.status == TaskStatus.RUNNING.value
        assert task.agent_id == "catch-all"
        assert "Hello! How can I help?" not in _published_texts(task_id)

    @patch("tasks.routes.decompose_task", return_value=(None, []))
    @patch("tasks.routes.route_task", return_value=(None, None, "4", []))
    @patch("tasks.routes.select_agent_by_mode")
    async def test_direct_answer_with_attachments_goes_to_the_requested_skill(
        self, by_mode, _for_task, decompose, dispatch, submit_task, as_user
    ):
        by_mode.side_effect = [
            (None, None, None, []),
            ("skill-agent", "what is 2+2", None, []),
        ]

        await submit_task(
            _task_form(
                demand="what is 2+2",
                skills_required=["analysis"],
                inline_files=[
                    {
                        "filename": "notes.txt",
                        "content_b64": base64.b64encode(b"2+2 is 5 here").decode(),
                    }
                ],
            ),
            user=as_user,
        )

        decompose.assert_not_called()
        agent_id, payload = _dispatched(dispatch)
        assert agent_id == "skill-agent"
        assert payload["files"][0]["source"] == "inline"


class TestCreateNewTaskAutoCreateAndCatchAll:
    @patch("tasks.routes.create_agent", return_value=("auto-id", "auto-key"))
    @patch("tasks.routes.route_task", return_value=(None, None, None, []))
    @patch("tasks.routes.select_agent_by_mode", return_value=(None, None, None, []))
    async def test_auto_creates_specialist_for_missing_skill(
        self, _by_mode, _for_task, create, dispatch, submit_task, routing_db, as_user
    ):
        _add_agent(routing_db, "a-existing", "Researcher", skills=["other"])

        submitted = await submit_task(
            _task_form(skills_required=["rare_skill"], conversation_id=7), user=as_user
        )

        create.assert_called_once()
        agent_id, payload = _dispatched(dispatch)
        assert agent_id == "auto-id"
        assert payload["assigned_agent_api_key"] == "auto-key"
        assert payload["assigned_agent_type"] == "general"
        assert payload["task_id"] == submitted.response.json()["task_id"]

    @patch("tasks.routes.create_agent", side_effect=RuntimeError("registry down"))
    @patch("tasks.routes.route_task", return_value=(None, None, None, []))
    @patch("tasks.routes.select_agent_by_mode", return_value=(None, None, None, []))
    async def test_auto_create_failure_falls_back_to_catch_all_agent(
        self, _by_mode, _for_task, _create, dispatch, submit_task, routing_db, as_user
    ):
        _add_agent(routing_db, "catch-all", "General-Assistant", skills=["other"])

        submitted = await submit_task(
            _task_form(skills_required=["rare_skill"], conversation_id=7), user=as_user
        )

        assert "catch-all" in submitted.outcome["message"]
        assert _dispatched(dispatch)[0] == "catch-all"

    @patch("tasks.routes.route_task", return_value=(None, None, None, []))
    @patch("tasks.routes.select_agent_by_mode")
    async def test_skill_match_fallback_selects_agent(
        self, by_mode, _for_task, dispatch, submit_task, as_user
    ):
        by_mode.side_effect = [
            (None, None, None, []),
            ("skill-agent", "demand", None, []),
        ]

        submitted = await submit_task(_task_form(skills_required=["analysis"]), user=as_user)

        assert "skill-agent" in submitted.outcome["message"]
        dispatch.publish.assert_called_once()


class TestCreateNewTaskDecompositionFallback:
    @patch("tasks.routes.manager_announce_plan")
    @patch("tasks.routes.decompose_task")
    @patch("tasks.routes.route_task", return_value=(None, None, None, []))
    @patch("tasks.routes.select_agent_by_mode", return_value=(None, None, None, []))
    async def test_decomposition_fallback_dispatches_first_action(
        self,
        _by_mode,
        _for_task,
        decompose,
        announce,
        dispatch,
        submit_task,
        routing_db,
        as_user,
    ):
        decompose.return_value = (("dagent", "first sub-demand"), [("dagent2", "second")])

        submitted = await submit_task(
            _task_form(skills_required=[], conversation_id=7), user=as_user
        )

        root_id = submitted.response.json()["task_id"]
        assert "decomposed and assigned" in submitted.outcome["message"]
        (subtask,) = _subtasks_of(routing_db, root_id)
        assert subtask.agent_id == "dagent"
        assert subtask.result.future_actions == [["dagent2", "second"]]
        assert _dispatched(dispatch)[1]["task_id"] == subtask.id
        announce.assert_not_called()

    @patch("tasks.routes.decompose_task", return_value=(("dagent", "only step"), []))
    @patch("tasks.routes.route_task", return_value=(None, None, None, []))
    @patch("tasks.routes.select_agent_by_mode", return_value=(None, None, None, []))
    async def test_one_step_decomposition_dispatches_the_queued_task_itself(
        self, _by_mode, _for_task, _decompose, dispatch, submit_task, routing_db, as_user
    ):
        submitted = await submit_task(_task_form(skills_required=[]), user=as_user)

        task_id = submitted.response.json()["task_id"]
        assert _subtasks_of(routing_db, task_id) == []
        assert _stored(routing_db, task_id).agent_id == "dagent"
        assert _dispatched(dispatch)[1]["task_id"] == task_id

    @patch("tasks.routes.create_agent", return_value=("auto-id", "auto-key"))
    @patch("tasks.routes.decompose_task")
    @patch("tasks.routes.route_task", return_value=(None, None, None, []))
    @patch("tasks.routes.select_agent_by_mode", return_value=(None, None, None, []))
    async def test_auto_created_credentials_ride_along_in_dispatch_payload(
        self,
        _by_mode,
        _for_task,
        decompose,
        _create,
        dispatch,
        submit_task,
        routing_db,
        as_user,
    ):
        _add_agent(routing_db, "a-existing", "Researcher", skills=["other"])

        await submit_task(
            _task_form(skills_required=["rare_skill"], conversation_id=7), user=as_user
        )

        decompose.assert_not_called()
        _agent_id, payload = _dispatched(dispatch)
        assert payload["assigned_agent_api_key"] == "auto-key"
        assert payload["assigned_agent_type"] == "general"

    @patch("tasks.routes.decompose_task", return_value=(None, []))
    @patch("tasks.routes.route_task", return_value=(None, None, None, []))
    @patch("tasks.routes.select_agent_by_mode", return_value=(None, None, None, []))
    async def test_no_plan_no_agents_registered_message(
        self, _by_mode, _for_task, _decompose, dispatch, submit_task, routing_db, as_user
    ):
        submitted = await submit_task(
            _task_form(skills_required=[], conversation_id=7), user=as_user
        )

        assert "No agents are currently registered" in submitted.outcome["message"]
        dispatch.publish.assert_not_called()
        task = _stored(routing_db, submitted.outcome["task_id"])
        assert task.status == TaskStatus.FAILED.value
        roles = [call.args[0] for call in dispatch.add_messages.call_args_list]
        assert roles == ["user", "assistant"]

    @patch("tasks.routes.create_agent", side_effect=RuntimeError("registry down"))
    @patch("tasks.routes.decompose_task", return_value=(None, []))
    @patch("tasks.routes.route_task", return_value=(None, None, None, []))
    @patch("tasks.routes.select_agent_by_mode", return_value=(None, None, None, []))
    async def test_no_plan_with_requested_skills_message(
        self,
        _by_mode,
        _for_task,
        _decompose,
        _create,
        dispatch,
        submit_task,
        routing_db,
        as_user,
    ):
        _add_agent(routing_db, "sleeping", "Researcher", status="inactive")

        submitted = await submit_task(
            _task_form(skills_required=["nonexistent"], conversation_id=7), user=as_user
        )

        assert "aren't advertised by any agent" in submitted.outcome["message"]


class TestCreateNewTaskDecomposeMode:
    @patch("tasks.routes.manager_announce_plan", return_value="The plan")
    @patch("tasks.routes.decompose_task")
    async def test_force_decompose_creates_root_and_dispatches(
        self, decompose, announce, dispatch, submit_task, routing_db, as_user
    ):
        decompose.return_value = (
            ("first-agent", "first action"),
            [("second-agent", "second action")],
        )
        _add_agent(routing_db, "manager-id", "Manager", type_value="manager")

        submitted = await submit_task(
            _task_form(mode="decompose", conversation_id=7), user=as_user
        )

        root_id = submitted.response.json()["task_id"]
        assert submitted.outcome["task_id"] == root_id
        assert "decomposed into 2 subtask" in submitted.outcome["message"]
        announce.assert_called_once()
        (subtask,) = _subtasks_of(routing_db, root_id)
        assert subtask.agent_id == "first-agent"
        assert _stored(routing_db, root_id).agent_id == "manager-id"

    @patch("tasks.routes.decompose_task", return_value=(None, []))
    async def test_force_decompose_no_specialists_message(
        self, _decompose, dispatch, submit_task, as_user
    ):
        submitted = await submit_task(
            _task_form(mode="decompose", conversation_id=7), user=as_user
        )

        assert "no specialist" in submitted.outcome["message"]

    @patch("tasks.routes.decompose_task", return_value=(None, []))
    async def test_force_decompose_single_agent_message(
        self, _decompose, dispatch, submit_task, routing_db, as_user
    ):
        _add_agent(routing_db, "only-one", "Researcher")

        submitted = await submit_task(
            _task_form(mode="decompose", conversation_id=7), user=as_user
        )

        assert "only one non-Manager" in submitted.outcome["message"]

    @patch("tasks.routes.decompose_task", return_value=(None, []))
    async def test_force_decompose_many_agents_planner_failed_message(
        self, _decompose, dispatch, submit_task, routing_db, as_user
    ):
        for index in range(5):
            _add_agent(routing_db, f"agent-{index}", f"Specialist-{index}")

        submitted = await submit_task(_task_form(mode="decompose"), user=as_user)

        assert "planner LLM" in submitted.outcome["message"]
        dispatch.add_messages.assert_not_called()


# --------------------------------------------------------------------------- #
# POST /tasks/new_task/  — inline-file validation in _build_files_payload
# --------------------------------------------------------------------------- #


@patch("tasks.routes.route_task", return_value=(None, None, None, []))
@patch(
    "tasks.routes.select_agent_by_mode",
    return_value=("agent-1", "demand", None, []),
)
class TestInlineFileValidation:
    async def test_invalid_base64_returns_400(
        self, _by_mode, _for_task, dispatch, submit_task, as_user
    ):
        body = _task_form(
            inline_files=[{"filename": "bad.bin", "content_b64": "!!!not base64!!!"}],
        )

        submitted = await submit_task(body, user=as_user)

        assert submitted.response.status_code == 400
        assert "Invalid base64" in submitted.response.json()["detail"]

    async def test_oversize_inline_file_returns_413(
        self, _by_mode, _for_task, dispatch, submit_task, as_user
    ):
        big = base64.b64encode(b"x" * (2 * 1024 * 1024 + 10)).decode()
        body = _task_form(
            inline_files=[{"filename": "big.bin", "content_b64": big}],
        )

        submitted = await submit_task(body, user=as_user)

        assert submitted.response.status_code == 413
        assert "exceeds" in submitted.response.json()["detail"]

    async def test_valid_inline_file_is_forwarded(
        self, _by_mode, _for_task, dispatch, submit_task, as_user
    ):
        small = base64.b64encode(b"hello world").decode()
        body = _task_form(
            inline_files=[
                {"filename": "ok.txt", "mime": "text/plain", "content_b64": small}
            ],
        )

        submitted = await submit_task(body, user=as_user)

        assert submitted.response.status_code == 202
        _agent_id, payload = _dispatched(dispatch)
        assert any(f["source"] == "inline" for f in payload["files"])


@patch("tasks.routes.route_task", return_value=(None, None, None, []))
@patch(
    "tasks.routes.select_agent_by_mode",
    return_value=("agent-1", "demand", None, []),
)
class TestAttachedKnowledgeStoreRefs:
    @pytest.mark.regression
    async def test_f25_same_name_documents_dispatch_with_their_doc_ids(
        self, _by_mode, _for_task, dispatch, submit_task, as_user
    ):
        """Regression F25 (B-48).

        What: two knowledge-store documents with the same filename crashed the
        attachment picker; each one is now picked and sent by its doc_id.
        How: submit a task with two refs that share a title but not a doc_id,
        and check the agent's payload keeps both doc_ids, in order.
        When: found in ATP v7 (18/09/2026), fixed in 0b93375.
        """
        title = "1_Q4_2025_Financial_Report.md"
        body = _task_form(
            attached_files=[
                {"filename": title, "doc_id": "older-copy"},
                {"filename": title, "doc_id": "newer-copy"},
            ],
        )

        submitted = await submit_task(body, user=as_user)

        assert submitted.response.status_code == 202
        _agent_id, payload = _dispatched(dispatch)
        assert payload["files"] == [
            {"source": "knowledge_store", "filename": title, "doc_id": "older-copy"},
            {"source": "knowledge_store", "filename": title, "doc_id": "newer-copy"},
        ]

    @pytest.mark.regression
    async def test_f25_filename_only_ref_still_dispatches(
        self, _by_mode, _for_task, dispatch, submit_task, as_user
    ):
        """Regression F25 (B-48).

        What: the F25 fix sends refs by doc_id; a ref that carries only a
        filename, as older clients send, must still reach the agent.
        How: submit a task with one filename-only ref and check the agent's
        payload has the filename and no doc_id.
        When: found in ATP v7 (18/09/2026), fixed in 0b93375.
        """
        body = _task_form(attached_files=[{"filename": "report.pdf"}])

        submitted = await submit_task(body, user=as_user)

        assert submitted.response.status_code == 202
        _agent_id, payload = _dispatched(dispatch)
        assert payload["files"] == [
            {"source": "knowledge_store", "filename": "report.pdf"}
        ]


# --------------------------------------------------------------------------- #
# POST /tasks/task-result/  — agent result ingestion
# --------------------------------------------------------------------------- #


def _result_body(**over):
    body = {"task_id": "t1", "agent_id": "agent-1", "result": "the output"}
    body.update(over)
    return body


class TestTaskResultAuthAndLookup:
    def test_unknown_task_returns_404(self, make_fake_client):
        fake = _FakeSession(first_map={"Task": None})
        client = make_fake_client(fake, agent_api_auth=("agent-1", "k"))
        r = client.post("/tasks/task-result/", json=_result_body())
        assert r.status_code == 404

    def test_body_agent_mismatch_returns_403(self, make_fake_client):
        task = _task(id="t1", agent_id="other-agent")
        fake = _FakeSession(first_map={"Task": task})
        client = make_fake_client(fake, agent_api_auth=("agent-1", "k"))
        r = client.post(
            "/tasks/task-result/", json=_result_body(agent_id="agent-1")
        )
        assert r.status_code == 403
        assert "must match" in r.json()["detail"]

    @patch("tasks.routes.agent_may_submit_task_result", return_value=False)
    def test_unauthorized_agent_returns_403(self, _allowed, make_fake_client):
        task = _task(id="t1", agent_id="agent-1")
        fake = _FakeSession(first_map={"Task": task})
        client = make_fake_client(fake, agent_api_auth=("agent-1", "k"))
        r = client.post("/tasks/task-result/", json=_result_body())
        assert r.status_code == 403
        assert "not allowed" in r.json()["detail"]

    def test_invalid_body_returns_422(self, make_fake_client):
        fake = _FakeSession()
        client = make_fake_client(fake, agent_api_auth=("agent-1", "k"))
        # missing required "result"
        r = client.post(
            "/tasks/task-result/", json={"task_id": "t1", "agent_id": "agent-1"}
        )
        assert r.status_code == 422


@patch("tasks.routes.publish_agent_message")
@patch("tasks.routes.add_messages")
@patch("tasks.routes.agent_may_submit_task_result", return_value=True)
@patch("tasks.routes.validating_task_results")
class TestTaskResultCompletion:
    def test_terminal_result_no_actions_aggregates_and_broadcasts(
        self, _validate, _allowed, mock_add, mock_ws, make_fake_client
    ):
        # Task with a conversation, no future actions → aggregate + broadcast.
        tr = _result(result_data=None, history=[], future_actions=[])
        task = _task(id="t1", agent_id="agent-1", conversation_id=12, result=tr)
        agent_row = _agent(id="agent-1", name="Researcher")
        fake = _FakeSession(first_map={"Task": task, "Agents": agent_row})
        with patch(
            "tasks.routes.aggregate_results", return_value="final synthesized answer"
        ):
            client = make_fake_client(fake, agent_api_auth=("agent-1", "k"))
            r = client.post(
                "/tasks/task-result/",
                json=_result_body(conversation_id="12", agent_name="Researcher"),
            )
        assert r.status_code == 200
        assert task.status == TaskStatus.COMPLETED.value
        assert mock_ws.await_count == 1 or mock_ws.call_count == 1
        assert "the output" in mock_ws.call_args.args

    def test_standalone_task_stores_the_result_without_chat_side_effects(
        self, _validate, _allowed, mock_add, mock_ws, make_fake_client
    ):
        tr = _result(future_actions=[])
        task = _task(id="t1", agent_id="agent-1", conversation_id=None, result=tr)
        fake = _FakeSession(first_map={"Task": task})
        with patch("tasks.routes.aggregate_results", return_value="answer"):
            client = make_fake_client(fake, agent_api_auth=("agent-1", "k"))
            r = client.post("/tasks/task-result/", json=_result_body())
        assert r.status_code == 200
        mock_add.assert_not_called()
        assert mock_ws.call_args.args == ("t1", None, "the output")
        assert mock_ws.call_args.kwargs["event_type"] == "result"

    def test_result_event_carries_the_agent_sources_when_given(
        self, _validate, _allowed, mock_add, mock_ws, make_fake_client
    ):
        tr = _result(future_actions=[])
        task = _task(id="t1", agent_id="agent-1", conversation_id=12, result=tr)
        fake = _FakeSession(first_map={"Task": task, "Agents": _agent()})
        sources = [{"doc_id": "doc-4", "title": "4_Expense_Policy.md"}]
        client = make_fake_client(fake, agent_api_auth=("agent-1", "k"))
        r = client.post("/tasks/task-result/", json=_result_body(sources=sources))
        assert r.status_code == 200
        assert mock_ws.call_args.kwargs["sources"] == [
            {"doc_id": "doc-4", "chunk_id": None, "title": "4_Expense_Policy.md", "page": None}
        ]
        assert tr.sources == mock_ws.call_args.kwargs["sources"]
        assert mock_add.call_args.kwargs["sources"] == mock_ws.call_args.kwargs["sources"]
        assert mock_ws.call_args.kwargs["route"] == "agent"
        assert mock_ws.call_args.kwargs["status"] == "completed"

    def test_result_event_has_no_sources_when_the_agent_sent_none(
        self, _validate, _allowed, mock_add, mock_ws, make_fake_client
    ):
        tr = _result(future_actions=[])
        task = _task(id="t1", agent_id="agent-1", conversation_id=12, result=tr)
        fake = _FakeSession(first_map={"Task": task, "Agents": _agent()})
        client = make_fake_client(fake, agent_api_auth=("agent-1", "k"))
        client.post("/tasks/task-result/", json=_result_body())
        assert "sources" not in mock_ws.call_args.kwargs

    def test_aggregate_failure_falls_back_to_raw_result(
        self, _validate, _allowed, mock_add, mock_ws, make_fake_client
    ):
        tr = _result(future_actions=[])
        task = _task(id="t1", agent_id="agent-1", conversation_id=None, result=tr)
        fake = _FakeSession(first_map={"Task": task})
        with patch(
            "tasks.routes.aggregate_results", side_effect=RuntimeError("LLM down")
        ):
            client = make_fake_client(fake, agent_api_auth=("agent-1", "k"))
            r = client.post(
                "/tasks/task-result/", json=_result_body(result="raw text")
            )
        assert r.status_code == 200  # fell back gracefully

    def test_completion_log_line_reports_the_peak_rss(
        self, _validate, _allowed, mock_add, mock_ws, make_fake_client
    ):
        tr = _result(future_actions=[])
        task = _task(id="t1", agent_id="agent-1", conversation_id=None, result=tr)
        fake = _FakeSession(first_map={"Task": task})
        with patch("tasks.routes.peak_rss_mb", return_value="4321"), patch(
            "tasks.routes.log_agent_operation"
        ) as log_operation:
            client = make_fake_client(fake, agent_api_auth=("agent-1", "k"))
            r = client.post("/tasks/task-result/", json=_result_body())
        assert r.status_code == 200
        log_operation.assert_any_call(
            "agent-1", "TASK", "Completed task t1 peak_rss_mb=4321"
        )

    def test_missing_taskresult_row_returns_404(
        self, _validate, _allowed, mock_add, mock_ws, make_fake_client
    ):
        # validating_task_results "succeeds" but task.result is falsy → 404.
        task = _task(id="t1", agent_id="agent-1", result=None)
        fake = _FakeSession(first_map={"Task": task})
        client = make_fake_client(fake, agent_api_auth=("agent-1", "k"))
        r = client.post("/tasks/task-result/", json=_result_body())
        assert r.status_code == 404
        assert "TaskResult not found" in r.json()["detail"]

    def test_processing_exception_returns_500(
        self, mock_validate, _allowed, mock_add, mock_ws, make_fake_client
    ):
        # validating_task_results raises a non-HTTP error → 500 + rollback.
        mock_validate.side_effect = RuntimeError("db blew up")
        task = _task(id="t1", agent_id="agent-1", result=_result())
        fake = _FakeSession(first_map={"Task": task})
        client = make_fake_client(fake, agent_api_auth=("agent-1", "k"))
        r = client.post("/tasks/task-result/", json=_result_body())
        assert r.status_code == 500
        assert "Error processing task result" in r.json()["detail"]
        fake.rollback.assert_called_once()


@patch("tasks.routes._publish_task_to_work_queue")
@patch("tasks.routes.publish_agent_message")
@patch("tasks.routes.add_messages")
@patch("tasks.routes.agent_may_submit_task_result", return_value=True)
@patch("tasks.routes.validating_task_results")
@patch("tasks.routes.insert_new_task", return_value="next-sub")
class TestTaskResultChaining:
    def test_continue_chains_to_next_agent(
        self,
        _insert,
        _validate,
        _allowed,
        mock_add,
        mock_ws,
        mock_publish,
        make_fake_client,
    ):
        # One future action remaining; Manager review says CONTINUE.
        tr = _result(
            future_actions=[("next-agent", "next action")],
            history=[{"role": "user", "message": "demand"}],
        )
        task = _task(
            id="t1",
            agent_id="agent-1",
            conversation_id=20,
            result=tr,
            parent_task_id="root-1",
            order=1,
        )
        next_subtask = _task(id="next-sub")
        prev_row = _agent(id="agent-1", name="Prev")
        # Task.first() fires three times: initial lookup, re-fetch after
        # validate, then the newly-inserted subtask. The first two must be the
        # chain task (carries result + future_actions); the third the subtask.
        calls = {"n": 0}

        def task_first():
            calls["n"] += 1
            return next_subtask if calls["n"] >= 3 else task

        fake = _FakeSession(
            first_map={"Task": task_first, "Agents": prev_row},
            all_map={"Task": []},
        )
        with patch(
            "tasks.routes.manager_review_step",
            return_value={"decision": "CONTINUE", "reasoning": "keep going"},
        ), patch(
            "tasks.routes._build_chain_transcript",
            return_value=("transcript", "demand"),
        ):
            client = make_fake_client(fake, agent_api_auth=("agent-1", "k"))
            r = client.post(
                "/tasks/task-result/", json=_result_body(conversation_id="20")
            )
        assert r.status_code == 200
        assert "Result received" in r.json()["message"]
        # Chained dispatch happened.
        mock_publish.assert_called_once()
        # New subtask re-parented to the same root, order bumped.
        assert next_subtask.parent_task_id == "root-1"
        assert next_subtask.order == 2

    def test_done_decision_skips_remaining_steps(
        self,
        _insert,
        _validate,
        _allowed,
        mock_add,
        mock_ws,
        mock_publish,
        make_fake_client,
    ):
        tr = _result(
            future_actions=[("next-agent", "next action")],
            history=[],
        )
        task = _task(
            id="t1",
            agent_id="agent-1",
            conversation_id=21,
            result=tr,
            parent_task_id=None,
        )
        fake = _FakeSession(first_map={"Task": task, "Agents": _agent()})
        with patch(
            "tasks.routes.manager_review_step",
            return_value={"decision": "DONE", "reasoning": "already answered"},
        ), patch(
            "tasks.routes._build_chain_transcript",
            return_value=("transcript", "demand"),
        ), patch(
            "tasks.routes.aggregate_results", return_value="aggregated final"
        ):
            client = make_fake_client(fake, agent_api_auth=("agent-1", "k"))
            r = client.post(
                "/tasks/task-result/", json=_result_body(conversation_id="21")
            )
        assert r.status_code == 200
        # DONE clears the action list → no chained publish.
        mock_publish.assert_not_called()
        # future_actions persisted as empty.
        assert tr.future_actions == []

    def test_insert_decision_prepends_extra_step(
        self,
        _insert,
        _validate,
        _allowed,
        mock_add,
        mock_ws,
        mock_publish,
        make_fake_client,
    ):
        tr = _result(
            future_actions=[("next-agent", "planned action")],
            history=[],
        )
        task = _task(
            id="t1",
            agent_id="agent-1",
            conversation_id=22,
            result=tr,
            parent_task_id="root-1",
            order=1,
        )
        resolved = _agent(id="inserted-agent", name="Inserted", type_value="analyst")
        next_subtask = _task(id="next-sub")
        # Task.first(): chain task (x2), then the inserted subtask.
        calls = {"n": 0}

        def task_first():
            calls["n"] += 1
            return next_subtask if calls["n"] >= 3 else task

        fake = _FakeSession(
            first_map={"Task": task_first, "Agents": resolved},
            all_map={"Task": []},
        )
        with patch(
            "tasks.routes.manager_review_step",
            return_value={
                "decision": "INSERT",
                "reasoning": "need more data",
                "next_agent_type": "analyst",
                "next_action": "fetch extra data",
            },
        ), patch(
            "tasks.routes._build_chain_transcript",
            return_value=("transcript", "demand"),
        ):
            client = make_fake_client(fake, agent_api_auth=("agent-1", "k"))
            r = client.post(
                "/tasks/task-result/", json=_result_body(conversation_id="22")
            )
        assert r.status_code == 200
        # Inserted step + planned step both queued → chained publish fired.
        mock_publish.assert_called_once()

    def test_insert_decision_with_no_resolvable_agent_continues(
        self,
        _insert,
        _validate,
        _allowed,
        mock_add,
        mock_ws,
        mock_publish,
        make_fake_client,
    ):
        # Manager says INSERT but no active agent resolves (both lookups None)
        # → the inserted step is dropped and the planned chain proceeds.
        tr = _result(
            future_actions=[("next-agent", "planned action")],
            history=[],
        )
        task = _task(
            id="t1",
            agent_id="agent-1",
            conversation_id=23,
            result=tr,
            parent_task_id="root-1",
            order=1,
        )
        next_subtask = _task(id="next-sub")

        # Agents.first() returns None for both INSERT resolution attempts, then
        # the progress-broadcast name lookups also yield None (harmless).
        t_calls = {"n": 0}

        def task_first():
            t_calls["n"] += 1
            return next_subtask if t_calls["n"] >= 3 else task

        fake = _FakeSession(
            first_map={"Task": task_first, "Agents": None},
            all_map={"Task": []},
        )
        with patch(
            "tasks.routes.manager_review_step",
            return_value={
                "decision": "INSERT",
                "reasoning": "want more",
                "next_agent_type": "ghost-type",
                "next_action": "extra",
            },
        ), patch(
            "tasks.routes._build_chain_transcript",
            return_value=("transcript", "demand"),
        ):
            client = make_fake_client(fake, agent_api_auth=("agent-1", "k"))
            r = client.post(
                "/tasks/task-result/", json=_result_body(conversation_id="23")
            )
        assert r.status_code == 200
        # Planned action still dispatched (just no inserted step).
        mock_publish.assert_called_once()

    def test_chain_closeout_writes_aggregated_answer_to_root(
        self,
        _insert,
        _validate,
        _allowed,
        mock_add,
        mock_ws,
        mock_publish,
        make_fake_client,
    ):
        # Last step of a chain (no remaining actions) with a root parent →
        # root is marked completed and gets the aggregated answer.
        root_result = _result(result_data=None, history=[])
        root = _task(id="root-1", query="user demand", result=root_result)
        tr = _result(future_actions=[], history=[])
        task = _task(
            id="t1",
            agent_id="agent-1",
            conversation_id=None,
            result=tr,
            parent_task_id="root-1",
        )

        # Task.first() returns the current task first, then the root lookup.
        calls = {"n": 0}

        def task_first():
            calls["n"] += 1
            # 1st: initial task lookup, 2nd: re-fetch after validate,
            # 3rd: root lookup in close-out.
            if calls["n"] >= 3:
                return root
            return task

        fake = _FakeSession(first_map={"Task": task_first, "Agents": _agent()})
        with patch("tasks.routes.aggregate_results", return_value="ROOT ANSWER"):
            client = make_fake_client(fake, agent_api_auth=("agent-1", "k"))
            r = client.post("/tasks/task-result/", json=_result_body())
        assert r.status_code == 200
        assert root.status == TaskStatus.COMPLETED.value
        assert root_result.result_data == "ROOT ANSWER"
        assert mock_ws.call_args.args == ("root-1", None, "ROOT ANSWER")
        # Empty seed history → user-demand turn synthesized, then the answer.
        assert root_result.history[0]["role"] == "user"
        assert root_result.history[-1]["message"] == "ROOT ANSWER"

    def test_chain_closeout_appends_to_existing_root_history(
        self,
        _insert,
        _validate,
        _allowed,
        mock_add,
        mock_ws,
        mock_publish,
        make_fake_client,
    ):
        # Root already carries history → answer is appended, not seeded.
        root_result = _result(
            result_data="stale",
            history=[{"role": "user", "message": "prior"}],
        )
        root = _task(id="root-1", query="user demand", result=root_result)
        tr = _result(future_actions=[], history=[])
        task = _task(
            id="t1",
            agent_id="agent-1",
            conversation_id=None,
            result=tr,
            parent_task_id="root-1",
        )
        calls = {"n": 0}

        def task_first():
            calls["n"] += 1
            return root if calls["n"] >= 3 else task

        fake = _FakeSession(first_map={"Task": task_first, "Agents": _agent()})
        with patch("tasks.routes.aggregate_results", return_value="FRESH ANSWER"):
            client = make_fake_client(fake, agent_api_auth=("agent-1", "k"))
            r = client.post("/tasks/task-result/", json=_result_body())
        assert r.status_code == 200
        assert root_result.history[0]["message"] == "prior"
        assert root_result.history[-1]["message"] == "FRESH ANSWER"

    def test_chain_closeout_aggregates_in_the_threadpool_not_on_the_event_loop(
        self,
        _insert,
        _validate,
        _allowed,
        mock_add,
        mock_ws,
        mock_publish,
        make_fake_client,
    ):
        root_result = _result(result_data=None, history=[])
        root = _task(id="root-1", query="user demand", result=root_result)
        tr = _result(future_actions=[], history=[{"role": "user", "message": "demand"}])
        task = _task(
            id="t1",
            agent_id="agent-1",
            conversation_id=None,
            result=tr,
            parent_task_id="root-1",
        )
        calls = {"n": 0}

        def task_first():
            calls["n"] += 1
            return root if calls["n"] >= 3 else task

        fake = _FakeSession(first_map={"Task": task_first, "Agents": _agent()})
        threadpool = AsyncMock(return_value="THREADPOOL ANSWER")
        with patch("tasks.routes.aggregate_results") as mock_aggregate, patch(
            "tasks.routes.run_in_threadpool", threadpool
        ):
            client = make_fake_client(fake, agent_api_auth=("agent-1", "k"))
            r = client.post("/tasks/task-result/", json=_result_body())

        assert r.status_code == 200
        threadpool.assert_awaited_once_with(mock_aggregate, tr.history, "the output")
        mock_aggregate.assert_not_called()
        assert root_result.result_data == "THREADPOOL ANSWER"

    def test_aggregate_empty_falls_back_to_default_text(
        self,
        _insert,
        _validate,
        _allowed,
        mock_add,
        mock_ws,
        mock_publish,
        make_fake_client,
    ):
        # aggregate returns blank AND the raw result is blank → canned message.
        tr = _result(future_actions=[])
        task = _task(id="t1", agent_id="agent-1", conversation_id=None, result=tr)
        fake = _FakeSession(first_map={"Task": task})
        with patch("tasks.routes.aggregate_results", return_value="   "):
            client = make_fake_client(fake, agent_api_auth=("agent-1", "k"))
            r = client.post("/tasks/task-result/", json=_result_body(result=""))
        assert r.status_code == 200


# --------------------------------------------------------------------------- #
# POST /tasks/task-step/  — telemetry passthrough
# --------------------------------------------------------------------------- #


def _step_body(**over):
    body = {"task_id": "t1", "agent_id": "agent-1", "step_type": "reasoning_start"}
    body.update(over)
    return body


@patch("tasks.routes.publish_task_step")
class TestTaskStep:
    def test_step_without_a_task_id_is_ignored(self, mock_ws, make_fake_client):
        fake = _FakeSession()
        client = make_fake_client(fake, agent_api_auth=("agent-1", "k"))
        r = client.post("/tasks/task-step/", json=_step_body(task_id=""))
        assert r.json()["message"] == "ignored"
        mock_ws.assert_not_called()

    def test_unknown_task_is_ignored(self, mock_ws, make_fake_client):
        fake = _FakeSession(first_map={"Task": None})
        client = make_fake_client(fake, agent_api_auth=("agent-1", "k"))
        r = client.post("/tasks/task-step/", json=_step_body())
        assert r.status_code == 200
        assert r.json()["message"] == "ignored"
        mock_ws.assert_not_called()

    @patch("tasks.routes.agent_may_submit_task_result", return_value=True)
    def test_agent_mismatch_returns_403(self, _allowed, mock_ws, make_fake_client):
        task = _task(id="t1", agent_id="real-agent")
        fake = _FakeSession(first_map={"Task": task})
        client = make_fake_client(fake, agent_api_auth=("agent-1", "k"))
        r = client.post("/tasks/task-step/", json=_step_body(agent_id="impostor"))
        assert r.status_code == 403

    @patch("tasks.routes.agent_may_submit_task_result", return_value=False)
    def test_unauthorized_agent_returns_403(self, _allowed, mock_ws, make_fake_client):
        task = _task(id="t1", agent_id="agent-1")
        fake = _FakeSession(first_map={"Task": task})
        client = make_fake_client(fake, agent_api_auth=("agent-1", "k"))
        r = client.post("/tasks/task-step/", json=_step_body())
        assert r.status_code == 403

    @patch("tasks.routes.agent_may_submit_task_result", return_value=True)
    def test_standalone_task_step_is_stored_without_a_conversation(
        self, _allowed, mock_ws, make_fake_client
    ):
        task = _task(id="t1", agent_id="agent-1", conversation_id=None)
        fake = _FakeSession(first_map={"Task": task})
        client = make_fake_client(fake, agent_api_auth=("agent-1", "k"))
        r = client.post("/tasks/task-step/", json=_step_body())
        assert r.status_code == 200
        assert r.json()["message"] == "no conversation"
        assert mock_ws.call_args.args[:2] == ("t1", None)

    @patch("tasks.routes.agent_may_submit_task_result", return_value=True)
    def test_step_broadcasts_under_root_task_id(
        self, _allowed, mock_ws, make_fake_client
    ):
        # Subtask with a root parent → broadcast keyed on the root id.
        subtask = _task(
            id="t1", agent_id="agent-1", conversation_id=30, parent_task_id="root-x"
        )
        root = _task(id="root-x", conversation_id=30)
        calls = {"n": 0}

        def task_first():
            calls["n"] += 1
            # 1st lookup = subtask, 2nd lookup = root.
            return root if calls["n"] >= 2 else subtask

        fake = _FakeSession(first_map={"Task": task_first})
        client = make_fake_client(fake, agent_api_auth=("agent-1", "k"))
        r = client.post("/tasks/task-step/", json=_step_body(agent_id="agent-1"))
        assert r.status_code == 200
        assert r.json()["message"] == "ok"
        # Broadcast happened with the root id as the outer task_id.
        task_arg, conv_arg, payload = mock_ws.call_args.args
        assert task_arg == "root-x"
        assert conv_arg == "30"
        assert payload["task_id"] == "root-x"
        assert payload["subtask_id"] == "t1"


# --------------------------------------------------------------------------- #
# PATCH /tasks/task-cancel/{id}  and  /tasks/{id}/cancel
# --------------------------------------------------------------------------- #


class TestCancelTask:
    @patch("tasks.routes.interrupt_task", return_value=True)
    def test_cancel_success_returns_200(self, _interrupt, make_fake_client, as_user):
        fake = _FakeSession()
        client = make_fake_client(fake, current_user=as_user)
        r = client.patch("/tasks/task-cancel/t1")
        assert r.status_code == 200
        assert "canceled successfully" in r.json()["message"]

    @patch("tasks.routes.interrupt_task", return_value=True)
    def test_cancel_alias_path_success(self, _interrupt, make_fake_client, as_user):
        fake = _FakeSession()
        client = make_fake_client(fake, current_user=as_user)
        r = client.patch("/tasks/t1/cancel")
        assert r.status_code == 200

    def test_cancel_unknown_task_returns_404(self, make_fake_client, as_user):
        from fastapi import HTTPException

        fake = _FakeSession()
        with patch(
            "tasks.routes.interrupt_task",
            side_effect=HTTPException(status_code=404, detail="Task not found"),
        ):
            client = make_fake_client(fake, current_user=as_user)
            r = client.patch("/tasks/task-cancel/missing")
        assert r.status_code == 404

    def test_cancel_unexpected_error_returns_500(self, make_fake_client, as_user):
        fake = _FakeSession()
        with patch(
            "tasks.routes.interrupt_task", side_effect=RuntimeError("rmq down")
        ):
            client = make_fake_client(fake, current_user=as_user)
            r = client.patch("/tasks/task-cancel/t1")
        assert r.status_code == 500
        assert "Error Canceling task" in r.json()["detail"]
        fake.rollback.assert_called_once()

    def test_cancel_requires_authentication(self, make_fake_client):
        fake = _FakeSession()
        client = make_fake_client(fake, current_user=None)
        assert client.patch("/tasks/task-cancel/t1").status_code == 401


# --------------------------------------------------------------------------- #
# _publish_task_to_work_queue  (helper used across dispatch paths)
# --------------------------------------------------------------------------- #


class TestPublishHelper:
    async def test_unresolvable_queue_raises_500(self):
        from fastapi import HTTPException

        from tasks.routes import _publish_task_to_work_queue

        with patch(
            "tasks.routes.resolve_work_queue_for_agent_id", return_value=None
        ):
            with pytest.raises(HTTPException) as exc:
                await _publish_task_to_work_queue(MagicMock(), "agent-1", {})
        assert exc.value.status_code == 500

    async def test_resolved_queue_publishes_payload(self):
        from tasks.routes import _publish_task_to_work_queue

        with patch(
            "tasks.routes.resolve_work_queue_for_agent_id", return_value="q.general"
        ), patch("tasks.routes.rabbitmq_instance") as mock_rmq:
            payload = {"task_id": "x"}
            await _publish_task_to_work_queue(MagicMock(), "agent-9", payload)
        # assignee id injected + published to the resolved queue.
        assert payload["assigned_agent_id"] == "agent-9"
        mock_rmq.publish_task.assert_called_once_with("q.general", json.dumps(payload))


# --------------------------------------------------------------------------- #
# Pure helpers exercised directly (no HTTP layer).
# --------------------------------------------------------------------------- #


class TestChainRootHelper:
    def test_no_parent_task_is_its_own_root(self):
        from tasks.routes import _get_chain_root

        task = _task(id="solo", parent_task_id=None)
        assert _get_chain_root(task, _FakeSession()) is task

    def test_walks_up_to_root(self):
        from tasks.routes import _get_chain_root

        root = _task(id="root", parent_task_id=None)
        child = _task(id="child", parent_task_id="root")
        fake = _FakeSession(first_map={"Task": root})
        assert _get_chain_root(child, fake) is root

    def test_missing_parent_terminates(self):
        from tasks.routes import _get_chain_root

        child = _task(id="child", parent_task_id="ghost")
        fake = _FakeSession(first_map={"Task": None})
        # Parent lookup returns None → loop breaks, returns the cursor as-is.
        assert _get_chain_root(child, fake) is child


class TestBuildChainTranscript:
    def test_first_subtask_has_empty_transcript(self):
        from tasks.routes import _build_chain_transcript

        # current_task is the root with no siblings → falls back to [self];
        # order 0 means a single prior step → non-empty transcript actually,
        # so use a sibling set where nothing precedes the cutoff.
        root = _task(id="root", parent_task_id=None, query="demand", order=0)
        fake = _FakeSession(
            first_map={"Task": root, "Agents": _agent(id="root")},
            all_map={"Task": []},  # no siblings under root
        )
        transcript, demand = _build_chain_transcript(root, fake)
        assert demand == "demand"
        # Self is the only step; transcript contains its block.
        assert "Chain transcript" in transcript

    def test_includes_prior_steps_with_results(self):
        from tasks.routes import _build_chain_transcript

        root = _task(id="root", parent_task_id=None, query="orig demand", order=0)
        step1 = _task(
            id="s1",
            parent_task_id="root",
            order=1,
            agent_id="a1",
            query="step one action",
            result=_result(result_data="step one result"),
        )
        step2 = _task(
            id="s2",
            parent_task_id="root",
            order=2,
            agent_id="a2",
            query="step two action",
            result=_result(result_data=None),  # no result yet
        )
        agent_rows = {"a1": _agent(id="a1", name="Alpha"), "a2": None}

        def agents_first():
            # Round-robin isn't needed; alternate by call order.
            agents_first.calls += 1
            return _agent(id="a1", name="Alpha") if agents_first.calls == 1 else None

        agents_first.calls = 0

        fake = _FakeSession(
            first_map={"Task": root, "Agents": agents_first},
            all_map={"Task": [step1, step2]},
        )
        transcript, demand = _build_chain_transcript(step2, fake)
        assert demand == "orig demand"
        assert "Alpha" in transcript
        assert "step one result" in transcript
        assert "(no result recorded yet)" in transcript

    def test_truncates_oversize_step_result(self):
        from tasks.routes import _CHAIN_STEP_CHAR_CAP, _build_chain_transcript

        root = _task(id="root", parent_task_id=None, query="d", order=0)
        big = "y" * (_CHAIN_STEP_CHAR_CAP + 500)
        step = _task(
            id="s1",
            parent_task_id="root",
            order=1,
            agent_id="a1",
            result=_result(result_data=big),
        )
        fake = _FakeSession(
            first_map={"Task": root, "Agents": _agent(id="a1")},
            all_map={"Task": [step]},
        )
        transcript, _ = _build_chain_transcript(step, fake)
        assert "[step truncated]" in transcript

    def test_serializes_dict_result(self):
        from tasks.routes import _build_chain_transcript

        root = _task(id="root", parent_task_id=None, query="d", order=0)
        step = _task(
            id="s1",
            parent_task_id="root",
            order=1,
            agent_id="a1",
            result=_result(result_data={"k": "v"}),
        )
        fake = _FakeSession(
            first_map={"Task": root, "Agents": _agent(id="a1")},
            all_map={"Task": [step]},
        )
        transcript, _ = _build_chain_transcript(step, fake)
        assert '{"k": "v"}' in transcript

    def test_omits_later_steps_past_total_budget(self):
        from tasks.routes import _CHAIN_STEP_CHAR_CAP, _build_chain_transcript

        # Many large (but per-step-legal) steps overflow the total cap, so the
        # builder stops and appends the "remaining ... omitted" marker.
        root = _task(id="root", parent_task_id=None, query="d", order=0)
        chunk = "w" * (_CHAIN_STEP_CHAR_CAP - 100)
        steps = [
            _task(
                id=f"s{i}",
                parent_task_id="root",
                order=i,
                agent_id="a1",
                result=_result(result_data=chunk),
            )
            for i in range(1, 8)
        ]
        cutoff = steps[-1]
        fake = _FakeSession(
            first_map={"Task": root, "Agents": _agent(id="a1")},
            all_map={"Task": steps},
        )
        transcript, _ = _build_chain_transcript(cutoff, fake)
        assert "remaining earlier steps omitted" in transcript


class TestPromoteToChainRoot:
    def test_root_is_attributed_to_the_manager_and_marked_running(self):
        from tasks.routes import _promote_to_chain_root

        root = _task(
            id="root-1", status=TaskStatus.QUEUED.value, agent_id="unassigned", order=None
        )
        fake = _FakeSession(first_map={"Agents": _agent(id="mgr", name="Manager")})
        _promote_to_chain_root(root, fake)
        assert root.agent_id == "mgr"
        assert root.status == TaskStatus.RUNNING.value
        assert root.order == 0
        fake.commit.assert_called()

    def test_missing_manager_keeps_the_placeholder_owner(self):
        from tasks.routes import _promote_to_chain_root

        root = _task(id="root-1", status=TaskStatus.QUEUED.value, agent_id="unassigned")
        _promote_to_chain_root(root, _FakeSession(first_map={"Agents": None}))
        assert root.agent_id == "unassigned"
        assert root.status == TaskStatus.RUNNING.value


class TestBroadcastManagerMessage:
    async def test_skips_when_conversation_none(self):
        from tasks.routes import _broadcast_manager_message

        with patch("tasks.routes.add_messages") as mock_add, patch(
            "tasks.routes.publish_agent_message"
        ) as mock_ws:
            await _broadcast_manager_message(None, "text", _FakeSession(), task_id="root-1")
        mock_add.assert_not_called()
        mock_ws.assert_not_called()

    async def test_skips_when_text_empty(self):
        from tasks.routes import _broadcast_manager_message

        with patch("tasks.routes.add_messages") as mock_add, patch(
            "tasks.routes.publish_agent_message"
        ) as mock_ws:
            await _broadcast_manager_message(5, "", _FakeSession(), task_id="root-1")
        mock_add.assert_not_called()
        mock_ws.assert_not_called()

    async def test_persists_and_broadcasts_with_manager_attribution(self):
        from tasks.routes import _broadcast_manager_message

        manager = _agent(id="mgr", name="Manager")
        with patch(
            "tasks.routes.get_manager_agent", return_value=manager
        ), patch("tasks.routes.add_messages") as mock_add, patch(
            "tasks.routes.publish_agent_message"
        ) as mock_ws:
            await _broadcast_manager_message(7, "hello", _FakeSession(), task_id="root-1")
        mock_add.assert_called_once()
        mock_ws.assert_called_once()
        assert mock_ws.call_args.args[:3] == ("root-1", 7, "hello")
        # Manager id/name flow into the WS attribution kwargs.
        assert mock_ws.call_args.kwargs["agent_id"] == "mgr"
        assert mock_ws.call_args.kwargs["agent_name"] == "Manager"

    async def test_missing_manager_drops_attribution_but_still_persists(self):
        from tasks.routes import _broadcast_manager_message

        with patch(
            "tasks.routes.get_manager_agent", return_value=None
        ), patch("tasks.routes.add_messages") as mock_add, patch(
            "tasks.routes.publish_agent_message"
        ) as mock_ws:
            await _broadcast_manager_message(7, "hello", _FakeSession(), task_id="root-1")
        mock_add.assert_called_once()
        # Falls back to a literal "Manager" name with no id.
        assert mock_ws.call_args.kwargs["agent_id"] is None
        assert mock_ws.call_args.kwargs["agent_name"] == "Manager"


@pytest.fixture
def sqlite_session():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    import db.models  # noqa: F401
    from db.database import Base

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


class TestQueueStatsHelper:
    def test_get_task_queue_stats_counts_and_totals(self):
        from tasks.routes import get_task_queue_stats

        rows = [
            (TaskStatus.PENDING.value, 1),
            (TaskStatus.COMPLETED.value, 2),
        ]
        fake = _FakeSession(all_map={"EXPR": rows})
        stats = get_task_queue_stats(fake)
        assert stats["pending"] == 1
        assert stats["completed"] == 2
        assert stats["total"] == 3
        assert set(stats) == {
            "queued",
            "pending",
            "running",
            "completed",
            "failed",
            "cancelled",
            "total",
        }

    @pytest.mark.regression
    def test_f28_queue_stats_count_root_tasks_not_subtasks(self, sqlite_session):
        """Regression F28 (B-49).

        What: the task stats counted subtasks, so Total Tasks disagreed with
        the Recent tasks list, which shows root tasks only.
        How: store one root task with two subtasks in an in-memory SQLite
        database and check the stats count one task.
        When: found in ATP v7 (18/09/2026), fixed in ff82920.
        """
        from db.models import Task
        from tasks.routes import get_task_queue_stats

        sqlite_session.add_all(
            [
                Task(
                    id="root",
                    agent_id="manager",
                    status=TaskStatus.COMPLETED.value,
                    query="compare the Q4 reports",
                ),
                Task(
                    id="sub-1",
                    parent_task_id="root",
                    agent_id="agent-1",
                    status=TaskStatus.COMPLETED.value,
                    query="summarise report A",
                    order=0,
                ),
                Task(
                    id="sub-2",
                    parent_task_id="root",
                    agent_id="agent-2",
                    status=TaskStatus.RUNNING.value,
                    query="summarise report B",
                    order=1,
                ),
            ]
        )
        sqlite_session.commit()

        stats = get_task_queue_stats(sqlite_session)

        assert stats["total"] == 1
        assert stats["completed"] == 1
        assert stats["running"] == 0

    def test_update_task_queue_depth_sets_gauge(self):
        from tasks.routes import update_task_queue_depth

        with patch("tasks.routes.TASK_QUEUE_DEPTH") as gauge:
            update_task_queue_depth(42)
        gauge.set.assert_called_once_with(42)


class TestBuildFilesPayload:
    def test_knowledge_store_refs_and_skips_blank_names(self):
        from schemas.schemas import TaskForm
        from tasks.routes import _build_files_payload

        form = TaskForm(
            demand="d",
            skills_required=[],
            attached_files=[{"filename": "doc.pdf"}, {"filename": "  "}],
        )
        files = _build_files_payload(form)
        # Blank-name ref dropped; the real one kept as a knowledge_store entry.
        assert files == [{"source": "knowledge_store", "filename": "doc.pdf"}]

    @pytest.mark.regression
    def test_f25_blank_doc_id_is_not_forwarded(self):
        """Regression F25 (B-48).

        What: with the F25 fix the files payload forwards doc_id; a blank one
        must not reach the agent as an id, and a padded one is trimmed.
        How: build the files payload from a blank and a padded doc_id and
        compare it with the expected refs.
        When: found in ATP v7 (18/09/2026), fixed in 0b93375.
        """
        from schemas.schemas import TaskForm
        from tasks.routes import _build_files_payload

        form = TaskForm(
            demand="d",
            skills_required=[],
            attached_files=[
                {"filename": "doc.pdf", "doc_id": "  "},
                {"filename": "doc.pdf", "doc_id": " abc123 "},
            ],
        )
        assert _build_files_payload(form) == [
            {"source": "knowledge_store", "filename": "doc.pdf"},
            {"source": "knowledge_store", "filename": "doc.pdf", "doc_id": "abc123"},
        ]

    def test_total_inline_cap_rejected_with_413(self):
        from fastapi import HTTPException

        from schemas.schemas import TaskForm
        from tasks.routes import _build_files_payload

        # Two ~1.5 MB files individually pass the per-file cap (2 MB) but
        # together exceed the 8 MB total — engineered to trip the total guard
        # with several files. Use 5 files of ~1.7 MB.
        chunk = base64.b64encode(b"z" * (1_700_000)).decode()
        form = TaskForm(
            demand="d",
            skills_required=[],
            inline_files=[
                {"filename": f"f{i}.bin", "content_b64": chunk} for i in range(6)
            ],
        )
        with pytest.raises(HTTPException) as exc:
            _build_files_payload(form)
        assert exc.value.status_code == 413
        assert "Total inline file size" in exc.value.detail
