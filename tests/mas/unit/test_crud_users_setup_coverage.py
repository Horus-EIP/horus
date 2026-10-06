"""Coverage-focused unit tests for several mid-size MAS modules.

Targets:
  * tasks.task_crud            — DB-bound task lifecycle helpers
  * users.user_tool_functions  — user CRUD helpers
  * tasks.collaborative_task   — pure pydantic orchestration logic
  * core.embedding_setup       — lazy sentence-embedding loader
  * alembic_helper             — migration CLI dispatcher

Hermetic: the service-level ``conftest`` already mocks torch/transformers and
points the app at in-memory SQLite. Every test here mocks its own DB session,
embedding model, and subprocess so nothing real runs. All monkeypatch/patch
usage auto-reverts, so module globals / env / sys.argv are never permanently
mutated.
"""

from __future__ import annotations

import asyncio
import threading
from unittest.mock import MagicMock, patch

import alembic_helper
import numpy as np
import pytest
from fastapi import HTTPException

from core import embedding_setup
from tasks import task_crud
from tasks.collaborative_task import CollaborativeTask, SubTask, TaskStatus
from tasks.status import TaskStatus as TaskRunStatus
from users import user_tool_functions

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _query_returning(value):
    """Build a MagicMock db whose ``query(...).filter(...).first()`` -> value."""
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = value
    return db


# =========================================================================== #
# tasks.task_crud
# =========================================================================== #


class TestInsertNewTask:
    def test_success_returns_new_task_id(self):
        db = MagicMock()
        task_id = task_crud.insert_new_task(
            conversation_id=7,
            agent_id="agent-A",
            query="do the thing",
            history=[{"role": "user", "message": "hi"}],
            future_actions=["step1"],
            db=db,
        )
        # A uuid string is returned and two rows (Task + TaskResult) committed.
        assert isinstance(task_id, str)
        assert len(task_id) == 36  # uuid4 hex-with-dashes
        assert db.add.call_count == 2
        assert db.commit.call_count == 2
        db.rollback.assert_not_called()

    def test_failure_rolls_back_and_returns_none(self):
        db = MagicMock()
        db.commit.side_effect = RuntimeError("db down")
        result = task_crud.insert_new_task(
            conversation_id=None,
            agent_id="agent-B",
            query="q",
            history=[],
            future_actions=[],
            db=db,
        )
        assert result is None
        db.rollback.assert_called_once()


class TestInsertQueuedTask:
    def test_stores_a_queued_task_owned_by_the_submitter(self):
        db = MagicMock()
        task = task_crud.insert_queued_task(
            "task-1", 7, "manager-id", "Summarise Q4", "alice", db, skills_required=["analysis"]
        )
        (stored_task,), (stored_result,) = (call.args for call in db.add.call_args_list)
        assert stored_task is task
        assert task.status == TaskRunStatus.QUEUED
        assert task.owner_username == "alice"
        assert task.skills_required == ["analysis"]
        assert stored_result.history == [{"role": "user", "message": "Summarise Q4"}]
        assert stored_result.future_actions == []
        db.commit.assert_called_once()

    def test_failure_rolls_back_and_raises(self):
        db = MagicMock()
        db.commit.side_effect = RuntimeError("db down")
        with pytest.raises(RuntimeError):
            task_crud.insert_queued_task("task-1", None, "manager-id", "q", "alice", db)
        db.rollback.assert_called_once()


