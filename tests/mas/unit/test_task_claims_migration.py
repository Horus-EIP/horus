from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import Column, Integer, MetaData, String, Table, create_engine, inspect

ALEMBIC_DIR = Path(__file__).resolve().parents[3] / "src" / "services" / "mas" / "db" / "alembic"
REVISION = "a9d4e2c7b1f3"
PREVIOUS_HEAD = "e4b8c1d2f6a9"


def _load_migration():
    (path,) = (ALEMBIC_DIR / "versions").glob(f"{REVISION}_*.py")
    spec = importlib.util.spec_from_file_location(f"migration_{REVISION}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def tasks_db():
    engine = create_engine("sqlite://")
    metadata = MetaData()
    Table(
        "tasks",
        metadata,
        Column("id", String, primary_key=True),
        Column("conversation_id", Integer),
    )
    metadata.create_all(engine)
    yield engine
    engine.dispose()


def _run(engine, step):
    with engine.begin() as conn, Operations.context(MigrationContext.configure(conn)):
        step()


def _columns(engine):
    return {column["name"] for column in inspect(engine).get_columns("tasks")}


def test_claims_migration_follows_the_queue_migration_and_is_the_single_head():
    script = ScriptDirectory(str(ALEMBIC_DIR))

    assert script.get_revision(REVISION).down_revision == PREVIOUS_HEAD
    assert script.get_heads() == [REVISION]


def test_upgrade_adds_the_worker_claim_columns(tasks_db):
    _run(tasks_db, _load_migration().upgrade)

    assert {"claimed_by", "claim_run", "started_at"} <= _columns(tasks_db)
    indexes = {index["name"] for index in inspect(tasks_db).get_indexes("tasks")}
    assert "ix_tasks_claimed_by" in indexes


def test_downgrade_removes_them(tasks_db):
    migration = _load_migration()
    _run(tasks_db, migration.upgrade)

    _run(tasks_db, migration.downgrade)

    assert _columns(tasks_db) == {"id", "conversation_id"}
