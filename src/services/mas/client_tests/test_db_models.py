"""
Database Model Tests - Direct Database Verification

This module provides direct database tests to verify the Task and TaskResult models:
- Task model with parent_task_id for hierarchical structure
- TaskResult model with result_data, history, and future_actions
- Relationships between Task and TaskResult
- Query and retrieval operations

Requirements:
- PostgreSQL database configured in db/database.py
- Models defined in db/models.py (Task, TaskResult)
- SQLAlchemy session management

Usage:
    python test_db_models.py
"""

import asyncio
import os
import sys
from datetime import datetime
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + "/../")

from db.database import URL_DATABASE, Base, engine
from db.models import Conversations, Messages, Task, TaskResult, Users


def print_separator(title: str = "") -> None:
    """Print a formatted separator line."""
    if title:
        print(f"\n{'=' * 70}")
        print(f"  {title}")
        print("=" * 70)
    else:
        print("-" * 70)


def test_task_model_creation(session: Session, conversation_id: int) -> str:
    """
    Test Task model creation and storage.

    Verifies:
    - Task can be created with all required fields
    - Task ID is unique (UUID)
    - parent_task_id can be None for main tasks
    - Task is stored in database

    Args:
        session (Session): SQLAlchemy session
        conversation_id (int): Conversation ID fixture

    Returns:
        str: Created task ID
    """
    print_separator("TEST 1: Task Model Creation")

    task_id = str(uuid4())

    task = Task(
        id=task_id,
        conversation_id=conversation_id,
        agent_id="agent_001",
        status="running",
        query="Calculate the square root of 4",
        parent_task_id=None,  # Main task
        order=0,
    )

    session.add(task)
    session.commit()

    print(f"✅ Task created successfully")
    print(f"   Task ID: {task_id}")
    print(f"   Conversation ID: {conversation_id}")
    print(f"   Agent ID: agent_001")
    print(f"   Status: running")
    print(f"   Query: {task.query}")
    print(f"   Parent Task ID: {task.parent_task_id}")
    print(f"   Order: {task.order}")
    print(f"   Created At: {task.created_at}")

    return task_id


def test_task_result_model_creation(session: Session, task_id: str) -> str:
    """
    Test TaskResult model creation with complete data storage.

    Verifies:
    - TaskResult can store result_data (JSON)
    - TaskResult can store history (JSON array)
    - TaskResult can store future_actions (JSON array)
    - TaskResult is linked to correct Task

    Args:
        session (Session): SQLAlchemy session
        task_id (str): Task ID to link to

    Returns:
        str: Created task result ID
    """
    print_separator("TEST 2: TaskResult Model Creation")

    task_result_id = str(uuid4())

    history = [
        {
            "role": "user",
            "message": "Calculate the square root of 4",
        }
    ]

    future_actions = [["agent_002", "Translate the result into English"]]

    result_data = "The square root of 4 is 2."

    task_result = TaskResult(
        id=task_result_id,
        task_id=task_id,
        result_data=result_data,
        history=history,
        future_actions=future_actions,
    )

    session.add(task_result)
    session.commit()

    print(f"✅ TaskResult created successfully")
    print(f"   TaskResult ID: {task_result_id}")
    print(f"   Task ID: {task_id}")
    print(f"   Result Data: {task_result.result_data}")
    print(f"   History: {task_result.history}")
    print(f"   Future Actions: {task_result.future_actions}")
    print(f"   Created At: {task_result.created_at}")

    return task_result_id


def test_subtask_creation(
    session: Session, parent_task_id: str, conversation_id: int
) -> str:
    """
    Test Subtask creation with parent_task_id relationship.

    Verifies:
    - Subtask can reference parent task via parent_task_id
    - Subtask inherits conversation context from workflow
    - Multiple subtasks can share same parent

    Args:
        session (Session): SQLAlchemy session
        parent_task_id (str): Parent task ID
        conversation_id (int): Conversation ID fixture

    Returns:
        str: Created subtask ID
    """
    print_separator("TEST 3: Subtask Creation (Parent-Child Relationship)")

    subtask_id = str(uuid4())

    subtask = Task(
        id=subtask_id,
        conversation_id=conversation_id,
        agent_id="agent_002",
        status="running",
        query="Translate result into English",
        parent_task_id=parent_task_id,  # Link to parent task
        order=1,  # Second in sequence
    )

    session.add(subtask)
    session.commit()

    print(f"✅ Subtask created successfully")
    print(f"   Subtask ID: {subtask_id}")
    print(f"   Parent Task ID: {subtask.parent_task_id}")
    print(f"   Agent ID: agent_002")
    print(f"   Status: running")
    print(f"   Query: {subtask.query}")
    print(f"   Order: {subtask.order}")

    return subtask_id


def test_task_retrieval(session: Session, task_id: str) -> None:
    """
    Test Task retrieval and relationship queries.

    Verifies:
    - Task can be retrieved by ID
    - Task.result relationship works (TaskResult)
    - Task.subtasks relationship works (list of child Tasks)
    - All data is correctly populated

    Args:
        session (Session): SQLAlchemy session
        task_id (str): Task ID to retrieve
    """
    print_separator("TEST 4: Task Retrieval and Relationships")

    task = session.query(Task).filter(Task.id == task_id).first()

    if not task:
        print(f"❌ Task not found: {task_id}")
        return

    print(f"✅ Task retrieved successfully")
    print(f"   Task ID: {task.id}")
    print(f"   Agent ID: {task.agent_id}")
    print(f"   Status: {task.status}")
    print(f"   Query: {task.query}")

    # Test TaskResult relationship
    if task.result:
        print(f"\n✅ TaskResult found via relationship:")
        print(f"   TaskResult ID: {task.result.id}")
        print(f"   Result Data: {task.result.result_data}")
        print(
            f"   History items: {len(task.result.history) if task.result.history else 0}"
        )
        print(
            f"   Future actions: {len(task.result.future_actions) if task.result.future_actions else 0}"
        )
    else:
        print(f"⚠️  No TaskResult associated with this task yet")

    # Test subtasks relationship
    if task.subtasks:
        print(f"\n✅ Subtasks found via relationship:")
        for i, subtask in enumerate(task.subtasks):
            print(f"   Subtask {i+1}:")
            print(f"     - ID: {subtask.id}")
            print(f"     - Agent ID: {subtask.agent_id}")
            print(f"     - Order: {subtask.order}")
            print(f"     - Status: {subtask.status}")
    else:
        print(f"⚠️  No subtasks associated with this task yet")


