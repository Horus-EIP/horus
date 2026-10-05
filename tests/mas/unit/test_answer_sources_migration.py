from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import Column, Integer, MetaData, String, Table, create_engine, inspect

ALEMBIC_DIR = Path(__file__).resolve().parents[3] / "src" / "services" / "mas" / "db" / "alembic"
REVISION = "c3f9a7e1d5b2"
PREVIOUS_HEAD = "a9d4e2c7b1f3"


def _load_migration():
    (path,) = (ALEMBIC_DIR / "versions").glob(f"{REVISION}_*.py")
    spec = importlib.util.spec_from_file_location(f"migration_{REVISION}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def answers_db():
    engine = create_engine("sqlite://")
    metadata = MetaData()
    Table("task_results", metadata, Column("id", String, primary_key=True))
    Table("messages", metadata, Column("id", Integer, primary_key=True))
    metadata.create_all(engine)
    yield engine
    engine.dispose()


def _run(engine, step):
    with engine.begin() as conn, Operations.context(MigrationContext.configure(conn)):
        step()


def _columns(engine, table):
    return {column["name"] for column in inspect(engine).get_columns(table)}


def test_sources_migration_follows_the_claims_migration_and_is_the_single_head():
    script = ScriptDirectory(str(ALEMBIC_DIR))

    assert script.get_revision(REVISION).down_revision == PREVIOUS_HEAD
    assert script.get_heads() == [REVISION]


def test_upgrade_adds_the_sources_of_results_and_messages(answers_db):
    _run(answers_db, _load_migration().upgrade)

    assert "sources" in _columns(answers_db, "task_results")
    assert "sources" in _columns(answers_db, "messages")


def test_downgrade_removes_them(answers_db):
    migration = _load_migration()
    _run(answers_db, migration.upgrade)

    _run(answers_db, migration.downgrade)

    assert _columns(answers_db, "task_results") == {"id"}
    assert _columns(answers_db, "messages") == {"id"}
