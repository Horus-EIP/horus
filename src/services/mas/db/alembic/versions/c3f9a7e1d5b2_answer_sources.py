from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c3f9a7e1d5b2"
down_revision: Union[str, Sequence[str], None] = "a9d4e2c7b1f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("task_results", sa.Column("sources", sa.JSON(), nullable=True))
    op.add_column("messages", sa.Column("sources", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("messages", "sources")
    op.drop_column("task_results", "sources")
