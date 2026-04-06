import json
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

# Need to import these to patch them or use them
from db.models import Task, TaskResult
from schemas.schemas import CollaborativeTask, SubTask
from tasks.status import TaskStatus
from tasks.task_tool_functions import (aggregate_results, build_action_list,
                                       build_subtask_list, clean_json_output,
                                       decompose_task,
                                       get_decomposition_prompt, get_prompt,
                                       get_prompt_final_answer_generation,
                                       get_tasks_in_progress, insert_new_task,
                                       interrupt_task, select_agent_for_task,
                                       sort_subtasks_by_dependency,
                                       validating_task_results)

# --- Fixtures ---


@pytest.fixture
def mock_db_session():
    """Returns a mock SQLAlchemy session."""
    session = MagicMock(spec=Session)
    return session


@pytest.fixture
def mock_rabbitmq():
    """Mocks the global rabbitmq_instance."""
    with patch("tasks.task_tool_functions.rabbitmq_instance") as mock:
        yield mock


@pytest.fixture
def mock_ask_llm():
    """Mocks the ask_llm function."""
    with patch("tasks.task_tool_functions.ask_llm") as mock:
        yield mock


@pytest.fixture
def mock_get_available_agents():
    """Mocks get_available_agents to return a fixed list."""
    with patch("tasks.task_tool_functions.get_available_agents") as mock:
        mock.return_value = [
            ("id_1", "Agent 1", "Desc 1", "researcher"),
            ("id_2", "Agent 2", "Desc 2", "analyst"),
        ]
        yield mock


@pytest.fixture
def mock_get_agent_id():
    with patch("tasks.task_tool_functions.get_agent_id") as mock:
        mock.side_effect = lambda name, db: (
            "id_1" if "Agent 1" in name else ("id_2" if "Agent 2" in name else None)
        )
        yield mock


@pytest.fixture
def mock_get_agent_by_type():
    with patch("tasks.task_tool_functions.get_agent_by_type") as mock:
        mock.side_effect = lambda type, db: (
            "id_1" if type == "researcher" else ("id_2" if type == "analyst" else None)
        )
        yield mock


@pytest.fixture
def mock_session_local():
    """Mocks SessionLocal in both locations."""
    mock_session = MagicMock(spec=Session)
    mock_factory = MagicMock(return_value=mock_session)

    # Patch both the original definition (for local imports) and the module-level import
    with patch("db.database.SessionLocal", mock_factory), patch(
        "tasks.task_tool_functions.SessionLocal", mock_factory
    ):
        yield mock_factory


# --- Tests ---


def test_clean_json_output():
    assert clean_json_output('{"key": "value"}') == '{"key": "value"}'
    assert clean_json_output('```json {"key": "value"} ```') == '{"key": "value"}'
    assert clean_json_output('``` {"key": "value"}```') == '{"key": "value"}'
    assert clean_json_output('  {"key": "value"}  ') == '{"key": "value"}'


def test_get_prompt_functions():
    suitable_agents = [("id1", "Ag1", "Desc1", "type1")]

    # get_prompt
    messages = get_prompt("Doing something", suitable_agents)
    assert len(messages) == 2

    # get_decomposition_prompt
    messages = get_decomposition_prompt("Complex task", suitable_agents)
    assert len(messages) == 2

    # get_prompt_final_answer_generation
    messages = get_prompt_final_answer_generation("History", "Final Result")
    assert len(messages) == 2


def test_build_action_list(
    mock_db_session, mock_rabbitmq, mock_get_agent_id, mock_session_local
):
    agents_avail = []  # unused

    # Case: db is None (Use SessionLocal)
    actions = [{"agent": "Agent 1", "input": "Do X"}]
    res = build_action_list(actions, agents_avail, db=None)
    assert len(res) == 1
    mock_session_local.assert_called()

    # Case: Normal (db provided)
    res = build_action_list(actions, agents_avail, mock_db_session)
    assert len(res) == 1
    mock_get_agent_id.assert_called_with("Agent 1", mock_db_session)
    mock_rabbitmq.create_queue.assert_called_with("id_1")

    # Error cases
    with pytest.raises(ValueError, match="must not be empty"):
        build_action_list([{"agent": "", "input": "X"}], agents_avail, mock_db_session)
    with pytest.raises(ValueError, match="must not be empty"):
        build_action_list(
            [{"agent": "Agent 1", "input": ""}], agents_avail, mock_db_session
        )
    with pytest.raises(ValueError, match="doesn't exists"):
        build_action_list(
            [{"agent": "Unknown", "input": "X"}], agents_avail, mock_db_session
        )


