"""seed_admin_user

Revision ID: f6a793898052
Revises: 3f524312486e
Create Date: 2025-12-01 16:11:19.748567

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f6a793898052"
down_revision: Union[str, Sequence[str], None] = "3f524312486e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
