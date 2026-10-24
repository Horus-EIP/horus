"""add consumed_reset_nonces table for license rollback recovery

Revision ID: 8e48716efaad
Revises: f2a9c6d4b1e8
Create Date: 2026-10-24 13:21:16.843297

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8e48716efaad'
down_revision: Union[str, Sequence[str], None] = 'f2a9c6d4b1e8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'consumed_reset_nonces',
        sa.Column('nonce', sa.String(length=36), nullable=False),
        sa.Column('consumed_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('nonce')
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('consumed_reset_nonces')