class TestValidatingTaskResults:
    def test_success_marks_completed_and_appends_history(self):
        task = MagicMock()
        result_shell = MagicMock()
        result_shell.history = [{"role": "user", "message": "q"}]
        task.result = result_shell
        db = _query_returning(task)

        task_crud.validating_task_results("task-1", "the answer", db)

        assert task.status == TaskRunStatus.COMPLETED
        assert result_shell.result_data == "the answer"
        # Original turn preserved + assistant turn appended.
        assert result_shell.history[-1] == {
            "role": "assistant",
            "message": "the answer",
        }
        db.commit.assert_called_once()

    def test_success_with_null_history_initialises_list(self):
        task = MagicMock()
        result_shell = MagicMock()
        result_shell.history = None
        task.result = result_shell
        db = _query_returning(task)

        task_crud.validating_task_results("task-1", "answer", db)

        assert result_shell.history == [{"role": "assistant", "message": "answer"}]

    def test_task_not_found_raises_404(self):
        db = _query_returning(None)
        with pytest.raises(HTTPException) as exc:
            task_crud.validating_task_results("missing", "r", db)
        assert exc.value.status_code == 404
        assert exc.value.detail == "Task not found"

    def test_missing_task_result_raises_404(self):
        task = MagicMock()
        task.result = None
        db = _query_returning(task)
        with pytest.raises(HTTPException) as exc:
            task_crud.validating_task_results("task-1", "r", db)
        assert exc.value.status_code == 404
        assert exc.value.detail == "TaskResult not found"

    def test_generic_error_rolls_back_and_raises_500(self):
        task = MagicMock()
        task.result = MagicMock(history=[])
        db = _query_returning(task)
        db.commit.side_effect = RuntimeError("boom")
        with pytest.raises(HTTPException) as exc:
            task_crud.validating_task_results("task-1", "r", db)
        assert exc.value.status_code == 500
        db.rollback.assert_called_once()


class TestInterruptTask:
    async def test_success_cancels_and_publishes(self):
        task = MagicMock()
        task.status = TaskRunStatus.RUNNING
        task.conversation_id = 99
        task.agent_id = "agent-X"
        db = _query_returning(task)

        with patch.object(task_crud, "rabbitmq_instance") as rmq:
            ok = await task_crud.interrupt_task("task-1", db, reason="stop please")

        assert ok is True
        assert task.status == TaskRunStatus.CANCELED
        db.commit.assert_called_once()
        # Cancellation message published to the agent's queue.
        rmq.publish.assert_called_once()
        kwargs = rmq.publish.call_args.kwargs
        assert kwargs["queue_name"] == "agent-X"
        assert kwargs["priority_value"] == 10
        assert '"type": "cancel"' in kwargs["message"]
        assert '"reason": "stop please"' in kwargs["message"]

    async def test_default_reason_used_when_none(self):
        task = MagicMock()
        task.status = TaskRunStatus.RUNNING
        task.conversation_id = 1
        task.agent_id = "agent-Y"
        db = _query_returning(task)

        with patch.object(task_crud, "rabbitmq_instance") as rmq:
            await task_crud.interrupt_task("task-2", db)

        msg = rmq.publish.call_args.kwargs["message"]
        assert "User requested cancellation" in msg

    async def test_task_not_found_raises_404(self):
        db = _query_returning(None)
        with patch.object(task_crud, "rabbitmq_instance") as rmq:
            with pytest.raises(HTTPException) as exc:
                await task_crud.interrupt_task("missing", db)
        assert exc.value.status_code == 404
        rmq.publish.assert_not_called()

    async def test_already_terminal_raises_400(self):
        task = MagicMock()
        # Handler compares task.status against the enum *.value strings.
        task.status = TaskRunStatus.COMPLETED.value
        db = _query_returning(task)
        with patch.object(task_crud, "rabbitmq_instance") as rmq:
            with pytest.raises(HTTPException) as exc:
                await task_crud.interrupt_task("done", db)
        assert exc.value.status_code == 400
        assert "Cannot interrupt a completed task" in exc.value.detail
        rmq.publish.assert_not_called()

    async def test_generic_error_rolls_back_and_raises_500(self):
        task = MagicMock()
        task.status = TaskRunStatus.RUNNING
        db = _query_returning(task)
        db.commit.side_effect = RuntimeError("commit fail")
        with patch.object(task_crud, "rabbitmq_instance"):
            with pytest.raises(HTTPException) as exc:
                await task_crud.interrupt_task("task-3", db)
        assert exc.value.status_code == 500
        db.rollback.assert_called_once()

    async def test_the_cancel_signal_waits_for_the_broker_off_the_event_loop(self):
        task = MagicMock()
        task.status = TaskRunStatus.RUNNING
        task.conversation_id = 5
        task.agent_id = "agent-Z"
        db = _query_returning(task)
        release = threading.Event()
        waits: list[bool] = []

        async def another_request():
            release.set()

        with patch.object(task_crud, "rabbitmq_instance") as rmq:
            rmq.publish.side_effect = lambda **_kwargs: waits.append(release.wait(timeout=2))
            ok, _ = await asyncio.gather(task_crud.interrupt_task("task-4", db), another_request())

        assert ok is True
        assert waits == [True]
        assert rmq.publish.call_args.kwargs["queue_name"] == "agent-Z"


