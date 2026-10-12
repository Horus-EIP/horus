from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a9d4e2c7b1f3"
down_revision: Union[str, Sequence[str], None] = "e4b8c1d2f6a9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("tasks", sa.Column("claimed_by", sa.String(), nullable=True))
    op.add_column("tasks", sa.Column("claim_run", sa.String(), nullable=True))
    op.add_column("tasks", sa.Column("started_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_tasks_claimed_by", "tasks", ["claimed_by"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_tasks_claimed_by", table_name="tasks")
    op.drop_column("tasks", "started_at")
    op.drop_column("tasks", "claim_run")
    op.drop_column("tasks", "claimed_by")
