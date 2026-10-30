from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import Column, Integer, MetaData, String, Table, create_engine, inspect

ALEMBIC_DIR = Path(__file__).resolve().parents[3] / "src" / "services" / "mas" / "db" / "alembic"
REVISION = "d2e6b8f4a1c9"
PREVIOUS_HEAD = "c3f9a7e1d5b2"
CURRENT_HEAD = "f8a03b219c7d"


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


def test_ai_provider_migration_follows_sources_and_the_chain_has_one_head():
    script = ScriptDirectory(str(ALEMBIC_DIR))

    assert script.get_revision(REVISION).down_revision == PREVIOUS_HEAD
    assert script.get_heads() == [CURRENT_HEAD]
    assert script.get_revision(CURRENT_HEAD).down_revision == REVISION


def test_upgrade_adds_the_ai_provider_of_results_and_messages(answers_db):
    _run(answers_db, _load_migration().upgrade)

    assert "ai_provider" in _columns(answers_db, "task_results")
    assert "ai_provider" in _columns(answers_db, "messages")


def test_downgrade_removes_them(answers_db):
    migration = _load_migration()
    _run(answers_db, migration.upgrade)

    _run(answers_db, migration.downgrade)

    assert _columns(answers_db, "task_results") == {"id"}
    assert _columns(answers_db, "messages") == {"id"}