class TestGetAllTasksInternal:
    def test_no_filter_returns_all(self):
        db = MagicMock()
        sentinel = [MagicMock(), MagicMock()]
        db.query.return_value.all.return_value = sentinel
        out = task_crud._get_all_tasks_internal(db)
        assert out is sentinel
        db.query.return_value.filter.assert_not_called()

    def test_status_filter_applies_filter(self):
        db = MagicMock()
        filtered = [MagicMock()]
        db.query.return_value.filter.return_value.all.return_value = filtered
        out = task_crud._get_all_tasks_internal(
            db, status_filter=TaskRunStatus.RUNNING
        )
        assert out is filtered
        db.query.return_value.filter.assert_called_once()

    def test_status_list_filter_applies_filter(self):
        db = MagicMock()
        filtered = [MagicMock()]
        db.query.return_value.filter.return_value.all.return_value = filtered
        out = task_crud._get_all_tasks_internal(
            db, status_in=[TaskRunStatus.QUEUED, TaskRunStatus.RUNNING]
        )
        assert out is filtered
        db.query.return_value.filter.assert_called_once()

    def test_error_raises_500(self):
        db = MagicMock()
        db.query.side_effect = RuntimeError("db gone")
        with pytest.raises(HTTPException) as exc:
            task_crud._get_all_tasks_internal(db)
        assert exc.value.status_code == 500


class TestGetTasksInProgress:
    def test_success_delegates_with_queued_and_running_filter(self):
        running = [MagicMock()]
        with patch.object(
            task_crud, "_get_all_tasks_internal", return_value=running
        ) as inner:
            out = task_crud.get_tasks_in_progress(MagicMock())
        assert out is running
        assert inner.call_args.kwargs["status_in"] == [
            TaskRunStatus.QUEUED,
            TaskRunStatus.RUNNING,
        ]

    def test_inner_httpexception_is_rewrapped_as_500(self):
        # _get_all_tasks_internal raises HTTPException(500); the outer handler
        # catches the broad Exception and re-raises a fresh 500.
        with patch.object(
            task_crud,
            "_get_all_tasks_internal",
            side_effect=HTTPException(status_code=500, detail="inner"),
        ):
            with pytest.raises(HTTPException) as exc:
                task_crud.get_tasks_in_progress(MagicMock())
        assert exc.value.status_code == 500
        assert "Error retrieving tasks in progress" in exc.value.detail


# =========================================================================== #
# users.user_tool_functions
# =========================================================================== #


class TestGetAllUsers:
    def test_success_returns_users_and_touches_attrs(self):
        u1, u2 = MagicMock(), MagicMock()
        u1.username, u1.role = "alice", "user"
        u2.username, u2.role = "bob", "manager"
        db = MagicMock()
        db.query.return_value.all.return_value = [u1, u2]

        out = user_tool_functions.get_all_users(db)
        assert out == [u1, u2]

    def test_error_returns_empty_list(self):
        db = MagicMock()
        db.query.side_effect = RuntimeError("db error")
        assert user_tool_functions.get_all_users(db) == []


class TestGetUserDetails:
    def test_found_returns_triplet(self):
        user = MagicMock()
        user.username = "carol"
        user.role = "admin"
        db = _query_returning(user)
        result = user_tool_functions.get_user_details(42, db)
        assert result == (42, "carol", "admin")

    def test_not_found_returns_triple_none(self):
        db = _query_returning(None)
        assert user_tool_functions.get_user_details(42, db) == (None, None, None)

    def test_error_returns_quad_none(self):
        db = MagicMock()
        db.query.side_effect = RuntimeError("boom")
        assert user_tool_functions.get_user_details(42, db) == (
            None,
            None,
            None,
            None,
        )


