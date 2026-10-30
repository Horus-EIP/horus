"""add agent_id to critical_logs

Revision ID: f8a03b219c7d
Revises: d2e6b8f4a1c9
Create Date: 2026-10-26
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f8a03b219c7d"
down_revision: Union[str, Sequence[str], None] = "d2e6b8f4a1c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    columns = {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("critical_logs")
    }
    if "agent_id" not in columns:
        op.add_column(
            "critical_logs",
            sa.Column("agent_id", sa.Text(), nullable=True),
        )


def downgrade() -> None:
    columns = {
        column["name"]
        for column in sa.inspect(op.get_bind()).get_columns("critical_logs")
    }
    if "agent_id" in columns:
        op.drop_column("critical_logs", "agent_id")
