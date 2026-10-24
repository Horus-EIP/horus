"""Add persistent installation site identity."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f2a9c6d4b1e8"
down_revision: Union[str, Sequence[str], None] = "f1c4a8b2d6e0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "global_config",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("site_id", sa.String(length=36), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("id = 1", name="ck_global_config_singleton"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("site_id"),
    )


def downgrade() -> None:
    op.drop_table("global_config")
