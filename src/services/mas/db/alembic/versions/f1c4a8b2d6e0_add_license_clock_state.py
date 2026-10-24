"""Add singleton licence clock high-water mark."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f1c4a8b2d6e0"
down_revision: Union[str, Sequence[str], None] = "d2e6b8f4a1c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "license_clock_state",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("last_seen_clock", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("id = 1", name="ck_license_clock_state_singleton"),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("license_clock_state")
