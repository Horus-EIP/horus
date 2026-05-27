"""add agent attribution columns to messages

Revision ID: c8e9d4f6b2a1
Revises: b5d2e1f3a9c7
Create Date: 2026-05-14 22:00:00.000000

Persists ``agent_id`` / ``agent_name`` / ``skill_used`` on each chat
message. Without these, the chat history endpoint can't tell which agent
produced an assistant turn, so reloading the page strips the Manager's
violet styling and the per-specialist attribution chips from every prior
message. All columns are nullable — user-role messages and pre-migration
rows simply leave them ``NULL``.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c8e9d4f6b2a1"
down_revision: Union[str, Sequence[str], None] = "b5d2e1f3a9c7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("messages", sa.Column("agent_id", sa.String(), nullable=True))
    op.add_column("messages", sa.Column("agent_name", sa.String(), nullable=True))
    op.add_column("messages", sa.Column("skill_used", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("messages", "skill_used")
    op.drop_column("messages", "agent_name")
    op.drop_column("messages", "agent_id")