class TestDeleteUser:
    def test_success_deletes_and_returns_message(self):
        user = MagicMock()
        user.username = "deleteme"
        db = _query_returning(user)
        out = user_tool_functions.delete_user(5, db)
        assert out == {"message": "User successfully deleted", "username": "deleteme"}
        db.delete.assert_called_once_with(user)
        db.commit.assert_called_once()

    def test_not_found_raises_404(self):
        db = _query_returning(None)
        with pytest.raises(HTTPException) as exc:
            user_tool_functions.delete_user(5, db)
        assert exc.value.status_code == 404

    def test_cannot_delete_main_admin_raises_403(self):
        admin = MagicMock()
        admin.username = "admin"  # Role.ADMIN.value
        db = _query_returning(admin)
        with pytest.raises(HTTPException) as exc:
            user_tool_functions.delete_user(1, db)
        assert exc.value.status_code == 403
        db.delete.assert_not_called()

    def test_error_rolls_back_and_raises_500(self):
        user = MagicMock()
        user.username = "victim"
        db = _query_returning(user)
        db.commit.side_effect = RuntimeError("commit fail")
        with pytest.raises(HTTPException) as exc:
            user_tool_functions.delete_user(5, db)
        assert exc.value.status_code == 500
        db.rollback.assert_called_once()


class TestModifyUserUsername:
    def _db_for_lookup_then_dup(self, target, dup):
        """db.query(...).filter(...).first() returns target then dup in order."""
        db = MagicMock()
        db.query.return_value.filter.return_value.first.side_effect = [target, dup]
        return db

    def test_success_changes_username(self):
        user = MagicMock()
        user.username = "old"
        db = self._db_for_lookup_then_dup(user, None)
        assert user_tool_functions.modify_user_username(5, "newname", db) is True
        assert user.username == "newname"
        db.commit.assert_called_once()

    def test_not_found_raises_404(self):
        db = _query_returning(None)
        with pytest.raises(HTTPException) as exc:
            user_tool_functions.modify_user_username(5, "x", db)
        assert exc.value.status_code == 404

    def test_duplicate_username_raises_409(self):
        user = MagicMock()
        user.username = "old"
        dup = MagicMock()
        db = self._db_for_lookup_then_dup(user, dup)
        with pytest.raises(HTTPException) as exc:
            user_tool_functions.modify_user_username(5, "taken", db)
        assert exc.value.status_code == 409
        db.commit.assert_not_called()

    def test_error_rolls_back_and_raises_500(self):
        user = MagicMock()
        user.username = "old"
        db = self._db_for_lookup_then_dup(user, None)
        db.commit.side_effect = RuntimeError("commit fail")
        with pytest.raises(HTTPException) as exc:
            user_tool_functions.modify_user_username(5, "newname", db)
        assert exc.value.status_code == 500
        db.rollback.assert_called_once()


# =========================================================================== #
# tasks.collaborative_task
# =========================================================================== #


def _subtask(description="t", agent_type="generic", **kw):
    return SubTask(description=description, agent_type=agent_type, **kw)


