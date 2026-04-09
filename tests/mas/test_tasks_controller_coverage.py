import asyncio
import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tasks.controller import check_task_timeout
from tasks.status import TaskStatus


@pytest.fixture
def mock_db_session():
    mock_session = MagicMock()
    # Ensure close is called
    mock_session.close = MagicMock()
    return mock_session


@pytest.fixture
def mock_settings():
    with patch("tasks.controller.settings") as mock:
        mock.task_timeout = 30  # seconds
        yield mock


@pytest.fixture
def mock_get_tasks_in_progress():
    with patch("tasks.controller.get_tasks_in_progress") as mock:
        yield mock


@pytest.fixture
def mock_interrupt_task():
    with patch("tasks.controller.interrupt_task") as mock:
        yield mock


@pytest.fixture
def mock_session_local(mock_db_session):
    with patch("tasks.controller.SessionLocal", return_value=mock_db_session) as mock:
        yield mock


class StopLoopException(BaseException):
    pass


@pytest.mark.asyncio
async def test_check_task_timeout_no_tasks(
    mock_session_local, mock_get_tasks_in_progress, mock_settings
):
    # Setup: No tasks in progress
    mock_get_tasks_in_progress.return_value = []

    # Run once by throwing exception in sleep to break loop
    # We use BaseException to bypass the catch-all "except Exception" in the code
    with patch(
        "asyncio.sleep", side_effect=[None, StopLoopException("StopLoop")]
    ) as mock_sleep:
        try:
            await check_task_timeout(test_mode=True)
        except StopLoopException:
            pass

    mock_get_tasks_in_progress.assert_called()
    mock_session_local.return_value.close.assert_called()


@pytest.mark.asyncio
async def test_check_task_timeout_task_active(
    mock_session_local, mock_get_tasks_in_progress, mock_interrupt_task, mock_settings
):
    # Runtime is measured from created_at (RUNNING tasks rarely get DB updates during LLM work).
    task = MagicMock()
    task.id = "task_1"
    task.conversation_id = 1
    task.created_at = datetime.datetime.now(datetime.timezone.utc)

    mock_get_tasks_in_progress.return_value = [task]

    with patch("asyncio.sleep", side_effect=[None, StopLoopException("StopLoop")]):
        try:
            await check_task_timeout(test_mode=True)
        except StopLoopException:
            pass

    # Should NOT have interrupted
    mock_interrupt_task.assert_not_called()


@pytest.mark.asyncio
async def test_check_task_timeout_task_stale(
    mock_session_local, mock_get_tasks_in_progress, mock_interrupt_task, mock_settings
):
    task = MagicMock()
    task.id = "task_stale"
    task.conversation_id = 42
    task.created_at = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(
        seconds=100
    )

    mock_settings.task_timeout = 30

    mock_get_tasks_in_progress.return_value = [task]

    with (
        patch("asyncio.sleep", side_effect=[None, StopLoopException("StopLoop")]),
        patch(
            "tasks.controller.send_messages_via_websockets", new_callable=AsyncMock
        ) as mock_ws,
    ):
        try:
            await check_task_timeout(test_mode=True)
        except StopLoopException:
            pass

    mock_interrupt_task.assert_called_once()
    assert mock_interrupt_task.call_args[0][0] == "task_stale"
    assert mock_interrupt_task.call_args[0][2].startswith("Exceeded maximum runtime")
    mock_ws.assert_awaited_once()


@pytest.mark.asyncio
async def test_check_task_timeout_db_error(mock_session_local):
    # Setup: SessionLocal raises exception
    mock_session_local.side_effect = Exception("DB Connection Failed")

    # This exception is caught by "except Exception" in outer loop
    # We need to break the loop eventually.
    # The code catches exception, logs, and sleeps(5).
    # So we need sleep to raise StopLoopException.

    with patch(
        "asyncio.sleep", side_effect=StopLoopException("StopLoop")
    ) as mock_sleep:
        try:
            await check_task_timeout(test_mode=True)
        except StopLoopException:
            pass

    # Should have logged error
    assert mock_session_local.call_count >= 1


@pytest.mark.asyncio
async def test_check_task_timeout_task_no_created_at(
    mock_session_local, mock_get_tasks_in_progress, mock_interrupt_task, mock_settings
):
    task = MagicMock()
    task.id = "task_none"
    task.conversation_id = 7
    task.created_at = None

    mock_get_tasks_in_progress.return_value = [task]

    with patch("asyncio.sleep", side_effect=[None, StopLoopException("StopLoop")]):
        try:
            await check_task_timeout(test_mode=True)
        except StopLoopException:
            pass

    mock_interrupt_task.assert_not_called()
