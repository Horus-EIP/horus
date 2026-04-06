"""
SQLAlchemy Database Models

This module defines the database schema for the MAS application using SQLAlchemy ORM.
The models represent the core entities of the multi-agent system and their relationships.

Database Schema Overview:
- Users: System users with authentication and role-based access
- Conversations: Chat conversations with ownership and metadata
- Messages: Individual messages within conversations
- CriticalLogs: System audit logs for security and monitoring

Key Features:
- Automatic timestamp management with timezone support
- Foreign key constraints with proper cascade behavior
- Database indexes for query optimization
- Event listeners for automatic CRUD operation logging
- Proper relationship configuration with lazy loading

Table Relationships:
- Users 1:N Conversations (owner relationship)
- Conversations 1:N Messages (conversation history)
- All models include audit event listeners for security logging

Security Considerations:
- Passwords are stored hashed, never in plaintext
- Foreign key constraints ensure data integrity
- Cascade deletes properly handle orphaned records
- Audit logging tracks all data modifications
"""

import secrets
import uuid
from enum import Enum
from typing import Dict, List, Set

from sqlalchemy import JSON, Column, DateTime
from sqlalchemy import Enum as SQLEnum
from sqlalchemy import ForeignKey, Index, Integer, String, Text, event
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from auth.permissions import Role
from core.logger import get_logger, log_db_operation
from db.database import Base
from tasks.status import TaskStatus

logger = get_logger("models")


class AgentTypes(str, Enum):
    RESEARCHER = "researcher"
    ANALYST = "analyst"
    WRITER = "writer"
    GENERAL = "general"


class Users(Base):
    """
    User model for authentication and authorization.

    Represents system users with authentication credentials and role-based access control.
    Each user can own multiple conversations and has a defined role (user/admin).

    Attributes:
        id (int): Primary key, auto-incrementing user identifier
        username (str): Unique username for authentication (indexed for performance)
        hashed_password (str): Bcrypt hashed password (never store plaintext)
        role (str): User role - 'user' (default) or 'admin' for elevated privileges

    Relationships:
        conversations: One-to-many relationship with Conversations model

    Indexes:
        - Primary key on id
        - Unique index on username for fast authentication lookups

    Security Features:
        - Unique constraint on username prevents duplicates
        - Password is always stored hashed using bcrypt
        - Role-based access control for admin operations
    """

    __tablename__ = "users"
    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    username = Column(String, unique=True, nullable=False, index=True)
    hashed_password = Column(String, nullable=False)
    role = Column(String, default=Role.USER.value, nullable=False)

    conversations = relationship(
        "Conversations",
        back_populates="owner",
        passive_deletes=True,
        cascade="save-update",
    )


