"""
Tests for task tool functions (Database-based implementation)

Tests the task workflow functions:
- get_prompt: Creates LLM prompt with available agents
- clean_json_output: Cleans JSON from LLM output
- build_action_list: Maps agent names to IDs
- select_agent_for_task: LLM-based agent selection
- insert_new_task: Creates task and taskresult in DB
- validating_task_results: Updates task result
"""

import json
import sys
import uuid
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.orm import Session

from agents.registry_tool_functions import create_agent, get_available_agents
from db.database import Base, SessionLocal, engine
from db.models import AgentTypes, Conversations, Task, TaskResult, Users
from tasks.task_tool_functions import (build_action_list, clean_json_output,
                                       get_prompt, insert_new_task,
                                       select_agent_for_task,
                                       validating_task_results)

# ---------- Fixtures ----------


@pytest.fixture(scope="function")
def db_session():
    """Create a fresh database session for each test."""
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    yield session
    session.query(TaskResult).delete()
    session.query(Task).delete()
    session.query(Conversations).delete()
    session.query(Users).delete()
    session.commit()
    session.close()
    # Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def mock_ask_llm():
    """Mock the ask_llm function imported in tasks.task_tool_functions."""
    with patch("tasks.decomposition.ask_llm") as mock:
        yield mock


@pytest.fixture(scope="function")
def sample_conversation(db_session: Session):
    """Create a sample conversation for testing."""
    user = Users(username="testuser", hashed_password="hashed", role="user")
    db_session.add(user)
    db_session.commit()

    conv = Conversations(owner_username="testuser", name="Test Conversation")
    db_session.add(conv)
    db_session.commit()

    return conv.id


# ---------- Tests: get_prompt ----------


def test_get_prompt_includes_agents_and_user_input():
    """Test that get_prompt creates correct message structure."""
    suitable_agents = [
        ("id-a", "A1", "alpha agent", "score_a"),
        ("id-b", "A2", "beta agent", "score_b"),
    ]
    user_input = "Find me tomorrow's weather in Paris."

    messages = get_prompt(user_input, suitable_agents)

    assert isinstance(messages, list)
    assert len(messages) == 2
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"

    user_block = messages[1]["content"]
    assert "AVAILABLE AGENTS" in user_block
    assert "- A1: alpha agent" in user_block
    assert "- A2: beta agent" in user_block
    assert "USER INPUT" in user_block
    assert "Find me tomorrow's weather in Paris" in user_block


def test_get_prompt_with_empty_agents():
    """Test get_prompt with no available agents."""
    suitable_agents = []
    user_input = "Test input"

    messages = get_prompt(user_input, suitable_agents)

    assert isinstance(messages, list)
    assert len(messages) == 2
    user_content = messages[1]["content"]
    assert "AVAILABLE AGENTS" in user_content
    assert "USER INPUT" in user_content
    assert "Test input" in user_content


# ---------- Tests: clean_json_output ----------


def test_clean_json_output_keeps_plain_json():
    """Test that clean_json_output preserves valid JSON."""
    raw = '{"next_action":"respond_to_user","actions":[],"final_answer":"ok"}'

    result = clean_json_output(raw)

    assert result == raw


def test_clean_json_output_strips_triple_backticks_with_language():
    """Test that clean_json_output removes code fences with language."""
    raw = """```json
{"next_action":"respond_to_user","actions":[],"final_answer":"done"}
```"""

    result = clean_json_output(raw)

    assert (
        result == '{"next_action":"respond_to_user","actions":[],"final_answer":"done"}'
    )
    parsed = json.loads(result)
    assert parsed["next_action"] == "respond_to_user"


def test_clean_json_output_strips_triple_backticks_without_language():
    """Test that clean_json_output removes code fences without language."""
    raw = """```
{"next_action":"run_agents","actions":[{"agent":"A1","input":"q"}],"final_answer":""}
```"""

    result = clean_json_output(raw)

    assert (
        result
        == '{"next_action":"run_agents","actions":[{"agent":"A1","input":"q"}],"final_answer":""}'
    )
    parsed = json.loads(result)
    assert parsed["next_action"] == "run_agents"


def test_clean_json_output_strips_whitespace():
    """Test that clean_json_output removes leading/trailing whitespace."""
    raw = '   {"next_action": "respond_to_user"}   \n\t'

    result = clean_json_output(raw)

    assert result == '{"next_action": "respond_to_user"}'


# ---------- Tests: build_action_list ----------


def test_build_action_list_success_maps_names_to_ids(db_session: Session):
    """Test that build_action_list correctly maps agent names to IDs."""
    a1_id, _ = create_agent("A1", ["x"], "alpha", db_session, AgentTypes.GENERAL)
    a2_id, _ = create_agent("A2", ["y"], "beta", db_session, AgentTypes.GENERAL)

    actions_dict = [
        {"agent": "A1", "input": "question-1"},
        {"agent": "A2", "input": "question-2"},
    ]

    with patch("tasks.decomposition.rabbitmq_instance.create_queue"):
        action_list = build_action_list(actions_dict, [], db_session)

    assert isinstance(action_list, list)
    assert len(action_list) == 2
    assert action_list[0] == (a1_id, "question-1")
    assert action_list[1] == (a2_id, "question-2")


