"""
Tests for agent registry tool functions (Database-based implementation)

Tests the new database-backed agent registry functions:
- create_agent, delete_agent
- get_agent_details, get_all_agents, get_agent_id
- update_alive_agent_status, update_dead_agent_status
- _is_agent_recently_alive
- get_available_agents
"""

import datetime as dt
from unittest.mock import MagicMock

import pytest
from sqlalchemy.orm import Session

from agents.registry_tool_functions import (
    _batch_update_agent_status_internal, _get_all_agents_internal,
    _is_agent_recently_alive, _update_alive_agent_status_internal,
    _update_dead_agent_status_internal, create_agent, delete_agent,
    get_agent_details, get_agent_id, get_all_agents, get_available_agents,
    update_active_status, update_alive_agent_status, update_dead_agent_status)
from db.database import Base, SessionLocal, engine
from db.models import Agents

# ---------- Fixtures ----------


@pytest.fixture(scope="function")
def db_session():
    """Create a fresh database session for each test."""
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    yield session
    session.query(Agents).delete()
    session.commit()
    session.close()
    # Base.metadata.drop_all(bind=engine)


# ---------- Tests: create_agent ----------


def test_create_agent_returns_uuid_and_sets_fields(db_session: Session):
    """Test that create_agent returns a valid UUID and sets all fields."""
    agent_id, _ = create_agent(
        "Alice", ["nlp", "retrieval"], "Agent to retrieve informations", db_session
    )

    assert agent_id is not None
    assert isinstance(agent_id, str)

    # Verify agent was created in database
    agent = db_session.query(Agents).filter(Agents.id == agent_id).first()
    assert agent is not None
    assert agent.name == "Alice"
    assert agent.skills == ["nlp", "retrieval"]
    assert agent.status == "active"
    assert agent.description == "Agent to retrieve informations"


def test_create_multiple_agents_unique_ids(db_session: Session):
    """Test that multiple agents have unique IDs."""
    ids = set()
    for i in range(5):
        agent_id, _ = create_agent(f"agent{i}", [], "", db_session)
        ids.add(agent_id)

    assert len(ids) == 5


def test_create_agent_allows_empty_skills(db_session: Session):
    """Test that agents can be created with no skills."""
    agent_id, _ = create_agent("NoSkills", [], "", db_session)
    agent = db_session.query(Agents).filter(Agents.id == agent_id).first()
    assert agent.skills == []


# ---------- Tests: get_all_agents ----------


def test_get_all_agents_reflects_created_agents(db_session: Session):
    """Test that get_all_agents returns all created agents."""
    a1, _ = create_agent("A1", [], "", db_session)
    a2, _ = create_agent("A2", ["x"], "", db_session)

    all_agents = get_all_agents(db_session)

    assert len(all_agents) == 2
    agent_ids = [a.id for a in all_agents]
    assert a1 in agent_ids
    assert a2 in agent_ids


# ---------- Tests: get_agent_details ----------


def test_get_agent_details_found_returns_expected_tuple(db_session: Session):
    """Test that get_agent_details returns all required information."""
    agent_id, _ = create_agent(
        "Bob", ["vision"], "Agent to retrieve informations", db_session
    )

    result = get_agent_details(agent_id, db_session)

    assert isinstance(result, tuple)
    assert len(result) == 7
    rid, name, skills, status, heartbeat, description, created_at = result

    assert rid == agent_id
    assert name == "Bob"
    assert skills == ["vision"]
    assert status == "active"
    assert description == "Agent to retrieve informations"
    assert isinstance(heartbeat, dt.datetime)
    assert isinstance(created_at, dt.datetime)


def test_get_agent_details_not_found_returns_nones(db_session: Session):
    """Test that get_agent_details returns None values for non-existent agent."""
    result = get_agent_details("nonexistent-id", db_session)

    assert isinstance(result, tuple)
    assert len(result) == 7
    assert all(x is None for x in result)


# ---------- Tests: update_alive_agent_status ----------