def test_sort_subtasks_by_dependency():
    t1 = SubTask(
        id="1",
        agent_type="researcher",
        description="D1",
        depends_on=[],
        status="pending",
    )
    t2 = SubTask(
        id="2",
        agent_type="analyst",
        description="D2",
        depends_on=["1"],
        status="pending",
    )

    sorted_tasks = sort_subtasks_by_dependency([t2, t1])
    assert [t.id for t in sorted_tasks] == ["1", "2"]


def test_build_subtask_list(
    mock_db_session, mock_rabbitmq, mock_get_agent_by_type, mock_session_local
):
    # Case: db is None
    t1 = SubTask(
        id="1",
        agent_type="researcher",
        description="D1",
        depends_on=[],
        status="pending",
    )
    collab = CollaborativeTask(sub_tasks=[t1])
    res = build_subtask_list(collab, [], db=None)
    assert len(res) == 1
    mock_session_local.assert_called()

    # Case: Normal
    res = build_subtask_list(collab, [], mock_db_session)
    assert len(res) == 1
    mock_get_agent_by_type.assert_called_with("researcher", mock_db_session)

    # Case: Cycle / Sort Error (Mock sort_subtasks_by_dependency to fail?)
    # Easier: Create a clear cycle that causes TopologicalSorter to raise CycleError
    tA = SubTask(
        id="A",
        agent_type="researcher",
        description="DA",
        depends_on=["B"],
        status="pending",
    )
    tB = SubTask(
        id="B",
        agent_type="analyst",
        description="DB",
        depends_on=["A"],
        status="pending",
    )
    collab_cycle = CollaborativeTask(sub_tasks=[tA, tB])

    # This should log error and fallback to unsorted list
    res_cycle = build_subtask_list(collab_cycle, [], mock_db_session)
    assert len(res_cycle) == 2

    # Error cases for validation inside loop
    t_bad_agent = SubTask(
        id="3", agent_type="", description="D", depends_on=[], status="pending"
    )
    with pytest.raises(ValueError, match="Agent type .* must not be empty"):
        build_subtask_list(
            CollaborativeTask(sub_tasks=[t_bad_agent]), [], mock_db_session
        )

    t_bad_desc = SubTask(
        id="4", agent_type="researcher", description="", depends_on=[], status="pending"
    )
    with pytest.raises(ValueError, match="Input .* must not be empty"):
        build_subtask_list(
            CollaborativeTask(sub_tasks=[t_bad_desc]), [], mock_db_session
        )


def test_decompose_task(
    mock_db_session,
    mock_ask_llm,
    mock_get_available_agents,
    mock_get_agent_by_type,
    mock_session_local,
    mock_rabbitmq,
):
    # Case: db is None
    with patch("tasks.task_tool_functions.get_available_agents") as mock_get_avail:
        mock_get_avail.return_value = []
        res = decompose_task("input", db=None)
        assert res == (None, [])
        mock_session_local.assert_called()

    # Case: Valid decomposition
    valid_json = json.dumps(
        {
            "sub_tasks": [
                {
                    "id": "1",
                    "agent_type": "researcher",
                    "description": "T1",
                    "depends_on": [],
                    "status": "pending",
                }
            ]
        }
    )
    mock_ask_llm.return_value = valid_json

    first, others = decompose_task("input", mock_db_session)
    assert first == ("id_1", "T1")
    assert others == []

    # Case: empty sub_tasks
    mock_ask_llm.return_value = '{"sub_tasks": []}'
    assert decompose_task("input", mock_db_session) == (None, [])

    # Case: JSONDecodeError
    mock_ask_llm.return_value = "invalid json"
    assert decompose_task("input", mock_db_session) == (None, [])

    # Case: Pydantic Validation Error (e.g. invalid status in JSON logic)
    # The code manually checks status != pending
    json_status_error = json.dumps(
        {
            "sub_tasks": [
                {
                    "id": "1",
                    "agent_type": "researcher",
                    "description": "T1",
                    "depends_on": [],
                    "status": "failed",
                }
            ]
        }
    )
    mock_ask_llm.return_value = json_status_error
    assert decompose_task("input", mock_db_session) == (None, [])

    # Case: General Exception (e.g. CollaborativeTask validation error)
    # Missing required field 'description'
    json_schema_error = json.dumps(
        {
            "sub_tasks": [
                {
                    "id": "1",
                    "agent_type": "researcher",
                    "depends_on": [],
                    "status": "pending",
                }
            ]
        }
    )
    mock_ask_llm.return_value = json_schema_error
    assert decompose_task("input", mock_db_session) == (None, [])


