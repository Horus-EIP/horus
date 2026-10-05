from __future__ import annotations

import importlib.util
import io
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import Column, Integer, MetaData, String, Table, create_engine, inspect, text

ALEMBIC_DIR = Path(__file__).resolve().parents[3] / "src" / "services" / "mas" / "db" / "alembic"
REVISION = "e4b8c1d2f6a9"
PREVIOUS_HEAD = "d7a3f5c9e1b4"


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
    conversations = Table(
        "conversations",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("owner_username", String),
    )
    tasks = Table(
        "tasks",
        metadata,
        Column("id", String, primary_key=True),
        Column("conversation_id", Integer),
    )
    metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(conversations.insert(), [{"id": 7, "owner_username": "alice"}])
        conn.execute(
            tasks.insert(),
            [
                {"id": "chat-task", "conversation_id": 7},
                {"id": "standalone", "conversation_id": None},
            ],
        )
    yield engine
    engine.dispose()


def _run(engine, step):
    with engine.begin() as conn, Operations.context(MigrationContext.configure(conn)):
        step()


def test_queue_migration_follows_previous_head_and_stays_single_head():
    script = ScriptDirectory(str(ALEMBIC_DIR))

    assert script.get_revision(REVISION).down_revision == PREVIOUS_HEAD
    assert len(script.get_heads()) == 1
    assert REVISION in {revision.revision for revision in script.walk_revisions()}


def test_upgrade_adds_the_queued_status_to_the_postgres_enum():
    buffer = io.StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql", opts={"as_sql": True, "output_buffer": buffer}
    )

    with Operations.context(context):
        _load_migration().upgrade()

    sql = buffer.getvalue()
    assert "ALTER TYPE taskstatus ADD VALUE IF NOT EXISTS 'queued'" in sql
    assert "ADD COLUMN owner_username" in sql


def test_upgrade_gives_chat_tasks_their_conversation_owner(legacy_tasks_db):
    _run(legacy_tasks_db, _load_migration().upgrade)

    with legacy_tasks_db.connect() as conn:
        owners = dict(conn.execute(text("SELECT id, owner_username FROM tasks")).all())
    assert owners == {"chat-task": "alice", "standalone": None}


def test_downgrade_removes_the_owner_column(legacy_tasks_db):
    migration = _load_migration()
    _run(legacy_tasks_db, migration.upgrade)

    _run(legacy_tasks_db, migration.downgrade)

    columns = {column["name"] for column in inspect(legacy_tasks_db).get_columns("tasks")}
    assert columns == {"id", "conversation_id"}