def test_update_alive_agent_status_updates_timestamp_and_status(db_session: Session):
    """Test that update_alive_agent_status updates status and heartbeat."""
    agent_id, _ = create_agent("Carol", ["nlp"], "", db_session)

    # Get initial heartbeat
    agent_before = db_session.query(Agents).filter(Agents.id == agent_id).first()
    initial_heartbeat = agent_before.last_heartbeat

    # Set to inactive
    agent_before.status = "inactive"
    db_session.commit()

    # Update status
    updated = update_alive_agent_status(agent_id, db_session)

    assert updated is True

    # Verify changes
    agent_after = db_session.query(Agents).filter(Agents.id == agent_id).first()
    assert agent_after.status == "active"
    assert agent_after.last_heartbeat >= initial_heartbeat


def test_update_alive_agent_status_returns_false_if_missing(db_session: Session):
    """Test that update_alive_agent_status returns False for non-existent agent."""
    result = update_alive_agent_status("nonexistent-id", db_session)
    assert result is False


# ---------- Tests: update_dead_agent_status ----------


def test_update_dead_agent_status_sets_inactive(db_session: Session):
    """Test that update_dead_agent_status sets status to inactive."""
    agent_id, _ = create_agent("Dave", [], "", db_session)

    updated = update_dead_agent_status(agent_id, db_session)

    assert updated is True

    agent = db_session.query(Agents).filter(Agents.id == agent_id).first()
    assert agent.status == "inactive"


def test_update_dead_agent_status_returns_false_if_missing(db_session: Session):
    """Test that update_dead_agent_status returns False for non-existent agent."""
    result = update_dead_agent_status("nonexistent-id", db_session)
    assert result is False


# ---------- Tests: delete_agent ----------


def test_delete_agent_success_removes_entry(db_session: Session):
    """Test that delete_agent removes the agent."""
    agent_id, _ = create_agent("Eve", [], "", db_session)
    assert db_session.query(Agents).filter(Agents.id == agent_id).first() is not None

    ok = delete_agent(agent_id, db_session)

    assert ok is True
    assert db_session.query(Agents).filter(Agents.id == agent_id).first() is None


def test_delete_agent_returns_false_when_not_found(db_session: Session):
    """Test that delete_agent returns False for non-existent agent."""
    result = delete_agent("nonexistent-id", db_session)
    assert result is False


# ---------- Tests: get_agent_id ----------


def test_get_agent_id_returns_matching_id(db_session: Session):
    """Test that get_agent_id returns the correct agent ID by name."""
    agent_id, _ = create_agent(
        "Grace", ["nlp"], "Agent to retrieve informations", db_session
    )

    found_id = get_agent_id("Grace", db_session)

    assert found_id == agent_id


def test_get_agent_id_returns_none_when_not_found(db_session: Session):
    """Test that get_agent_id returns None for non-existent name."""
    create_agent("Heidi", [], "", db_session)

    result = get_agent_id("NotExisting", db_session)

    assert result is None


# ---------- Tests: _is_agent_recently_alive ----------


def test_is_agent_recently_alive_with_recent_heartbeat(db_session: Session):
    """Test that recently heartbeat agent is considered alive."""
    agent_id, _ = create_agent("RecentAgent", ["test"], "Test", db_session)
    agent = db_session.query(Agents).filter(Agents.id == agent_id).first()

    result = _is_agent_recently_alive(agent, max_age_seconds=90)

    assert result is True


def test_is_agent_recently_alive_with_old_heartbeat(db_session: Session):
    """Test that old heartbeat agent is considered dead."""
    agent_id, _ = create_agent("OldAgent", ["test"], "Test", db_session)
    agent = db_session.query(Agents).filter(Agents.id == agent_id).first()

    # Set heartbeat to old time
    agent.last_heartbeat = dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=200)
    db_session.commit()

    result = _is_agent_recently_alive(agent, max_age_seconds=90)

    assert result is False


def test_is_agent_recently_alive_returns_false_if_no_heartbeat(db_session: Session):
    """Test that agent with no heartbeat is considered dead."""
    agent = Agents(
        id="test-id",
        name="NoHeartbeat",
        skills=[],
        status="active",
        last_heartbeat=None,
    )

    result = _is_agent_recently_alive(agent)

    assert result is False