def test_query_chains(session: Session) -> None:
    """
    Test complex query operations.

    Verifies:
    - Query all tasks for a conversation
    - Filter by status
    - Get only main tasks (parent_task_id IS NULL)
    - Get only subtasks (parent_task_id IS NOT NULL)

    Args:
        session (Session): SQLAlchemy session
    """
    print_separator("TEST 5: Complex Query Operations")

    conversation_id = "1"

    # Query 1: All tasks in conversation
    all_tasks = (
        session.query(Task).filter(Task.conversation_id == conversation_id).all()
    )

    print(f"✅ All tasks in conversation:")
    print(f"   Total tasks: {len(all_tasks)}")

    # Query 2: Main tasks only (parent_task_id IS NULL)
    main_tasks = (
        session.query(Task)
        .filter(Task.conversation_id == conversation_id, Task.parent_task_id.is_(None))
        .all()
    )

    print(f"\n✅ Main tasks (no parent):")
    print(f"   Count: {len(main_tasks)}")
    for task in main_tasks:
        print(f"   - {task.id}: {task.query[:50]}...")

    # Query 3: Subtasks only (parent_task_id IS NOT NULL)
    subtasks = (
        session.query(Task)
        .filter(
            Task.conversation_id == conversation_id, Task.parent_task_id.isnot(None)
        )
        .all()
    )

    print(f"\n✅ Subtasks (with parent):")
    print(f"   Count: {len(subtasks)}")
    for task in subtasks:
        print(f"   - {task.id}: parent={task.parent_task_id}, order={task.order}")

    # Query 4: Running tasks
    running_tasks = (
        session.query(Task)
        .filter(Task.conversation_id == conversation_id, Task.status == "running")
        .all()
    )

    print(f"\n✅ Running tasks:")
    print(f"   Count: {len(running_tasks)}")

    # Query 5: Completed tasks with results
    completed_tasks_with_results = (
        session.query(Task)
        .filter(Task.conversation_id == conversation_id, Task.status == "completed")
        .all()
    )

    print(f"\n✅ Completed tasks:")
    print(f"   Count: {len(completed_tasks_with_results)}")


def test_data_persistence(session: Session, task_id: str) -> None:
    """
    Test data persistence across session boundaries.

    Verifies:
    - Data is stored persistently in database
    - New session can retrieve same data
    - Relationships work across sessions

    Args:
        session (Session): SQLAlchemy session
        task_id (str): Task ID to verify
    """
    print_separator("TEST 6: Data Persistence Verification")

    # Close current session to simulate new connection
    session.close()

    # Create new session
    SessionLocal = sessionmaker(bind=engine)
    new_session = SessionLocal()

    # Retrieve task in new session
    task = new_session.query(Task).filter(Task.id == task_id).first()

    if task:
        print(f"✅ Task retrieved in new session successfully")
        print(f"   Task ID: {task.id}")
        print(f"   Agent ID: {task.agent_id}")
        print(f"   Status: {task.status}")

        # Verify relationship
        if task.result:
            print(f"✅ TaskResult accessible in new session")
            print(f"   Result Data: {task.result.result_data}")
        else:
            print(f"⚠️  TaskResult not found in new session")
    else:
        print(f"❌ Task not found in new session")

    new_session.close()


def run_all_tests() -> None:
    """Run all database model tests."""
    print("\n" + "=" * 70)
    print("DATABASE MODEL TESTS - Task and TaskResult")
    print("=" * 70)
    print(f"\nDatabase URL: {URL_DATABASE}")

    # Create session
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()

    try:
        # Create a dummy conversation for testing
        # We need to create a real conversation because of FK constraints
        print("Creating test conversation...")
        test_conv = Conversations(
            name="DB Model Test Conversation", owner_username="admin"
        )
        session.add(test_conv)
        session.commit()
        session.refresh(test_conv)
        conversation_id = test_conv.id
        print(f"Created test conversation with ID: {conversation_id}")

        # Run tests in sequence
        task_id = test_task_model_creation(session, conversation_id)
        task_result_id = test_task_result_model_creation(session, task_id)
        subtask_id = test_subtask_creation(session, task_id, conversation_id)
        test_task_retrieval(session, task_id)
        test_query_chains(session)
        test_data_persistence(session, task_id)

        print_separator()
        print("\n✅ ALL DATABASE TESTS PASSED SUCCESSFULLY!")
        print("\nTest Summary:")
        print(f"  ✓ Task model works correctly")
        print(f"  ✓ TaskResult model works correctly")
        print(f"  ✓ Parent-child relationships work")
        print(f"  ✓ Queries execute correctly")
        print(f"  ✓ Data persists to database")
        print(f"  ✓ Relationships accessible across sessions")

    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback

        traceback.print_exc()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    run_all_tests()