class TestCollaborativeTask:
    def test_get_ready_subtasks_returns_pending_with_deps_met(self):
        done = _subtask(status=TaskStatus.COMPLETED)
        ready = _subtask(depends_on=[done.id])
        blocked = _subtask(depends_on=["nonexistent"])
        ct = CollaborativeTask(sub_tasks=[done, ready, blocked])

        out = ct.get_ready_subtasks()
        ids = {t.id for t in out}
        assert ready.id in ids
        # Dependency unmet -> excluded; already-completed -> not pending -> excluded.
        assert blocked.id not in ids
        assert done.id not in ids

    def test_get_ready_subtasks_no_dependencies_always_ready(self):
        free = _subtask()
        ct = CollaborativeTask(sub_tasks=[free])
        assert ct.get_ready_subtasks() == [free]

    def test_update_subtask_status_with_result(self):
        st = _subtask()
        ct = CollaborativeTask(sub_tasks=[st])
        ct.update_subtask_status(st.id, TaskStatus.COMPLETED, result="done!")
        assert st.status == TaskStatus.COMPLETED
        assert st.result == "done!"

    def test_update_subtask_status_without_result_keeps_none(self):
        st = _subtask()
        ct = CollaborativeTask(sub_tasks=[st])
        ct.update_subtask_status(st.id, TaskStatus.IN_PROGRESS)
        assert st.status == TaskStatus.IN_PROGRESS
        assert st.result is None

    def test_update_subtask_status_unknown_id_is_noop(self):
        st = _subtask()
        ct = CollaborativeTask(sub_tasks=[st])
        ct.update_subtask_status("does-not-exist", TaskStatus.FAILED)
        assert st.status == TaskStatus.PENDING

    def test_is_complete_true_when_all_completed(self):
        ct = CollaborativeTask(
            sub_tasks=[
                _subtask(status=TaskStatus.COMPLETED),
                _subtask(status=TaskStatus.COMPLETED),
            ]
        )
        assert ct.is_complete() is True

    def test_is_complete_false_when_any_pending(self):
        ct = CollaborativeTask(
            sub_tasks=[
                _subtask(status=TaskStatus.COMPLETED),
                _subtask(status=TaskStatus.PENDING),
            ]
        )
        assert ct.is_complete() is False

    def test_aggregate_results_only_completed(self):
        ct = CollaborativeTask(
            sub_tasks=[
                _subtask(agent_type="writer", status=TaskStatus.COMPLETED,
                         result="A"),
                _subtask(agent_type="coder", status=TaskStatus.PENDING, result="B"),
                _subtask(agent_type="qa", status=TaskStatus.COMPLETED, result="C"),
            ]
        )
        agg = ct.aggregate_results()
        assert "Task (writer): A" in agg
        assert "Task (qa): C" in agg
        assert "coder" not in agg  # pending one excluded
        assert agg.count("\n\n") == 1  # exactly two blocks joined


# =========================================================================== #
# core.embedding_setup
# =========================================================================== #


class TestEmbedThreads:
    @pytest.fixture(autouse=True)
    def _no_thread_settings(self, monkeypatch):
        monkeypatch.delenv(embedding_setup.EMBED_THREADS_ENV, raising=False)
        monkeypatch.delenv(embedding_setup.SHARED_THREADS_ENV, raising=False)

    def test_onnxruntime_picks_the_threads_when_nothing_is_set(self):
        assert embedding_setup.embed_threads() is None

    def test_the_embedder_setting_wins(self, monkeypatch):
        monkeypatch.setenv(embedding_setup.EMBED_THREADS_ENV, "2")
        monkeypatch.setenv(embedding_setup.SHARED_THREADS_ENV, "1")

        assert embedding_setup.embed_threads() == 2

    def test_the_installer_thread_budget_applies_without_an_embedder_setting(self, monkeypatch):
        monkeypatch.setenv(embedding_setup.SHARED_THREADS_ENV, "1")

        assert embedding_setup.embed_threads() == 1

    @pytest.mark.parametrize("raw", ["0", "-2", "many"])
    def test_a_value_that_is_not_a_positive_count_is_ignored(self, monkeypatch, raw):
        monkeypatch.setenv(embedding_setup.EMBED_THREADS_ENV, raw)
        monkeypatch.setenv(embedding_setup.SHARED_THREADS_ENV, "3")

        assert embedding_setup.embed_threads() == 3


class TestLoadEmbedder:
    def test_load_embedder_uses_fastembed_on_cpu(self, monkeypatch):
        monkeypatch.setenv(embedding_setup.EMBED_THREADS_ENV, "1")
        fake_model = MagicMock(embedding_size=384)
        fake_fastembed = MagicMock()
        fake_fastembed.TextEmbedding.return_value = fake_model

        with patch.dict("sys.modules", {"fastembed": fake_fastembed}):
            model = embedding_setup._load_embedder()

        assert model is fake_model
        fake_fastembed.TextEmbedding.assert_called_once_with(
            "sentence-transformers/all-MiniLM-L6-v2", threads=1, cuda=False
        )

    def test_sentence_transformers_and_torch_are_not_needed(self):
        missing = {"sentence_transformers": None, "torch": None, "fastembed": MagicMock()}
        with patch.dict("sys.modules", missing):
            embedding_setup._load_embedder()