def test_is_agent_recently_alive_returns_false_if_invalid_heartbeat():
    """Test that agent with invalid heartbeat type is considered dead."""
    # Create a mock object that raises an exception when accessing heartbeat
    agent_info = MagicMock()
    agent_info.last_heartbeat = "not-a-datetime"

    result = _is_agent_recently_alive(agent_info)

    assert result is False


# ---------- Tests: get_available_agents ----------


def test_get_available_agents_returns_recently_alive(db_session: Session):
    """Test that get_available_agents returns only recently alive agents."""
    # Create one active agent
    agent1_id, _ = create_agent("Active", ["test"], "Active agent", db_session)

    # Create one inactive agent (by not updating heartbeat)
    agent2_id, _ = create_agent("Inactive", ["test"], "Inactive agent", db_session)
    agent2 = db_session.query(Agents).filter(Agents.id == agent2_id).first()
    agent2.last_heartbeat = dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=200)
    db_session.commit()

    available = get_available_agents(db_session)

    # Should only return the active agent
    assert len(available) == 1
    assert available[0][0] == agent1_id
    assert available[0][1] == "Active"


def test_get_available_agents_returns_empty_list_when_no_agents(db_session: Session):
    """Test that get_available_agents returns empty list when no agents."""
    available = get_available_agents(db_session)

    assert available == []


def test_get_available_agents_returns_agent_info(db_session: Session):
    """Test that get_available_agents returns correct agent information."""
    agent_id, _ = create_agent(
        "TestAgent", ["skill1", "skill2"], "Test description", db_session
    )

    available = get_available_agents(db_session)

    assert len(available) == 1
    agent_tuple = available[0]
    assert agent_tuple[0] == agent_id
    assert agent_tuple[1] == "TestAgent"
    assert agent_tuple[2] == "Test description"


# ---------- Tests: Internal Functions ----------


def test_get_all_agents_internal(db_session: Session):
    """Test internal get_all_agents function."""
    create_agent("InternalAgent", [], "", db_session)
    agents = _get_all_agents_internal(db_session)
    assert len(agents) == 1
    assert agents[0].name == "InternalAgent"


def test_get_all_agents_internal_error(db_session: Session):
    """Test internal get_all_agents handles errors gracefully."""
    # Mock db session to raise exception
    mock_db = MagicMock()
    mock_db.query.side_effect = Exception("DB Error")

    agents = _get_all_agents_internal(mock_db)
    assert agents == []


def test_update_alive_agent_status_internal(db_session: Session):
    """Test internal update_alive_agent_status function."""
    agent_id, _ = create_agent("AliveInternal", [], "", db_session)

    # Set to inactive first
    agent = db_session.query(Agents).filter(Agents.id == agent_id).first()
    agent.status = "inactive"
    db_session.commit()

    result = _update_alive_agent_status_internal(agent_id, db_session)
    assert result is True

    agent = db_session.query(Agents).filter(Agents.id == agent_id).first()
    assert agent.status == "active"


def test_update_alive_agent_status_internal_not_found(db_session: Session):
    """Test internal update_alive_agent_status returns False if agent not found."""
    result = _update_alive_agent_status_internal("missing", db_session)
    assert result is False


def test_update_alive_agent_status_internal_error(db_session: Session):
    """Test internal update_alive_agent_status handles errors."""
    mock_db = MagicMock()
    mock_db.query.side_effect = Exception("DB Error")

    result = _update_alive_agent_status_internal("id", mock_db)
    assert result is False
    mock_db.rollback.assert_called_once()


def test_update_dead_agent_status_internal(db_session: Session):
    """Test internal update_dead_agent_status function."""
    agent_id, _ = create_agent("DeadInternal", [], "", db_session)

    result = _update_dead_agent_status_internal(agent_id, db_session)
    assert result is True

    agent = db_session.query(Agents).filter(Agents.id == agent_id).first()
    assert agent.status == "dead"


def test_update_dead_agent_status_internal_not_found(db_session: Session):
    """Test internal update_dead_agent_status returns False if agent not found."""
    result = _update_dead_agent_status_internal("missing", db_session)
    assert result is False