class Conversations(Base):
    """
    Conversation model for chat session management.

    Represents individual chat conversations with ownership, metadata, and message history.
    Each conversation belongs to a user and can contain multiple messages.

    Attributes:
        id (int): Primary key, auto-incrementing conversation identifier
        owner_username (str): Foreign key to Users.username (nullable for deleted users)
        name (str): Optional human-readable name for the conversation
        created_at (DateTime): Timestamp when conversation was created (auto-set)
        modified_at (DateTime): Timestamp of last modification (auto-updated)

    Relationships:
        owner: Many-to-one relationship with Users model
        messages: One-to-many relationship with Messages model

    Cascade Behavior:
        - Messages are deleted when conversation is deleted (CASCADE)
        - Owner reference is set to NULL when user is deleted (SET NULL)

    Indexing:
        - Primary key on id
        - Index on owner_username for efficient user conversation queries

    Timestamp Management:
        - created_at: Set automatically on insert using database server time
        - modified_at: Updated automatically on any record modification
    """

    __tablename__ = "conversations"
    id = Column(Integer, primary_key=True, autoincrement=True)

    owner_username = Column(
        String,
        ForeignKey("users.username", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    name = Column(String, nullable=True)

    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    modified_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    owner = relationship(
        "Users",
        back_populates="conversations",
        foreign_keys=[owner_username],
        cascade="save-update",
        viewonly=False,
    )

    messages = relationship(
        "Messages",
        back_populates="conversation",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    tasks = relationship(
        "Task",
        back_populates="conversation",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class Messages(Base):
    """
    Message model for conversation content storage.

    Represents individual messages within conversations, storing both user inputs
    and agent/assistant responses with proper role identification.

    Attributes:
        id (int): Primary key, auto-incrementing message identifier
        role (str): Message sender role ('user', 'assistant', 'system')
        content (str): The actual message content/text
        created_at (DateTime): Timestamp when message was created (auto-set)
        conversation_id (int): Foreign key to parent Conversations record

    Relationships:
        conversation: Many-to-one relationship with Conversations model

    Indexing:
        - Primary key on id for unique identification
        - Index on conversation_id for efficient conversation queries

    Role Types:
        - 'user': Messages sent by human users
        - 'assistant': Messages sent by AI agents/assistants
        - 'system': System-generated messages (notifications, errors, etc.)

    Cascade Behavior:
        - Messages are automatically deleted when parent conversation is deleted
        - Uses database-level CASCADE for data consistency
    """

    __tablename__ = "messages"
    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    role = Column(String, nullable=False)
    content = Column(String, nullable=False)
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    conversation_id = Column(
        Integer,
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    conversation = relationship("Conversations", back_populates="messages")

    __table_args__ = (
        Index("idx_messages_conversation_created", "conversation_id", "created_at"),
    )


class Agents(Base):
    """
    Agent model for multi-agent system management.

    Represents AI agents with heartbeat tracking for monitoring agent availability.
    """

    __tablename__ = "agents"
    id = Column(String, primary_key=True)
    name = Column(String, unique=True, nullable=False, index=True)
    skills = Column(JSON, default=list, nullable=False)
    status = Column(String, default="inactive", nullable=False)
    description = Column(String, nullable=True)
    last_heartbeat = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
        index=True,
    )
    type = Column(SQLEnum(AgentTypes), nullable=False, default=AgentTypes.GENERAL)
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    api_key = Column(String, unique=True, nullable=False)


class Task(Base):
    __tablename__ = "tasks"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    conversation_id = Column(
        Integer,
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    parent_task_id = Column(String, ForeignKey("tasks.id"), nullable=True)
    agent_id = Column(String, nullable=False)
    status = Column(
        SQLEnum(TaskStatus, values_callable=lambda obj: [e.value for e in obj]),
        default=TaskStatus.PENDING.value,
    )
    query = Column(String, nullable=False)
    order = Column(Integer, nullable=True)
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    conversation = relationship(
        "Conversations", back_populates="tasks", passive_deletes=True
    )
    parent_task = relationship("Task", remote_side=[id], backref="subtasks")
    result = relationship(
        "TaskResult", back_populates="task", uselist=False, cascade="all, delete-orphan"
    )


class TaskResult(Base):
    __tablename__ = "task_results"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    task_id = Column(
        String, ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    result_data = Column(JSON, nullable=True)
    history = Column(JSON, nullable=True)
    future_actions = Column(JSON, nullable=True)
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    task = relationship("Task", back_populates="result")


class CriticalLogs(Base):
    """
    Critical system logs model for security and audit trails.

    Stores high-priority system events, security incidents, and audit information
    for compliance and monitoring purposes. This table captures detailed information
    about system operations for forensic analysis and security monitoring.

    Attributes:
        id (int): Primary key, auto-incrementing log entry identifier
        timestamp (DateTime): When the event occurred (auto-set with timezone)
        level (str): Log level (ERROR, CRITICAL, WARNING, etc.)
        category (str): Event category (SECURITY, AUTH, SYSTEM, etc.)
        component (str): System component that generated the log
        user_id (int): ID of user associated with the event (nullable)
        operation (str): Description of the operation performed
        details (Text): Detailed information about the event
        ip_address (str): IP address of the client (for security events)
        user_agent (Text): User agent string (for web requests)

    Indexing Strategy:
        - timestamp: For chronological queries and log rotation
        - category: For filtering by event type
        - user_id: For user-specific audit trails
        - component: For component-specific debugging
        - operation: For operation-specific analysis

    Use Cases:
        - Security incident investigation
        - Compliance audit trails
        - System performance monitoring
        - Error tracking and debugging
        - User activity monitoring
    """

    __tablename__ = "critical_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    level = Column(String(20), nullable=False)
    category = Column(String(20), nullable=False)
    component = Column(String(50), nullable=False)
    user_id = Column(Integer, nullable=True)
    operation = Column(String(100), nullable=False)
    details = Column(Text, nullable=True)
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(Text, nullable=True)

    __table_args__ = (
        Index("idx_critical_logs_timestamp", "timestamp"),
        Index("idx_critical_logs_category", "category"),
        Index("idx_critical_logs_user", "user_id"),
        Index("idx_critical_logs_component", "component"),
        Index("idx_critical_logs_operation", "operation"),
    )


# SQLAlchemy Event Listeners for Automatic CRUD Logging
# These event listeners automatically log all database operations for audit purposes


@event.listens_for(Users, "after_insert")
def log_user_insert(mapper, connection, target):
    """Log user creation events for security auditing."""
    log_db_operation(
        "CREATE", "users", f"username: {target.username}, role: {target.role}"
    )


@event.listens_for(Users, "after_update")
def log_user_update(mapper, connection, target):
    """Log user modification events for security auditing."""
    log_db_operation("UPDATE", "users", f"username: {target.username}")


@event.listens_for(Users, "after_delete")
def log_user_delete(mapper, connection, target):
    """Log user deletion events for security auditing."""
    log_db_operation("DELETE", "users", f"username: {target.username}")


@event.listens_for(Conversations, "after_insert")
def log_conversation_insert(mapper, connection, target):
    """Log conversation creation events for usage tracking."""
    log_db_operation(
        "CREATE", "conversations", f"id: {target.id}, owner: {target.owner_username}"
    )


@event.listens_for(Conversations, "after_update")
def log_conversation_update(mapper, connection, target):
    """Log conversation modification events for usage tracking."""
    log_db_operation("UPDATE", "conversations", f"id: {target.id}")


@event.listens_for(Conversations, "after_delete")
def log_conversation_delete(mapper, connection, target):
    """Log conversation deletion events for usage tracking."""
    log_db_operation("DELETE", "conversations", f"id: {target.id}")


@event.listens_for(Messages, "after_insert")
def log_message_insert(mapper, connection, target):
    """Log message creation events for conversation auditing."""
    log_db_operation(
        "CREATE",
        "messages",
        f"id: {target.id}, conversation: {target.conversation_id}, role: {target.role}",
    )


@event.listens_for(Messages, "after_update")
def log_message_update(mapper, connection, target):
    """Log message modification events for conversation auditing."""
    log_db_operation("UPDATE", "messages", f"id: {target.id}")


@event.listens_for(Messages, "after_delete")
def log_message_delete(mapper, connection, target):
    """Log message deletion events for conversation auditing."""
    log_db_operation("DELETE", "messages", f"id: {target.id}")


@event.listens_for(Task, "after_insert")
def log_task_insert(mapper, connection, target):
    """Log task creation events for task tracking."""
    log_db_operation(
        "CREATE",
        "tasks",
        f"id: {target.id}, conversation: {target.conversation_id}, agent: {target.agent_id}, status: {target.status}",
    )


@event.listens_for(Task, "after_update")
def log_task_update(mapper, connection, target):
    """Log task modification events for task tracking."""
    log_db_operation("UPDATE", "tasks", f"id: {target.id}, status: {target.status}")


@event.listens_for(Task, "after_delete")
def log_task_delete(mapper, connection, target):
    """Log task deletion events for task tracking."""
    log_db_operation(
        "DELETE", "tasks", f"id: {target.id}, conversation: {target.conversation_id}"
    )


@event.listens_for(TaskResult, "after_insert")
def log_task_result_insert(mapper, connection, target):
    """Log task result creation events."""
    log_db_operation(
        "CREATE", "task_results", f"id: {target.id}, task: {target.task_id}"
    )


@event.listens_for(TaskResult, "after_update")
def log_task_result_update(mapper, connection, target):
    """Log task result modification events."""
    log_db_operation(
        "UPDATE", "task_results", f"id: {target.id}, task: {target.task_id}"
    )