class TestEnsureEmbedderLoaded:
    def test_test_mode_short_circuits(self, monkeypatch):
        # conftest sets TEST_MODE=1; confirm we never touch the loader.
        monkeypatch.setenv("TEST_MODE", "1")
        with patch.object(embedding_setup, "_embedder", None), \
             patch.object(embedding_setup, "_load_embedder") as loader:
            embedding_setup._ensure_embedder_loaded()
            loader.assert_not_called()

    def test_loads_when_not_in_test_mode_and_unloaded(self, monkeypatch):
        monkeypatch.delenv("TEST_MODE", raising=False)
        fake_model = MagicMock()
        with patch.object(embedding_setup, "_embedder", None), \
             patch.object(embedding_setup, "_load_embedder",
                          return_value=fake_model) as loader:
            embedding_setup._ensure_embedder_loaded()
            loader.assert_called_once()
            assert embedding_setup._embedder is fake_model

    def test_already_loaded_skips_loader(self, monkeypatch):
        monkeypatch.delenv("TEST_MODE", raising=False)
        with patch.object(embedding_setup, "_embedder", MagicMock()), \
             patch.object(embedding_setup, "_load_embedder") as loader:
            embedding_setup._ensure_embedder_loaded()
            loader.assert_not_called()

    def test_double_checked_lock_skips_loader_when_set_under_lock(
        self, monkeypatch
    ):
        # Simulate the race: _embedder is None at the first check, but another
        # thread populated it by the time we acquire the lock. The second guard
        # inside the lock must short-circuit before calling the loader.
        monkeypatch.delenv("TEST_MODE", raising=False)

        class _LockSettingEmbedder:
            def __enter__(self_lock):
                embedding_setup._embedder = MagicMock()
                return self_lock

            def __exit__(self_lock, *exc):
                return False

        with patch.object(embedding_setup, "_embedder", None), \
             patch.object(embedding_setup, "_embedder_load_lock",
                          _LockSettingEmbedder()), \
             patch.object(embedding_setup, "_load_embedder") as loader:
            embedding_setup._ensure_embedder_loaded()
            loader.assert_not_called()


