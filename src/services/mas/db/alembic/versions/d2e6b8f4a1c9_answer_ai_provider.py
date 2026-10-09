from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d2e6b8f4a1c9"
down_revision: Union[str, Sequence[str], None] = "c3f9a7e1d5b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("task_results", sa.Column("ai_provider", sa.String(), nullable=True))
    op.add_column("messages", sa.Column("ai_provider", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("messages", "ai_provider")
    op.drop_column("task_results", "ai_provider")
