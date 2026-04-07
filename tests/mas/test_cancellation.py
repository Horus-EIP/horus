from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from db.models import Task
from tasks.status import TaskStatus
from tasks.task_tool_functions import interrupt_task

# Mock rabbitmq_instance before importing task_tool_functions fully if needed,
# but since we import interrupt_task, we can patch it where it is used or patch the object in the module.


@pytest.fixture
def mock_db():
    return MagicMock()


@pytest.fixture
def mock_rabbitmq():
    with patch("tasks.task_tool_functions.rabbitmq_instance") as mock:
        yield mock


def test_interrupt_task_success(mock_db, mock_rabbitmq):
    # Setup
    task_id = "task-123"
    agent_id = "agent-007"
    conversation_id = "conv-1"

    mock_task = MagicMock(spec=Task)
    mock_task.id = task_id
    mock_task.agent_id = agent_id
    mock_task.conversation_id = conversation_id
    mock_task.status = TaskStatus.RUNNING

    mock_db.query.return_value.filter.return_value.first.return_value = mock_task

    # Execute
    result = interrupt_task(task_id, mock_db)

    # Verify
    assert result is True
    assert mock_task.status == TaskStatus.CANCELED
    mock_db.commit.assert_called_once()

    # Verify RabbitMQ publish
    mock_rabbitmq.publish.assert_called_once()
    call_args = mock_rabbitmq.publish.call_args
    assert call_args.kwargs["queue_name"] == agent_id
    assert call_args.kwargs["priority_value"] == 10
    assert '"type": "cancel"' in call_args.kwargs["message"]
    assert task_id in call_args.kwargs["message"]


def test_interrupt_task_not_found(mock_db, mock_rabbitmq):
    # Setup
    task_id = "task-unknown"
    mock_db.query.return_value.filter.return_value.first.return_value = None

    # Execute & Verify
    with pytest.raises(HTTPException) as exc:
        interrupt_task(task_id, mock_db)
    assert exc.value.status_code == 404
    mock_rabbitmq.publish.assert_not_called()


def test_interrupt_task_already_completed(mock_db, mock_rabbitmq):
    # Setup
    task_id = "task-completed"
    mock_task = MagicMock(spec=Task)
    mock_task.id = task_id
    mock_task.status = (
        TaskStatus.COMPLETED.value
    )  # Or TaskStatus.COMPLETED depending on how it's stored

    # Note: In the code provided:
    # if task.status in [TaskStatus.COMPLETED.value, ...]:
    # So we should ensure we match that check.

    mock_db.query.return_value.filter.return_value.first.return_value = mock_task

    # Execute & Verify
    with pytest.raises(HTTPException) as exc:
        interrupt_task(task_id, mock_db)
    assert exc.value.status_code == 400
    mock_rabbitmq.publish.assert_not_called()


from tasks.controller import check_task_timeout, get_tasks_in_progress


@pytest.mark.asyncio
async def test_check_task_timeout_logic():
    # This is a bit harder to test because it's an infinite loop.
    # We can mock get_tasks_in_progress and interrupt_task, and run one iteration?
    # Or we can extract the logic inside the loop to a separate function.
    # For now, let's just verify the logic by mocking the dependencies and
    # ensuring the loop would call interrupt_task for old tasks.

    with patch("tasks.controller.SessionLocal") as mock_session_cls, patch(
        "tasks.controller.get_tasks_in_progress"
    ) as mock_get_tasks, patch(
        "tasks.controller.interrupt_task"
    ) as mock_interrupt, patch(
        "tasks.controller.settings"
    ) as mock_settings, patch(
        "asyncio.sleep", side_effect=InterruptedError("Stop loop")
    ):  # Raise exception to break loop

        mock_db = MagicMock()
        mock_session_cls.return_value = mock_db
        mock_settings.task_timeout = 300

        # Task that is old
        old_task = MagicMock()
        old_task.id = "old-task"
        old_task.updated_at = datetime.now(timezone.utc) - timedelta(seconds=301)

        # Task that is new
        new_task = MagicMock()
        new_task.id = "new-task"
        new_task.updated_at = datetime.now(timezone.utc) - timedelta(seconds=100)

        mock_get_tasks.return_value = [old_task, new_task]

        try:
            await check_task_timeout(
                test_mode=True
            )  # test_mode=True breaks the loop after one iteration
        except InterruptedError:
            pass

        # Verify interrupt_task was called ONLY for old_task
        mock_interrupt.assert_called_once_with("old-task", mock_db)