def test_update_dead_agent_status_internal_error(db_session: Session):
    """Test internal update_dead_agent_status handles errors."""
    mock_db = MagicMock()
    mock_db.query.side_effect = Exception("DB Error")

    result = _update_dead_agent_status_internal("id", mock_db)
    assert result is False
    mock_db.rollback.assert_called_once()


def test_batch_update_agent_status_internal(db_session: Session):
    """Test batch update of agent statuses."""
    a1, _ = create_agent("Batch1", [], "", db_session)
    a2, _ = create_agent("Batch2", [], "", db_session)

    statuses = {a1: "inactive", a2: "dead"}
    result = _batch_update_agent_status_internal(statuses, db_session)

    assert result is True

    agent1 = db_session.query(Agents).filter(Agents.id == a1).first()
    agent2 = db_session.query(Agents).filter(Agents.id == a2).first()

    assert agent1.status == "inactive"
    assert agent2.status == "dead"


def test_batch_update_agent_status_internal_error(db_session: Session):
    """Test batch update handles errors."""
    mock_db = MagicMock()
    mock_db.query.side_effect = Exception("DB Error")

    result = _batch_update_agent_status_internal({"id": "status"}, mock_db)
    assert result is False
    mock_db.rollback.assert_called_once()


# ---------- Tests: Error Handling in Public Functions ----------


def test_create_agent_error_handling(db_session: Session):
    """Test create_agent handles DB errors."""
    mock_db = MagicMock()
    mock_db.add.side_effect = Exception("DB Error")

    result = create_agent("ErrorAgent", [], "", mock_db)
    assert result == (None, None)
    mock_db.rollback.assert_called_once()


def test_delete_agent_error_handling(db_session: Session):
    """Test delete_agent handles DB errors."""
    mock_db = MagicMock()
    mock_db.get.side_effect = Exception("DB Error")

    result = delete_agent("id", mock_db)
    assert result is False
    mock_db.rollback.assert_called_once()


def test_get_agent_details_error_handling(db_session: Session):
    """Test get_agent_details handles DB errors."""
    mock_db = MagicMock()
    mock_db.query.side_effect = Exception("DB Error")

    result = get_agent_details("id", mock_db)
    assert result == (None, None, None, None, None, None, None)


def test_update_alive_agent_status_error_handling(db_session: Session):
    """Test update_alive_agent_status handles DB errors."""
    mock_db = MagicMock()
    mock_db.query.side_effect = Exception("DB Error")

    result = update_alive_agent_status("id", mock_db)
    assert result is False
    mock_db.rollback.assert_called_once()


def test_update_dead_agent_status_error_handling(db_session: Session):
    """Test update_dead_agent_status handles DB errors."""
    mock_db = MagicMock()
    mock_db.query.side_effect = Exception("DB Error")

    result = update_dead_agent_status("id", mock_db)
    assert result is False
    mock_db.rollback.assert_called_once()


def test_update_active_status(db_session: Session):
    """Test update_active_status function."""
    agent_id, _ = create_agent("ActiveStatus", [], "", db_session)

    # Set to inactive
    agent = db_session.query(Agents).filter(Agents.id == agent_id).first()
    agent.status = "inactive"
    db_session.commit()

    result = update_active_status(agent_id, db_session)
    assert result is True

    agent = db_session.query(Agents).filter(Agents.id == agent_id).first()
    assert agent.status == "active"


def test_update_active_status_not_found(db_session: Session):
    """Test update_active_status returns False if not found."""
    result = update_active_status("missing", db_session)
    assert result is False


def test_update_active_status_error(db_session: Session):
    """Test update_active_status handles errors."""
    mock_db = MagicMock()
    mock_db.query.side_effect = Exception("DB Error")

    result = update_active_status("id", mock_db)
    assert result is False
    mock_db.rollback.assert_called_once()


def test_get_agent_id_error(db_session: Session):
    """Test get_agent_id handles errors."""
    mock_db = MagicMock()
    mock_db.query.side_effect = Exception("DB Error")

    result = get_agent_id("name", mock_db)
    assert result is None


def test_get_available_agents_error(db_session: Session):
    """Test get_available_agents handles errors."""
    mock_db = MagicMock()
    mock_db.query.side_effect = Exception("DB Error")

    result = get_available_agents(mock_db)
    assert result == []