def test_build_action_list_raises_on_empty_agent_name(db_session: Session):
    """Test that build_action_list raises error for empty agent name."""
    create_agent("A1", [], "desc", db_session, AgentTypes.GENERAL)

    with pytest.raises(ValueError) as exc:
        build_action_list([{"agent": "", "input": "q"}], [], db_session)

    assert "must not be empty" in str(exc.value)


def test_build_action_list_raises_on_unknown_agent(db_session: Session):
    """Test that build_action_list raises error for unknown agent."""
    create_agent("A1", [], "desc", db_session, AgentTypes.GENERAL)

    with pytest.raises(ValueError) as exc:
        build_action_list([{"agent": "DoesNotExist", "input": "q"}], [], db_session)

    assert "doesn't exists" in str(exc.value)


def test_build_action_list_raises_on_empty_input(db_session: Session):
    """Test that build_action_list raises error for empty input."""
    create_agent("A1", [], "desc", db_session, AgentTypes.GENERAL)

    with pytest.raises(ValueError) as exc:
        build_action_list([{"agent": "A1", "input": ""}], [], db_session)

    assert "must not be empty" in str(exc.value)


# ---------- Tests: select_agent_for_task ----------


def test_select_agent_for_task_no_agents_returns_nones(db_session: Session):
    """Test that select_agent_for_task returns None values when no agents."""
    # Mock get_available_agents to return empty list even if DB has agents
    with patch("tasks.decomposition.get_available_agents", return_value=[]):
        first_agent, first_action, final_answer, remaining = select_agent_for_task(
            "Hello", db_session
        )

    assert first_agent is None
    assert first_action is None
    assert final_answer is None
    assert remaining == []


def test_select_agent_for_task_respond_to_user(mock_ask_llm, db_session: Session):
    """Test when LLM decides to respond to user directly."""
    unique_name = f"TestAgent_{uuid.uuid4().hex[:8]}"
    create_agent(unique_name, ["test"], "Test agent", db_session, AgentTypes.GENERAL)

    mock_ask_llm.return_value = '{"classification": "DIRECT_ANSWER", "final_answer": "I can help!"}'

    first_agent, first_action, final_answer, remaining = select_agent_for_task(
        "Hello", db_session
    )

    assert first_agent is None
    assert first_action is None
    assert "I can help!" in final_answer
    assert remaining == []


def test_select_agent_for_task_run_single_agent(mock_ask_llm, db_session: Session):
    """Test when LLM decides to run a single agent."""
    unique_name = f"TestAgent_{uuid.uuid4().hex[:8]}"
    agent_id, _ = create_agent(
        unique_name, ["test"], "Test agent", db_session, AgentTypes.GENERAL
    )

    mock_ask_llm.return_value = json.dumps(
        {
            "classification": "SINGLE_AGENT",
            "agent_name": unique_name,
            "rewritten_input": "Do something",
        }
    )

    with patch("tasks.decomposition.rabbitmq_instance.create_queue"):
        first_agent, first_action, final_answer, remaining = select_agent_for_task(
            "Do something", db_session
        )

    assert first_agent == agent_id
    assert first_action == "Do something"
    assert final_answer is None
    assert remaining == []


