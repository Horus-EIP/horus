from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d7a3f5c9e1b4"
down_revision: Union[str, Sequence[str], None] = "c8e9d4f6b2a1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("tasks", sa.Column("skills_required", sa.JSON(), nullable=True))
    op.add_column(
        "tasks", sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.execute(
        "UPDATE tasks SET completed_at = updated_at "
        "WHERE status IN ('completed', 'canceled', 'failed')"
    )


def downgrade() -> None:
    op.drop_column("tasks", "completed_at")
    op.drop_column("tasks", "skills_required")
