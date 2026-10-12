from __future__ import annotations

import importlib.util
from datetime import datetime
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import Column, DateTime, MetaData, String, Table, create_engine, inspect, text

ALEMBIC_DIR = Path(__file__).resolve().parents[3] / "src" / "services" / "mas" / "db" / "alembic"
REVISION = "d7a3f5c9e1b4"
PREVIOUS_HEAD = "c8e9d4f6b2a1"
UPDATED_AT = datetime(2026, 10, 1, 9, 30, 0)


def _load_migration():
    (path,) = (ALEMBIC_DIR / "versions").glob(f"{REVISION}_*.py")
    spec = importlib.util.spec_from_file_location(f"migration_{REVISION}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def legacy_tasks_db():
    engine = create_engine("sqlite://")
    metadata = MetaData()
    tasks = Table(
        "tasks",
        metadata,
        Column("id", String, primary_key=True),
        Column("status", String),
        Column("updated_at", DateTime),
    )
    metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(
            tasks.insert(),
            [
                {"id": "done", "status": "completed", "updated_at": UPDATED_AT},
                {"id": "stopped", "status": "canceled", "updated_at": UPDATED_AT},
                {"id": "broken", "status": "failed", "updated_at": UPDATED_AT},
                {"id": "busy", "status": "running", "updated_at": UPDATED_AT},
            ],
        )
    yield engine
    engine.dispose()


def _run(engine, step):
    with engine.begin() as conn, Operations.context(MigrationContext.configure(conn)):
        step()


def _task_columns(engine):
    return {column["name"] for column in inspect(engine).get_columns("tasks")}


def test_task_timing_migration_follows_previous_head_and_stays_single_head():
    script = ScriptDirectory(str(ALEMBIC_DIR))

    assert script.get_revision(REVISION).down_revision == PREVIOUS_HEAD
    assert len(script.get_heads()) == 1


def test_upgrade_adds_skills_and_completion_columns(legacy_tasks_db):
    _run(legacy_tasks_db, _load_migration().upgrade)

    assert {"skills_required", "completed_at"} <= _task_columns(legacy_tasks_db)


def test_upgrade_backfills_completion_time_of_finished_tasks_only(legacy_tasks_db):
    _run(legacy_tasks_db, _load_migration().upgrade)

    with legacy_tasks_db.connect() as conn:
        rows = dict(conn.execute(text("SELECT id, completed_at FROM tasks")).all())
    assert rows["busy"] is None
    for task_id in ("done", "stopped", "broken"):
        assert datetime.fromisoformat(rows[task_id]) == UPDATED_AT


def test_downgrade_removes_skills_and_completion_columns(legacy_tasks_db):
    migration = _load_migration()
    _run(legacy_tasks_db, migration.upgrade)

    _run(legacy_tasks_db, migration.downgrade)

    assert _task_columns(legacy_tasks_db) == {"id", "status", "updated_at"}
