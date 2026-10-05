from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e4b8c1d2f6a9"
down_revision: Union[str, Sequence[str], None] = "d7a3f5c9e1b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if op.get_context().dialect.name == "postgresql":
        with op.get_context().autocommit_block():
            op.execute("ALTER TYPE taskstatus ADD VALUE IF NOT EXISTS 'queued'")
    op.add_column("tasks", sa.Column("owner_username", sa.String(), nullable=True))
    op.create_index("ix_tasks_owner_username", "tasks", ["owner_username"], unique=False)
    op.execute(
        "UPDATE tasks SET owner_username = ("
        "SELECT conversations.owner_username FROM conversations "
        "WHERE conversations.id = tasks.conversation_id"
        ") WHERE conversation_id IS NOT NULL"
    )


def downgrade() -> None:
    op.drop_index("ix_tasks_owner_username", table_name="tasks")
    op.drop_column("tasks", "owner_username")
