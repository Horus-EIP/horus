"""initial: create all tables with proper foreign keys and indexes

Revision ID: 3f524312486e
Revises: 
Create Date: 2025-11-18 22:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "3f524312486e"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema - create all application tables."""

    # Create users table (base table, no dependencies)
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=True),
        sa.Column("username", sa.String(), nullable=False, unique=True),
        sa.Column("hashed_password", sa.String(), nullable=False),
        sa.Column("role", sa.String(), nullable=False, server_default="user"),
        sa.PrimaryKeyConstraint("id", name="users_pkey"),
        sa.UniqueConstraint("username", name="users_username_key"),
    )
    op.create_index("ix_users_id", "users", ["id"], unique=False)
    op.create_index("ix_users_username", "users", ["username"], unique=True)

    # Create agents table (no foreign key dependencies)
    op.create_table(
        "agents",
        sa.Column("id", sa.String(), nullable=False, primary_key=True),
        sa.Column("name", sa.String(), nullable=False, unique=True),
        sa.Column(
            "skills",
            postgresql.JSON(astext_type=sa.Text()),
            nullable=False,
            server_default="[]",
        ),
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column(
            "last_heartbeat",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="agents_pkey"),
        sa.UniqueConstraint("name", name="agents_name_key"),
    )
    # Indexes on frequently queried fields
    op.create_index("ix_agents_name", "agents", ["name"], unique=True)
    op.create_index(
        "ix_agents_last_heartbeat", "agents", ["last_heartbeat"], unique=False
    )
    op.create_index("ix_agents_status", "agents", ["status"], unique=False)

    # Create conversations table (depends on users)
    op.create_table(
        "conversations",
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=True),
        sa.Column("owner_username", sa.String(), nullable=True),
        sa.Column("name", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "modified_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["owner_username"],
            ["users.username"],
            name="conversations_owner_username_fkey",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="conversations_pkey"),
    )
    op.create_index("ix_conversations_id", "conversations", ["id"], unique=False)
    op.create_index(
        "ix_conversations_owner_username",
        "conversations",
        ["owner_username"],
        unique=False,
    )

    # Create messages table (depends on conversations)
    op.create_table(
        "messages",
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=True),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("content", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("conversation_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            name="messages_conversation_id_fkey",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="messages_pkey"),
    )
    op.create_index("ix_messages_id", "messages", ["id"], unique=False)
    op.create_index(
        "ix_messages_conversation_id", "messages", ["conversation_id"], unique=False
    )

    # Create tasks table (depends on conversations and agents)
    op.create_table(
        "tasks",
        sa.Column("id", sa.String(), nullable=False, primary_key=True),
        sa.Column("conversation_id", sa.Integer(), nullable=False),
        sa.Column("parent_task_id", sa.String(), nullable=True),
        sa.Column("agent_id", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("query", sa.String(), nullable=False),
        sa.Column("order", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.id"],
            name="tasks_conversation_id_fkey",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["parent_task_id"], ["tasks.id"], name="tasks_parent_task_id_fkey"
        ),
        sa.PrimaryKeyConstraint("id", name="tasks_pkey"),
    )
    # Indexes on frequently queried fields
    op.create_index(
        "ix_tasks_conversation_id", "tasks", ["conversation_id"], unique=False
    )
    op.create_index("ix_tasks_agent_id", "tasks", ["agent_id"], unique=False)
    op.create_index("ix_tasks_status", "tasks", ["status"], unique=False)
    op.create_index(
        "ix_tasks_parent_task_id", "tasks", ["parent_task_id"], unique=False
    )

    # Create task_results table (depends on tasks)
    op.create_table(
        "task_results",
        sa.Column("id", sa.String(), nullable=False, primary_key=True),
        sa.Column("task_id", sa.String(), nullable=False, unique=True),
        sa.Column("result_data", postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column("history", postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "future_actions", postgresql.JSON(astext_type=sa.Text()), nullable=True
        ),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["tasks.id"],
            name="task_results_task_id_fkey",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="task_results_pkey"),
        sa.UniqueConstraint("task_id", name="task_results_task_id_key"),
    )
    op.create_index("ix_task_results_task_id", "task_results", ["task_id"], unique=True)

    # Create critical_logs table (no dependencies)
    op.create_table(
        "critical_logs",
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=True),
        sa.Column(
            "timestamp",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("level", sa.String(length=20), nullable=False),
        sa.Column("category", sa.String(length=20), nullable=False),
        sa.Column("component", sa.String(length=50), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("operation", sa.String(length=100), nullable=False),
        sa.Column("details", sa.Text(), nullable=True),
        sa.Column("ip_address", sa.String(length=45), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="critical_logs_pkey"),
    )
    # Indexes for performance
    op.create_index(
        "idx_critical_logs_timestamp", "critical_logs", ["timestamp"], unique=False
    )
    op.create_index(
        "idx_critical_logs_category", "critical_logs", ["category"], unique=False
    )
    op.create_index(
        "idx_critical_logs_user", "critical_logs", ["user_id"], unique=False
    )
    op.create_index(
        "idx_critical_logs_component", "critical_logs", ["component"], unique=False
    )
    op.create_index(
        "idx_critical_logs_operation", "critical_logs", ["operation"], unique=False
    )


def downgrade() -> None:
    """Downgrade schema - drop all application tables in reverse dependency order."""

    # Drop in reverse dependency order
    op.drop_index("idx_critical_logs_operation", table_name="critical_logs")
    op.drop_index("idx_critical_logs_component", table_name="critical_logs")
    op.drop_index("idx_critical_logs_user", table_name="critical_logs")
    op.drop_index("idx_critical_logs_category", table_name="critical_logs")
    op.drop_index("idx_critical_logs_timestamp", table_name="critical_logs")
    op.drop_table("critical_logs")

    op.drop_index("ix_task_results_task_id", table_name="task_results")
    op.drop_table("task_results")

    op.drop_index("ix_tasks_parent_task_id", table_name="tasks")
    op.drop_index("ix_tasks_status", table_name="tasks")
    op.drop_index("ix_tasks_agent_id", table_name="tasks")
    op.drop_index("ix_tasks_conversation_id", table_name="tasks")
    op.drop_table("tasks")

    op.drop_index("ix_messages_conversation_id", table_name="messages")
    op.drop_index("ix_messages_id", table_name="messages")
    op.drop_table("messages")

    op.drop_index("ix_conversations_owner_username", table_name="conversations")
    op.drop_index("ix_conversations_id", table_name="conversations")
    op.drop_table("conversations")

    op.drop_index("ix_agents_status", table_name="agents")
    op.drop_index("ix_agents_last_heartbeat", table_name="agents")
    op.drop_index("ix_agents_name", table_name="agents")
    op.drop_table("agents")

    op.drop_index("ix_users_username", table_name="users")
    op.drop_index("ix_users_id", table_name="users")
    op.drop_table("users")