class TestPreloadBackgroundThread:
    def test_test_mode_does_not_spawn_thread(self, monkeypatch):
        monkeypatch.setenv("TEST_MODE", "1")
        with patch.object(embedding_setup.threading, "Thread") as thread_cls:
            embedding_setup.start_embedding_preload_background_thread()
            thread_cls.assert_not_called()

    def test_spawns_daemon_thread_when_not_test_mode(self, monkeypatch):
        monkeypatch.delenv("TEST_MODE", raising=False)
        with patch.object(embedding_setup.threading, "Thread") as thread_cls:
            embedding_setup.start_embedding_preload_background_thread()
            thread_cls.assert_called_once()
            assert thread_cls.call_args.kwargs["daemon"] is True
            thread_cls.return_value.start.assert_called_once()

    def test_worker_loads_and_warms_cache(self, monkeypatch):
        """Run the inner _worker synchronously to cover its body + cache warm."""
        monkeypatch.delenv("TEST_MODE", raising=False)
        captured = {}

        def fake_thread(target, name, daemon):
            captured["target"] = target
            return MagicMock()

        warm = MagicMock()
        fake_skill_cache = MagicMock(warm_skill_cache=warm)
        router_warm = MagicMock()
        fake_router = MagicMock(warm_router_examples=router_warm)

        with patch.object(embedding_setup.threading, "Thread",
                          side_effect=fake_thread), \
             patch.object(embedding_setup, "_ensure_embedder_loaded") as ensure, \
             patch.dict(
                 "sys.modules",
                 {"core.skill_cache": fake_skill_cache, "tasks.router": fake_router},
             ):
            embedding_setup.start_embedding_preload_background_thread()
            # Invoke the captured worker as the thread would have.
            captured["target"]()

        ensure.assert_called_once()
        warm.assert_called_once()
        router_warm.assert_called_once()

    def test_worker_swallows_router_examples_warm_exception(self, monkeypatch):
        monkeypatch.delenv("TEST_MODE", raising=False)
        captured = {}

        def fake_thread(target, name, daemon):
            captured["target"] = target
            return MagicMock()

        skill_warm = MagicMock()
        failing_router = MagicMock()
        failing_router.warm_router_examples.side_effect = RuntimeError("examples failed")

        with patch.object(embedding_setup.threading, "Thread", side_effect=fake_thread), \
             patch.object(embedding_setup, "_ensure_embedder_loaded"), \
             patch.dict(
                 "sys.modules",
                 {
                     "core.skill_cache": MagicMock(warm_skill_cache=skill_warm),
                     "tasks.router": failing_router,
                 },
             ):
            embedding_setup.start_embedding_preload_background_thread()
            captured["target"]()

        skill_warm.assert_called_once()
        failing_router.warm_router_examples.assert_called_once()

    def test_worker_swallows_loader_exception(self, monkeypatch):
        monkeypatch.delenv("TEST_MODE", raising=False)
        captured = {}

        def fake_thread(target, name, daemon):
            captured["target"] = target
            return MagicMock()

        with patch.object(embedding_setup.threading, "Thread",
                          side_effect=fake_thread), \
             patch.object(embedding_setup, "_ensure_embedder_loaded",
                          side_effect=RuntimeError("load failed")):
            embedding_setup.start_embedding_preload_background_thread()
            # Worker must not propagate the exception.
            captured["target"]()

    def test_worker_swallows_cache_warm_exception(self, monkeypatch):
        monkeypatch.delenv("TEST_MODE", raising=False)
        captured = {}

        def fake_thread(target, name, daemon):
            captured["target"] = target
            return MagicMock()

        boom_cache = MagicMock()
        boom_cache.warm_skill_cache.side_effect = RuntimeError("warm failed")

        with patch.object(embedding_setup.threading, "Thread",
                          side_effect=fake_thread), \
             patch.object(embedding_setup, "_ensure_embedder_loaded"), \
             patch.dict(
                 "sys.modules", {"core.skill_cache": boom_cache, "tasks.router": MagicMock()}
             ):
            embedding_setup.start_embedding_preload_background_thread()
            captured["target"]()  # inner warm raises, outer try swallows


class TestEmbedTexts:
    def test_embed_texts_returns_float32_matrix(self):
        fake_model = MagicMock()
        fake_model.embed.return_value = iter(
            [np.array([1.0, 2.0]), np.array([3.0, 4.0])]
        )
        with patch.object(embedding_setup, "_embedder", fake_model), \
             patch.object(embedding_setup, "_ensure_embedder_loaded"):
            out = embedding_setup.embed_texts(["a", "b"])
        assert out.dtype == np.float32
        assert out.shape == (2, 2)
        fake_model.embed.assert_called_once_with(["a", "b"])

    def test_embed_texts_of_nothing_is_an_empty_matrix_of_the_model_width(self):
        fake_model = MagicMock(embedding_size=384)
        fake_model.embed.return_value = iter([])
        with patch.object(embedding_setup, "_embedder", fake_model), \
             patch.object(embedding_setup, "_ensure_embedder_loaded"):
            out = embedding_setup.embed_texts([])
        assert out.shape == (0, 384)
        assert out.dtype == np.float32

    def test_embed_texts_raises_when_model_not_loaded(self):
        with patch.object(embedding_setup, "_embedder", None), \
             patch.object(embedding_setup, "_ensure_embedder_loaded"):
            with pytest.raises(RuntimeError, match="Embedding model is not loaded"):
                embedding_setup.embed_texts(["x"])

    def test_embed_text_returns_single_vector(self):
        fake_model = MagicMock()
        fake_model.embed.return_value = iter([np.array([5.0, 6.0, 7.0])])
        with patch.object(embedding_setup, "_embedder", fake_model), \
             patch.object(embedding_setup, "_ensure_embedder_loaded"):
            vec = embedding_setup.embed_text("hello")
        assert vec.shape == (3,)
        assert vec.dtype == np.float32
        np.testing.assert_array_equal(vec, np.array([5.0, 6.0, 7.0], dtype=np.float32))


