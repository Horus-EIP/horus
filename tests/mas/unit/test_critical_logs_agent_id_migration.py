from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import Mock, patch

import sqlalchemy as sa

REPO = Path(__file__).resolve().parents[3]
MIGRATION_PATH = (
    REPO
    / "src"
    / "services"
    / "mas"
    / "db"
    / "alembic"
    / "versions"
    / "f8a03b219c7d_critical_logs_agent_id.py"
)
SPEC = importlib.util.spec_from_file_location("critical_logs_agent_id", MIGRATION_PATH)
assert SPEC and SPEC.loader
migration = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(migration)


def test_upgrade_adds_nullable_agent_id_column():
    inspector = Mock()
    inspector.get_columns.return_value = []
    with (
        patch.object(migration.op, "get_bind"),
        patch.object(migration.sa, "inspect", return_value=inspector),
        patch.object(migration.op, "add_column") as add_column,
    ):
        migration.upgrade()

    add_column.assert_called_once()
    table_name, column = add_column.call_args.args
    assert table_name == "critical_logs"
    assert isinstance(column, sa.Column)
    assert column.name == "agent_id"
    assert column.nullable is True


def test_downgrade_drops_agent_id_column():
    inspector = Mock()
    inspector.get_columns.return_value = [{"name": "agent_id"}]
    with (
        patch.object(migration.op, "get_bind"),
        patch.object(migration.sa, "inspect", return_value=inspector),
        patch.object(migration.op, "drop_column") as drop_column,
    ):
        migration.downgrade()

    drop_column.assert_called_once_with("critical_logs", "agent_id")


def test_upgrade_skips_column_already_created_by_fallback_schema():
    inspector = Mock()
    inspector.get_columns.return_value = [{"name": "agent_id"}]
    with (
        patch.object(migration.op, "get_bind"),
        patch.object(migration.sa, "inspect", return_value=inspector),
        patch.object(migration.op, "add_column") as add_column,
    ):
        migration.upgrade()

    add_column.assert_not_called()
