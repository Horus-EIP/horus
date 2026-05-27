"""add MANAGER value to agenttypes enum

Revision ID: b5d2e1f3a9c7
Revises: a4c1f2b3e7d8
Create Date: 2026-05-14 18:00:00.000000

Adds the ``MANAGER`` value to the Postgres ``agenttypes`` enum so the
orchestrator can be represented as a first-class agent identity. The seed
creates a ``Manager`` row of this type; cyclic re-planning and per-step
review are then attributed to this identity in the chat UI.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "b5d2e1f3a9c7"
down_revision: Union[str, Sequence[str], None] = "a4c1f2b3e7d8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add MANAGER to the agenttypes enum.

    Postgres 12+ supports ``ALTER TYPE ... ADD VALUE`` in transactions, but
    the CI runner uses isolated migration steps so an explicit COMMIT before
    the DDL keeps older versions safe. ``IF NOT EXISTS`` is idempotent — the
    migration can rerun after a partial apply without erroring.
    """
    # Run outside the implicit transaction; ALTER TYPE ... ADD VALUE in
    # Postgres < 12 cannot run inside a transaction block.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE agenttypes ADD VALUE IF NOT EXISTS 'MANAGER'")


def downgrade() -> None:
    """No-op.

    Postgres does not support removing a value from an enum without
    rebuilding the type. Since no rows reference MANAGER until the seed runs,
    leaving the value in the enum is harmless on rollback.
    """
    pass