def test_select_agent_for_task_run_multiple_agents(mock_ask_llm, db_session: Session):
    """COMPLEX_TASK must produce a real multi-agent plan, not push the work elsewhere.

    Previously this test asserted ``(None, None, None, [])`` — codifying a
    broken design where ``select_agent_for_task`` washed its hands on COMPLEX
    requests and left downstream callers to "fall back to decomposition",
    except the call chain in :mod:`tasks.routes` always grabbed the request
    via single-agent paths (skill-match → auto-create → catch-all) before
    decomposition could fire. That made multi-agent dispatch structurally
    unreachable on a platform whose entire pitch is multi-agent collaboration.

    Corrected contract: when the router classifies as COMPLEX_TASK, the
    function runs the planner inline and surfaces ``(first_agent_id,
    first_demand, None, remaining_actions)``. The caller dispatches the
    first action immediately and chains the rest via the existing
    task-result subtask flow — no special-case branching required.
    """
    unique_name1 = f"Agent1_{uuid.uuid4().hex[:8]}"
    unique_name2 = f"Agent2_{uuid.uuid4().hex[:8]}"
    agent_id1, _ = create_agent(
        unique_name1, ["test"], "First agent", db_session, AgentTypes.GENERAL
    )
    agent_id2, _ = create_agent(
        unique_name2, ["test"], "Second agent", db_session, AgentTypes.GENERAL
    )

    # Two ask_llm calls happen on the COMPLEX_TASK path:
    # 1. intent router  → returns the COMPLEX_TASK classification
    # 2. planner        → returns the dependency plan
    mock_ask_llm.side_effect = [
        json.dumps({"classification": "COMPLEX_TASK"}),
        json.dumps(
            {
                "sub_tasks": [
                    {
                        "id": "1",
                        "agent_type": "general",
                        "description": "Task 1",
                        "depends_on": [],
                        "status": "pending",
                    },
                    {
                        "id": "2",
                        "agent_type": "general",
                        "description": "Task 2",
                        "depends_on": ["1"],
                        "status": "pending",
                    },
                ]
            }
        ),
    ]

    with patch("tasks.decomposition.rabbitmq_instance.create_queue"):
        first_agent, first_action, final_answer, remaining = select_agent_for_task(
            "Do multiple tasks", db_session
        )

    # First subtask must be returned ready-to-dispatch and remaining actions
    # must be queued for the existing chain mechanism. ``final_answer`` must
    # stay None because we are NOT short-circuiting to a direct response.
    assert first_agent in (agent_id1, agent_id2)
    assert first_action == "Task 1"
    assert final_answer is None
    assert len(remaining) == 1
    assert remaining[0][1] == "Task 2"


def test_select_agent_for_task_complex_with_unparseable_plan_falls_back(
    mock_ask_llm, db_session: Session
):
    """Planner failure on a COMPLEX_TASK must surface ``(None, None, None, [])``.

    Lets downstream callers reach their remaining fallback paths (skill-match,
    catch-all general agent) so we always answer the user with *something*
    rather than silently dropping the task.
    """
    create_agent(
        f"FallbackAgent_{uuid.uuid4().hex[:8]}",
        ["test"],
        "Some agent",
        db_session,
        AgentTypes.GENERAL,
    )
    mock_ask_llm.side_effect = [
        json.dumps({"classification": "COMPLEX_TASK"}),
        "this is not valid json",
    ]
    with patch("tasks.decomposition.rabbitmq_instance.create_queue"):
        result = select_agent_for_task("Do something complex", db_session)
    assert result == (None, None, None, [])


# ---------- Tests: insert_new_task ----------


def test_insert_new_task_creates_task_and_result(
    db_session: Session, sample_conversation
):
    """Test that insert_new_task creates both Task and TaskResult."""
    task_id = insert_new_task(
        conversation_id=sample_conversation,
        agent_id="agent_001",
        query="Test query",
        history=[],
        future_actions=[],
        db=db_session,
    )

    assert task_id is not None

    # Verify task was created
    task = db_session.query(Task).filter(Task.id == task_id).first()
    assert task is not None
    assert task.query == "Test query"
    assert task.agent_id == "agent_001"
    assert task.status == "running"

    # Verify task result was created
    result = db_session.query(TaskResult).filter(TaskResult.task_id == task_id).first()
    assert result is not None
    assert result.history == []
    assert result.future_actions == []


def test_insert_new_task_returns_none_on_error(db_session: Session):
    """Test that insert_new_task returns None on database error."""
    # Try to insert with invalid conversation_id
    # Since SQLite in-memory doesn't enforce FKs by default in SQLAlchemy session
    # unless PRAGMA foreign_keys=ON is set, we will mock the session to raise an error
    # to test the exception handling logic.
    mock_db = MagicMock()
    mock_db.commit.side_effect = Exception("DB Error")

    task_id = insert_new_task(
        conversation_id=99999,  # Non-existent
        agent_id="agent_001",
        query="Test query",
        history=[],
        future_actions=[],
        db=mock_db,
    )

    assert task_id is None


# ---------- Tests: validating_task_results ----------


def test_validating_task_results_updates_task(db_session: Session, sample_conversation):
    """Test that validating_task_results updates the task result."""
    # Create a task first
    task_id = insert_new_task(
        conversation_id=sample_conversation,
        agent_id="agent_001",
        query="Test query",
        history=[],
        future_actions=[],
        db=db_session,
    )

    # Update the result
    validating_task_results(
        task_id=task_id,
        task_result="Result of the task",
        db=db_session,
    )

    # Verify task was updated
    task = db_session.query(Task).filter(Task.id == task_id).first()
    assert task.status == "completed"

    result = db_session.query(TaskResult).filter(TaskResult.task_id == task_id).first()
    assert result.result_data == "Result of the task"
    assert len(result.history) > 0


def test_validating_task_results_raises_on_not_found(db_session: Session):
    """Test that validating_task_results raises HTTPException for non-existent task."""
    from fastapi import HTTPException

    with pytest.raises(HTTPException):
        validating_task_results(
            task_id="nonexistent",
            task_result="Result",
            db=db_session,
        )