# =========================================================================== #
# alembic_helper
# =========================================================================== #


class TestRunCommand:
    def test_success_returns_true(self):
        with patch.object(alembic_helper.subprocess, "run") as run:
            run.return_value = MagicMock(returncode=0)
            assert alembic_helper.run_command("alembic current", "desc") is True
        run.assert_called_once()
        # Runs inside the db/ working directory via the shell.
        assert run.call_args.kwargs["cwd"] == "db"
        assert run.call_args.kwargs["shell"] is True

    def test_nonzero_returncode_returns_false(self):
        with patch.object(alembic_helper.subprocess, "run") as run:
            run.return_value = MagicMock(returncode=1)
            assert alembic_helper.run_command("alembic bogus") is False

    def test_subprocess_exception_returns_false(self):
        with patch.object(alembic_helper.subprocess, "run",
                          side_effect=OSError("no alembic")):
            assert alembic_helper.run_command("alembic current", "d") is False


class TestAlembicMain:
    def _run_main(self, argv, monkeypatch):
        """Invoke main() with patched argv + run_command; return the mock."""
        monkeypatch.setattr(alembic_helper.sys, "argv", argv)
        with patch.object(alembic_helper, "run_command",
                          return_value=True) as run:
            alembic_helper.main()
        return run

    def test_no_args_prints_help_and_exits_1(self, monkeypatch):
        monkeypatch.setattr(alembic_helper.sys, "argv", ["alembic_helper.py"])
        with patch.object(alembic_helper, "run_command") as run:
            with pytest.raises(SystemExit) as exc:
                alembic_helper.main()
        assert exc.value.code == 1
        run.assert_not_called()

    @pytest.mark.parametrize(
        "command, expected_cmd",
        [
            ("status", "alembic current"),
            ("history", "alembic history"),
            ("upgrade", "alembic upgrade head"),
            ("downgrade", "alembic downgrade base"),
            ("rollback-1", "alembic downgrade -1"),
            ("current", "alembic current"),
        ],
    )
    def test_simple_commands_dispatch(self, command, expected_cmd, monkeypatch):
        run = self._run_main(["alembic_helper.py", command], monkeypatch)
        called_cmds = [c.args[0] for c in run.call_args_list]
        assert expected_cmd in called_cmds

    def test_command_is_case_insensitive(self, monkeypatch):
        run = self._run_main(["alembic_helper.py", "STATUS"], monkeypatch)
        assert run.call_args.args[0] == "alembic current"

    def test_create_with_description_builds_autogenerate(self, monkeypatch):
        run = self._run_main(
            ["alembic_helper.py", "create", "Add", "email", "column"], monkeypatch
        )
        cmd = run.call_args.args[0]
        assert "alembic revision --autogenerate" in cmd
        assert 'Add email column' in cmd

    def test_create_without_description_exits_1(self, monkeypatch):
        monkeypatch.setattr(alembic_helper.sys, "argv", ["alembic_helper.py", "create"])
        with patch.object(alembic_helper, "run_command") as run:
            with pytest.raises(SystemExit) as exc:
                alembic_helper.main()
        assert exc.value.code == 1
        run.assert_not_called()

    def test_test_command_runs_full_cycle(self, monkeypatch):
        run = self._run_main(["alembic_helper.py", "test"], monkeypatch)
        called_cmds = [c.args[0] for c in run.call_args_list]
        # The cycle drives downgrade-to-base then upgrade-to-head plus status checks.
        assert "alembic downgrade base" in called_cmds
        assert "alembic upgrade head" in called_cmds
        assert called_cmds.count("alembic current") >= 2

    def test_unknown_command_exits_1(self, monkeypatch):
        monkeypatch.setattr(
            alembic_helper.sys, "argv", ["alembic_helper.py", "frobnicate"]
        )
        with patch.object(alembic_helper, "run_command") as run:
            with pytest.raises(SystemExit) as exc:
                alembic_helper.main()
        assert exc.value.code == 1
        run.assert_not_called()