def test_select_agent_for_task(
    mock_db_session,
    mock_ask_llm,
    mock_get_available_agents,
    mock_get_agent_id,
    mock_session_local,
    mock_rabbitmq,
):
    # Case: db is None
    with patch("tasks.task_tool_functions.get_available_agents", return_value=[]):
        res = select_agent_for_task("input", db=None)
        assert res == (None, None, None, [])
        mock_session_local.assert_called()

    # Case: Respond to user
    mock_ask_llm.return_value = json.dumps(
        {"classification": "DIRECT_ANSWER", "final_answer": "Hi"}
    )
    res = select_agent_for_task("input", mock_db_session)
    assert res[2] == "Response for user : Hi"

    # Case: Run agents
    mock_ask_llm.return_value = json.dumps(
        {
            "classification": "SINGLE_AGENT",
            "agent_name": "Agent 1",
            "rewritten_input": "Do 1",
        }
    )
    res = select_agent_for_task("input", mock_db_session)
    assert res[0] == "id_1"

    # Case: Invalid JSON (caught and returns None)
    mock_ask_llm.return_value = "invalid json"
    res = select_agent_for_task("input", mock_db_session)
    assert res == (None, None, None, [])

    # Case: Invalid classification (caught and returns None)
    mock_ask_llm.return_value = json.dumps({"classification": "UNKNOWN"})
    res = select_agent_for_task("input", mock_db_session)
    assert res == (None, None, None, [])

    # Case: SINGLE_AGENT but no agent_name (caught and returns None)
    mock_ask_llm.return_value = json.dumps(
        {"classification": "SINGLE_AGENT", "rewritten_input": "Do 1"}
    )
    res = select_agent_for_task("input", mock_db_session)
    assert res == (None, None, None, [])


def test_insert_new_task(mock_db_session):
    # Success
    task_id = insert_new_task(1, "agent_1", "query", [], [], mock_db_session)
    assert task_id is not None
    mock_db_session.commit.assert_called()

    # Exception during add
    mock_db_session.add.side_effect = Exception("DB Error")
    task_id = insert_new_task(1, "agent_1", "query", [], [], mock_db_session)
    assert task_id is None
    mock_db_session.rollback.assert_called()


def test_validating_task_results(mock_db_session):
    # Success
    mock_task = MagicMock(spec=Task, status=TaskStatus.RUNNING)
    mock_task.result = MagicMock(spec=TaskResult, history=[])
    mock_db_session.query.return_value.filter.return_value.first.return_value = (
        mock_task
    )

    validating_task_results("tid", "result", mock_db_session)
    assert mock_task.status == TaskStatus.COMPLETED

    # Case: Task not found (raises HTTPException)
    mock_db_session.query.return_value.filter.return_value.first.return_value = None
    with pytest.raises(HTTPException) as exc:
        validating_task_results("tid", "result", mock_db_session)
    assert exc.value.status_code == 404

    # Case: General Exception (raises HTTPException 500)
    mock_db_session.query.side_effect = Exception("DB Error")
    with pytest.raises(HTTPException) as exc:
        validating_task_results("tid", "result", mock_db_session)
    assert exc.value.status_code == 500
    mock_db_session.rollback.assert_called()


def test_interrupt_task(mock_db_session, mock_rabbitmq):
    mock_task = MagicMock(
        spec=Task,
        id="tid",
        agent_id="aid",
        conversation_id=1,
        status=TaskStatus.RUNNING,
    )
    mock_db_session.query.return_value.filter.return_value.first.return_value = (
        mock_task
    )

    # Success
    res = interrupt_task("tid", mock_db_session)
    assert res is True
    assert mock_task.status == TaskStatus.CANCELED
    mock_rabbitmq.publish.assert_called()

    # Case: Task not found (404)
    mock_db_session.query.return_value.filter.return_value.first.return_value = None
    with pytest.raises(HTTPException) as exc:
        interrupt_task("tid", mock_db_session)
    assert exc.value.status_code == 404

    # Case: Task already completed (400)
    mock_task.status = TaskStatus.COMPLETED
    mock_db_session.query.return_value.filter.return_value.first.return_value = (
        mock_task
    )
    with pytest.raises(HTTPException) as exc:
        interrupt_task("tid", mock_db_session)
    assert exc.value.status_code == 400

    # Case: General Exception (500)
    # We need to reset the status to running to pass the first check
    mock_task.status = TaskStatus.RUNNING
    # We assume 'commit' raises the exception
    mock_db_session.commit.side_effect = Exception("DB Error")
    with pytest.raises(HTTPException) as exc:
        interrupt_task("tid", mock_db_session)
    assert exc.value.status_code == 500
    mock_db_session.rollback.assert_called()


def test_get_tasks_in_progress(mock_db_session):
    mock_db_session.query.return_value.filter.return_value.all.return_value = []
    assert get_tasks_in_progress(mock_db_session) == []

    mock_db_session.query.side_effect = Exception("Error")
    with pytest.raises(HTTPException):
        get_tasks_in_progress(mock_db_session)


def test_aggregate_results(mock_ask_llm):
    mock_ask_llm.return_value = "Result"
    assert aggregate_results("Hist", "Final") == "Result"
