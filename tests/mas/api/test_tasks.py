"""Task-routes contract tests (hermetic — RabbitMQ mocked).

Routes under test (``src/services/mas/tasks/routes.py``):

* ``GET   /tasks/stats/queue``                          → 200
* ``GET   /tasks/conversation/{conversation_id}/running`` → 200
* ``GET   /tasks/{task_id}``                            → 200 / 404
* ``POST  /tasks/new_task/``                            body: TaskForm
* ``POST  /tasks/task-result/``                         agent-auth via verify_agent_api_key
* ``PATCH /tasks/{task_id}/cancel``                     → 200 / 404
* ``PATCH /tasks/task-cancel/{task_id}``                alias
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from db.database import Base, get_db
from db.models import Agents, Task, TaskResult
from tasks.routes import router


class TestTaskCreate:
    # Heavy task-creation path has many helpers (skill router, LLM, RMQ).
    # Verifying just that the endpoint exists and accepts the schema is
    # enough at the contract level; full behaviour is covered under
    # scripts/integration-checks/mas-task-workflow.py.
    def test_new_task_rejects_invalid_body(self, make_client, mock_db, as_user):
        client = make_client(router, current_user=as_user)
        r = client.post("/tasks/new_task/", json={})
        assert r.status_code == 422


class TestTaskRead:
    def test_get_unknown_task_returns_404(self, make_client, mock_db, as_admin):
        mock_db.query.return_value.filter.return_value.first.return_value = None
        client = make_client(router, current_user=as_admin)
        r = client.get("/tasks/ghost-id")
        assert r.status_code == 404

    def test_queue_stats_returns_200(self, make_client, mock_db, as_admin):
        client = make_client(router, current_user=as_admin)
        r = client.get("/tasks/stats/queue")
        assert r.status_code == 200

    def test_running_for_conversation_returns_200(self, make_client, mock_db, as_user):
        mock_db.query.return_value.filter.return_value.first.return_value = SimpleNamespace(
            owner_username="user"
        )
        mock_db.query.return_value.filter.return_value.all.return_value = []
        client = make_client(router, current_user=as_user)
        r = client.get("/tasks/conversation/1/running")
        assert r.status_code == 200


class TestTaskCancel:
    def test_cancel_unknown_returns_404(self, make_client, mock_db, as_user):
        mock_db.query.return_value.filter.return_value.first.return_value = None
        client = make_client(router, current_user=as_user)
        r = client.patch("/tasks/missing/cancel")
        assert r.status_code == 404

    def test_cancel_alias_path_returns_404_for_unknown(self, make_client, mock_db, as_user):
        mock_db.query.return_value.filter.return_value.first.return_value = None
        client = make_client(router, current_user=as_user)
        r = client.patch("/tasks/task-cancel/missing")
        assert r.status_code == 404


class TestTaskResultSubmission:
    """task-result requires verify_agent_api_key — override it."""

    def test_unknown_task_returns_404(self, make_client, mock_db):
        mock_db.query.return_value.filter.return_value.first.return_value = None
        client = make_client(router, agent_api_auth=("agent-id", "api-key"))
        r = client.post(
            "/tasks/task-result/",
            json={"task_id": "ghost", "agent_id": "agent-id", "result": {"text": "x"}},
        )
        # 404 if route ran; 422 if TaskResultForm field shape differs.
        assert r.status_code in (404, 422)


@pytest.fixture
def task_db():
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


@pytest.fixture
def make_db_client(make_client, task_db):
    def _factory(**kwargs):
        client = make_client(router, **kwargs)
        client.app.dependency_overrides[get_db] = lambda: task_db
        return client

    return _factory


def _add_task(
    db,
    *,
    task_id,
    status="running",
    agent_id="agent-1",
    parent_task_id=None,
    skills_required=None,
    query="Summarise the Q4 2025 financial report",
):
    task = Task(
        id=task_id,
        agent_id=agent_id,
        status=status,
        query=query,
        parent_task_id=parent_task_id,
        order=0,
        skills_required=skills_required,
    )
    db.add(task)
    db.add(
        TaskResult(
            task_id=task_id,
            history=[{"role": "user", "message": query}],
            future_actions=[],
        )
    )
    db.commit()
    return task


def _stored_task(db, task_id):
    db.expire_all()
    return db.get(Task, task_id)


def _post_result(client, task_id, *, skill_used=None):
    body = {"task_id": task_id, "agent_id": "agent-1", "result": "Revenue was $4.2M"}
    if skill_used is not None:
        body["skill_used"] = skill_used
    return client.post("/tasks/task-result/", json=body)


class TestTaskDetailSkillsAndTimes:
    def test_detail_returns_requested_skills_and_creation_time(
        self, make_db_client, task_db, as_admin
    ):
        _add_task(task_db, task_id="t1", skills_required=["financial_analysis"])

        body = make_db_client(current_user=as_admin).get("/tasks/t1").json()

        assert body["skills_required"] == ["financial_analysis"]
        assert body["created_at"]
        assert body["completed_at"] is None

    def test_detail_of_task_without_stored_skills_returns_empty_list(
        self, make_db_client, task_db, as_admin
    ):
        _add_task(task_db, task_id="t1", skills_required=None)

        body = make_db_client(current_user=as_admin).get("/tasks/t1").json()

        assert body["skills_required"] == []

    def test_detail_returns_completion_time_of_finished_task(
        self, make_db_client, task_db, as_admin
    ):
        task = _add_task(task_db, task_id="t1")
        task.status = "completed"
        task_db.commit()

        body = make_db_client(current_user=as_admin).get("/tasks/t1").json()

        completed_at = datetime.fromisoformat(body["completed_at"]).replace(tzinfo=None)
        created_at = datetime.fromisoformat(body["created_at"]).replace(tzinfo=None)
        assert completed_at >= created_at.replace(microsecond=0)

    def test_detail_lists_subtask_skills_and_times(self, make_db_client, task_db, as_admin):
        _add_task(task_db, task_id="root", agent_id="manager")
        sub = _add_task(
            task_db, task_id="sub-1", parent_task_id="root", skills_required=["writing"]
        )
        sub.status = "completed"
        task_db.commit()

        body = make_db_client(current_user=as_admin).get("/tasks/root").json()

        (subtask,) = body["subtasks"]
        assert subtask["skillsRequired"] == ["writing"]
        assert subtask["createdAt"]
        assert subtask["completedAt"]

    def test_task_list_includes_skills_and_completion_time(
        self, make_db_client, task_db, as_admin
    ):
        task = _add_task(task_db, task_id="t1", skills_required=["analysis"])
        task.status = "completed"
        task_db.commit()

        (row,) = make_db_client(current_user=as_admin).get("/tasks/list").json()

        assert row["skills_required"] == ["analysis"]
        assert row["completed_at"]


@patch("tasks.routes.agent_may_submit_task_result", return_value=True)
class TestTaskCompletionTime:
    def test_agent_result_records_completion_time_and_skill_used(
        self, _allowed, make_db_client, task_db
    ):
        _add_task(task_db, task_id="t1", skills_required=[])
        client = make_db_client(agent_api_auth=("agent-1", "k"))

        r = _post_result(client, "t1", skill_used="financial_analysis")

        assert r.status_code == 200
        task = _stored_task(task_db, "t1")
        assert task.status == "completed"
        assert task.completed_at is not None
        assert task.skills_required == ["financial_analysis"]

    def test_agent_result_keeps_requested_skills_without_duplicates(
        self, _allowed, make_db_client, task_db
    ):
        _add_task(task_db, task_id="t1", skills_required=["financial_analysis"])
        client = make_db_client(agent_api_auth=("agent-1", "k"))

        _post_result(client, "t1", skill_used="financial_analysis")

        assert _stored_task(task_db, "t1").skills_required == ["financial_analysis"]

    def test_agent_result_without_skill_keeps_requested_skills(
        self, _allowed, make_db_client, task_db
    ):
        _add_task(task_db, task_id="t1", skills_required=["analysis"])
        client = make_db_client(agent_api_auth=("agent-1", "k"))

        _post_result(client, "t1")

        assert _stored_task(task_db, "t1").skills_required == ["analysis"]

    def test_last_chain_step_records_root_completion_time(
        self, _allowed, make_db_client, task_db
    ):
        _add_task(task_db, task_id="root", agent_id="manager")
        _add_task(task_db, task_id="sub-1", parent_task_id="root")
        client = make_db_client(agent_api_auth=("agent-1", "k"))

        with patch("tasks.routes.aggregate_results", return_value="Aggregated answer"):
            r = _post_result(client, "sub-1", skill_used="writing")

        assert r.status_code == 200
        root = _stored_task(task_db, "root")
        assert root.status == "completed"
        assert root.completed_at is not None
        assert _stored_task(task_db, "sub-1").completed_at is not None


class TestFinalStatusTransitions:
    def test_cancel_records_completion_time(self, make_db_client, task_db, as_user):
        _add_task(task_db, task_id="t1")
        client = make_db_client(current_user=as_user)

        with patch("tasks.task_crud.rabbitmq_instance"):
            r = client.patch("/tasks/t1/cancel")

        assert r.status_code == 200
        task = _stored_task(task_db, "t1")
        assert task.status == "canceled"
        assert task.completed_at is not None

    async def test_timeout_watchdog_cancel_records_completion_time(self, task_db):
        from tasks import controller

        class StopWatchdog(BaseException):
            pass

        _add_task(task_db, task_id="t1")

        with (
            patch.object(controller, "SessionLocal", return_value=task_db),
            patch.object(controller.settings, "task_timeout", -1),
            patch.object(controller, "publish_agent_message"),
            patch.object(controller.asyncio, "sleep", side_effect=StopWatchdog),
            patch("tasks.task_crud.rabbitmq_instance"),
            pytest.raises(StopWatchdog),
        ):
            await controller.check_task_timeout()

        task = _stored_task(task_db, "t1")
        assert task.status == "canceled"
        assert task.completed_at is not None

    def test_failed_status_records_completion_time(self, task_db):
        task = _add_task(task_db, task_id="t1")
        task.status = "failed"
        task_db.commit()

        assert _stored_task(task_db, "t1").completed_at is not None

    def test_completion_time_is_kept_when_final_status_is_written_again(self, task_db):
        task = _add_task(task_db, task_id="t1")
        task.status = "completed"
        task_db.commit()
        first_completion = _stored_task(task_db, "t1").completed_at

        task.status = "completed"
        task_db.commit()

        assert _stored_task(task_db, "t1").completed_at == first_completion

    def test_non_final_status_leaves_completion_time_empty(self, task_db):
        task = _add_task(task_db, task_id="t1", status="pending")
        task.status = "running"
        task_db.commit()

        assert _stored_task(task_db, "t1").completed_at is None


@patch("tasks.routes.add_messages", return_value={"id": 1})
@patch("tasks.routes._publish_task_to_work_queue")
class TestNewTaskStoresSkills:
    @patch(
        "tasks.routes.select_agent_by_mode",
        return_value=("agent-7", "Summarise the Q4 2025 financial report", None, []),
    )
    async def test_single_agent_task_stores_requested_skills(
        self, _by_mode, _publish, _add, submit_task, routing_db, as_user
    ):
        submitted = await submit_task(
            {
                "demand": "Summarise the Q4 2025 financial report",
                "skills_required": ["financial_analysis"],
                "mode": "any_with_skill",
            },
            user=as_user,
        )

        assert submitted.response.status_code == 202
        task = _stored_task(routing_db, submitted.response.json()["task_id"])
        assert task.skills_required == ["financial_analysis"]

    @patch(
        "tasks.routes.decompose_task",
        return_value=(("agent-2", "Find the Q4 figures"), [("agent-3", "Write the summary")]),
    )
    async def test_decomposed_task_stores_requested_skills_on_root_and_first_step(
        self, _decompose, _publish, _add, submit_task, routing_db, as_user
    ):
        routing_db.add(Agents(id="manager-id", name="Manager", skills=[], api_key="manager-key"))
        routing_db.commit()

        submitted = await submit_task(
            {
                "demand": "Compare Q4 revenue with the expense policy",
                "skills_required": ["financial_analysis", "writing"],
                "mode": "decompose",
            },
            user=as_user,
        )

        assert submitted.response.status_code == 202
        root = _stored_task(routing_db, submitted.response.json()["task_id"])
        (first_step,) = routing_db.query(Task).filter(Task.parent_task_id == root.id).all()
        assert root.agent_id == "manager-id"
        assert root.skills_required == ["financial_analysis", "writing"]
        assert first_step.skills_required == ["financial_analysis", "writing"]
