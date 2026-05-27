"""tasks.conversation_id nullable for standalone tasks

Revision ID: a4c1f2b3e7d8
Revises: 673e69dd4df7
Create Date: 2026-05-13 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a4c1f2b3e7d8"
down_revision: Union[str, Sequence[str], None] = "673e69dd4df7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "tasks",
        "conversation_id",
        existing_type=sa.Integer(),
        nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "tasks",
        "conversation_id",
        existing_type=sa.Integer(),
        nullable=False,
    )
