from __future__ import annotations

from contextlib import ExitStack
from unittest.mock import MagicMock, patch

import pytest

from db import init_setup
from tasks.status import TaskStatus

LABELS_WITHOUT_QUEUED = [("pending",), ("running",), ("completed",), ("canceled",), ("failed",)]
ALL_LABELS = [(status.value,) for status in TaskStatus]


def _engine(labels, dialect="postgresql"):
    executed: list[str] = []
    connection = MagicMock(name="connection")
    connection.__enter__.return_value = connection
    connection.execution_options.return_value = connection

    def execute(statement, *_args, **_kwargs):
        sql = str(statement)
        executed.append(sql)
        return iter(labels) if "pg_enum" in sql else iter([])

    connection.execute.side_effect = execute
    engine = MagicMock(name="engine")
    engine.dialect.name = dialect
    engine.connect.return_value = connection
    return engine, executed, connection


def _alters(executed):
    return [sql for sql in executed if sql.startswith("ALTER TYPE")]


def _init_db(engine, tables):
    inspector = MagicMock()
    inspector.get_table_names.return_value = tables
    with ExitStack() as stack:
        stack.enter_context(patch.object(init_setup, "run_migrations", return_value=True))
        stack.enter_context(patch.object(init_setup, "engine", engine))
        stack.enter_context(patch("sqlalchemy.inspect", return_value=inspector))
        stack.enter_context(
            patch.object(init_setup, "create_critical_logs_table", return_value=True)
        )
        stack.enter_context(patch.object(init_setup, "SessionLocal", MagicMock()))
        stack.enter_context(patch("db.seed_agents.seed_manager_agent"))
        create_all = stack.enter_context(patch.object(init_setup.Base.metadata, "create_all"))
        stamp = stack.enter_context(patch.object(init_setup, "stamp_alembic_head"))
        init_setup.init_db()
    return create_all, stamp


def test_startup_adds_the_queued_status_a_create_all_schema_is_missing():
    engine, executed, _connection = _engine(LABELS_WITHOUT_QUEUED)

    _init_db(engine, ["users", "tasks"])

    assert "ALTER TYPE taskstatus ADD VALUE IF NOT EXISTS 'queued'" in executed


def test_the_enum_is_altered_outside_a_transaction():
    engine, executed, connection = _engine(LABELS_WITHOUT_QUEUED)

    assert init_setup.ensure_task_status_enum(engine) == ["queued"]

    connection.execution_options.assert_called_once_with(isolation_level="AUTOCOMMIT")
    assert _alters(executed) == ["ALTER TYPE taskstatus ADD VALUE IF NOT EXISTS 'queued'"]


def test_a_complete_enum_is_left_alone():
    engine, executed, _connection = _engine(ALL_LABELS)

    assert init_setup.ensure_task_status_enum(engine) == []
    assert _alters(executed) == []


def test_a_schema_without_the_native_enum_is_left_alone():
    engine, executed, _connection = _engine([])

    assert init_setup.ensure_task_status_enum(engine) == []
    assert _alters(executed) == []


def test_other_databases_are_not_queried():
    engine, executed, _connection = _engine(LABELS_WITHOUT_QUEUED, dialect="sqlite")

    assert init_setup.ensure_task_status_enum(engine) == []
    assert executed == []


def test_an_enum_check_error_does_not_stop_startup():
    engine, _executed, connection = _engine(LABELS_WITHOUT_QUEUED)
    connection.execute.side_effect = RuntimeError("permission denied for type taskstatus")

    _init_db(engine, ["users", "tasks"])


@pytest.mark.parametrize(
    ("tables", "stamped"),
    [(["alembic_version"], True), (["users", "tasks"], False)],
)
def test_a_schema_built_from_the_models_is_stamped_at_the_alembic_head(tables, stamped):
    engine, _executed, _connection = _engine(ALL_LABELS)

    create_all, stamp = _init_db(engine, tables)

    assert create_all.called is stamped
    assert stamp.called is stamped


def test_stamping_runs_alembic_from_the_migration_folder():
    completed = MagicMock(returncode=0, stderr="")
    with patch.object(init_setup.subprocess, "run", return_value=completed) as run:
        assert init_setup.stamp_alembic_head() is True

    command = run.call_args.args[0]
    assert command[-3:] == ["alembic", "stamp", "head"]
    assert run.call_args.kwargs["cwd"].endswith("db")


def test_a_failed_stamp_is_reported():
    failed = MagicMock(returncode=1, stderr="Can't locate revision")
    with patch.object(init_setup.subprocess, "run", return_value=failed):
        assert init_setup.stamp_alembic_head() is False
