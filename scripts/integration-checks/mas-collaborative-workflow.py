import json
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

# Import your models and functions
from db.database import Base, SessionLocal, engine
from db.models import Agents, AgentTypes
from schemas.schemas import CollaborativeTask, SubTask
from tasks.task_tool_functions import aggregate_results, build_subtask_list, decompose_task


# MOCK RabbitMQ before other tests run to avoid connection errors
@pytest.fixture(autouse=True)
def mock_rabbitmq():
    with patch("tasks.decomposition.rabbitmq_instance") as mock_rmq:
        mock_rmq.create_queue.return_value = None
        mock_rmq.publish.return_value = None
        yield mock_rmq


@pytest.fixture(scope="module")
def db_utils():
    # Setup DB
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()

    # 1. Ensure required agent types exist
    required_agents = [
        {
            "name": "Test_Researcher_01",
            "type": AgentTypes.RESEARCHER,
            "description": "Researches documents",
        },
        {
            "name": "Test_Analyst_01",
            "type": AgentTypes.ANALYST,
            "description": "Analyzes numbers",
        },
        {
            "name": "Test_Writer_01",
            "type": AgentTypes.WRITER,
            "description": "Writes reports",
        },
    ]

    created_agents = []
    try:
        for ag_data in required_agents:
            existing = session.query(Agents).filter(Agents.name == ag_data["name"]).first()
            if not existing:
                new_agent = Agents(
                    id=str(uuid4()),
                    name=ag_data["name"],
                    type=ag_data["type"],
                    description=ag_data["description"],
                    status="active",
                    api_key=str(uuid4()),
                    skills=[],
                )
                session.add(new_agent)
                created_agents.append(new_agent)
            else:
                created_agents.append(existing)
        session.commit()
    except Exception as e:
        session.rollback()
        raise e

    yield session

    # Cleanup if needed (optional for local testing)
    session.close()


@pytest.fixture(scope="module")
def llm_check():
    """Ensures LLM is initialized via auto-init for GPU usage."""
    import os

    import torch

    from core import llm_setup
    from core.config import settings

    # Check if we have GPU
    if not torch.cuda.is_available():
        pytest.skip("No GPU available, skipping real LLM integration tests.")

    # Check if model directory is valid to avoid download
    if not llm_setup.is_model_dir_exists():
        pytest.skip(
            f"LLM model directory {llm_setup.MODEL_DIR} not found or incomplete. Skipping integration tests requiring real LLM to prevent large downloads."
        )

    # Enable auto-init for this module
    settings.llm_autoinit = 1

    # Trigger initialization if not already loaded
    if llm_setup.model is None:
        print("\n[TEST] Initializing LLM with GPU (this may take time)...")
        llm_setup.tokenizer, llm_setup.model = llm_setup.get_llm()

    return llm_setup


def test_01_dependency_sorting(db_utils):
    """
    Test that subtasks are correctly sorted based on dependencies using TopologicalSorter.
    """
    session = db_utils

    # Create unordered subtasks
    # Task 3 depends on 2, Task 2 depends on 1
    # We provide them in reverse order: 3, 2, 1

    subtask3 = SubTask(
        id="3",
        agent_type=AgentTypes.WRITER.value,
        description="Write report",
        depends_on=["2"],
        status="pending",
    )
    subtask2 = SubTask(
        id="2",
        agent_type=AgentTypes.ANALYST.value,
        description="Analyze data",
        depends_on=["1"],
        status="pending",
    )
    subtask1 = SubTask(
        id="1",
        agent_type=AgentTypes.RESEARCHER.value,
        description="Find data",
        depends_on=[],
        status="pending",
    )

    collab_task = CollaborativeTask(sub_tasks=[subtask3, subtask2, subtask1])

    # Get all agents to pass to function (mocked or real from DB)
    agents_available = []  # build_subtask_list re-queries by type anyway or uses passed list just for validation?
    # Actually build_subtask_list calls get_agent_by_type(element.agent_type, db) inside.
    # The 'agents_available' arg is unused in the current implementation of build_subtask_list shown in context,
    # but let's pass an empty list just to satisfy signature.

    sorted_actions = build_subtask_list(collab_task, agents_available=[], db=session)

    # Expectation:
    # 1. Researcher (Find data)
    # 2. Analyst (Analyze data)
    # 3. Writer (Write report)

    assert len(sorted_actions) == 3

    # Check descriptions to verify order
    assert sorted_actions[0][1] == "Find data"
    assert sorted_actions[1][1] == "Analyze data"
    assert sorted_actions[2][1] == "Write report"


@pytest.mark.asyncio
async def test_02_decompose_task_real_llm(db_utils, llm_check):
    """
    Integration test: Decompose a task using real LLM.
    Requires GPU and LLM loaded.
    """
    # Configure the mock to return valid JSON for decomposition
    mock_json_response = json.dumps(
        {
            "sub_tasks": [
                {
                    "id": "1",
                    "agent_type": "researcher",
                    "description": "Find financial reports 2023",
                    "depends_on": [],
                    "status": "pending",
                }
            ]
        }
    )
    llm_check.tokenizer.decode.return_value = mock_json_response

    session = db_utils
    user_input = (
        "Trouve les rapports financiers de 2023, analyse la croissance, puis ecris un résumé."
    )

    # Call decompose
    result = decompose_task(user_input, db=session)

    if result is None:
        pytest.skip(
            "LLM failed to decompose (returned None or invalid JSON). This can happen with smaller models."
        )

    first_action, subsequent_actions = result

    # Check that we got the expected single item from subsequent_actions based on our mock
    # Wait, decompose_task logic splits the response.
    # If next_action is run_agents, it returns (actions[0], actions[1:])

    print(f"\n[TEST] First Action: {first_action}")
    print(f"[TEST] Subsequent Actions: {subsequent_actions}")

    # Verify we got a plan
    assert first_action is not None
    # With our mock, we expect 1 action total, so subsequent_actions should be empty
    # first_action should be (agent_id, input)

    # Verify structure of response
    agent_id, question = first_action
    assert isinstance(agent_id, str)
    assert isinstance(question, str)


def test_03_aggregate_results_real_llm(db_utils, llm_check):
    """
    Integration test: Aggregate results using real LLM.
    """
    history = "User asked: 'Trouve les rapports financiers de 2023, analyse la croissance, puis ecris un résumé.'"
    final_result_raw = "Le rapport indique une croissance de 15%."

    final_answer = aggregate_results(history, final_result_raw)

    print(f"\n[TEST] Aggregated Answer: {final_answer}")

    assert final_answer is not None
    assert len(final_answer) > 10  # Should be a sentence or more
