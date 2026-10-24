"""add active status to user accounts

Revision ID: a13c9e4b6d02
Revises: 8e48716efaad
Create Date: 2026-10-24

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a13c9e4b6d02"
down_revision: Union[str, Sequence[str], None] = "8e48716efaad"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.true(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "is_active")
