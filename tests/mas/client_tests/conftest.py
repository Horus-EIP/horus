"""
Pytest configuration for client tests.
Provides fixtures for database sessions and models.
"""

import sys
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

# MAS service root (for running client_tests as scripts outside pytest)
_REPO_ROOT = Path(__file__).resolve().parents[2]
_MAS_ROOT = _REPO_ROOT / "src" / "services" / "mas"
sys.path.insert(0, str(_MAS_ROOT))

from db.database import Base, SessionLocal, engine
from db.models import Conversations, Messages, Task, TaskResult, Users


@pytest.fixture(scope="function")
def session() -> Session:
    """
    Provide a clean database session for each test.
    Creates a fresh database on setup, cleans up on teardown.
    """
    # Create all tables
    Base.metadata.create_all(bind=engine)

    # Create a session
    session = SessionLocal()

    try:
        yield session
    finally:
        # Clean up: remove all data from tables
        session.query(TaskResult).delete()
        session.query(Task).delete()
        session.query(Messages).delete()
        session.query(Conversations).delete()
        session.query(Users).delete()
        session.commit()
        session.close()

        # Drop all tables
        Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def user_id(session: Session) -> str:
    """
    Provide a sample user by creating a user in the database.
    """
    user = Users(username="testuser", role="user", hashed_password="test_password_hash")

    session.add(user)
    session.commit()

    return user.username


@pytest.fixture(scope="function")
def conversation_id(session: Session, user_id: str) -> int:
    """
    Provide a sample conversation ID by creating a conversation in the database.
    """
    conversation = Conversations(
        owner_username=user_id,
        name="Test Conversation",
        modified_at=datetime(2024, 1, 1),
    )

    session.add(conversation)
    session.commit()

    return conversation.id


@pytest.fixture(scope="function")
def task_id(session: Session, conversation_id: int) -> str:
    """
    Provide a sample task ID by creating a task in the database.
    """
    from uuid import uuid4

    task = Task(
        id=str(uuid4()),
        conversation_id=conversation_id,
        agent_id="agent_001",
        status="running",
        query="Test query",
        parent_task_id=None,
        order=0,
    )

    session.add(task)
    session.commit()

    return task.id


@pytest.fixture(scope="function")
def parent_task_id(session: Session, conversation_id: int) -> str:
    """
    Provide a sample parent task ID by creating a parent task in the database.
    """
    from uuid import uuid4

    parent_task = Task(
        id=str(uuid4()),
        conversation_id=conversation_id,
        agent_id="agent_001",
        status="running",
        query="Parent task query",
        parent_task_id=None,
        order=0,
    )

    session.add(parent_task)
    session.commit()

    return parent_task.id
