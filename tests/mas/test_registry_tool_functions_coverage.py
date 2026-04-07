from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from agents.registry_tool_functions import (
    _batch_update_agent_status_internal, _get_all_agents_internal,
    _is_agent_recently_alive, _update_alive_agent_status_internal,
    _update_dead_agent_status_internal, create_agent, delete_agent,
    get_agent_details, get_agent_id, get_available_agents,
    update_active_status, update_alive_agent_status, update_dead_agent_status)
from db.models import AgentTypes


def test_get_all_agents_internal_exception():
    mock_db = MagicMock()
    mock_db.query.side_effect = Exception("DB Error")

    result = _get_all_agents_internal(mock_db)
    assert result == []


def test_update_alive_agent_status_internal_exception():
    mock_db = MagicMock()
    mock_db.query.side_effect = Exception("DB Error")

    result = _update_alive_agent_status_internal("agent-1", mock_db)
    assert result is False
    mock_db.rollback.assert_called_once()


def test_update_dead_agent_status_internal_exception():
    mock_db = MagicMock()
    mock_db.query.side_effect = Exception("DB Error")

    result = _update_dead_agent_status_internal("agent-1", mock_db)
    assert result is False
    mock_db.rollback.assert_called_once()


def test_batch_update_agent_status_internal_exception():
    mock_db = MagicMock()
    mock_db.query.side_effect = Exception("DB Error")

    result = _batch_update_agent_status_internal({"agent-1": "active"}, mock_db)
    assert result is False
    mock_db.rollback.assert_called_once()


def test_create_agent_exception():
    mock_db = MagicMock()
    mock_db.add.side_effect = Exception("DB Error")

    result = create_agent("Agent 1", [], "Desc", mock_db, AgentTypes.GENERAL)
    assert result == (None, None)
    mock_db.rollback.assert_called_once()


def test_delete_agent_exception():
    mock_db = MagicMock()
    mock_db.get.side_effect = Exception("DB Error")

    result = delete_agent("agent-1", mock_db)
    assert result is False
    mock_db.rollback.assert_called_once()


def test_get_agent_details_exception():
    mock_db = MagicMock()
    mock_db.query.side_effect = Exception("DB Error")

    result = get_agent_details("agent-1", mock_db)
    assert result == (None, None, None, None, None, None, None)


def test_update_alive_agent_status_exception():
    mock_db = MagicMock()
    mock_db.query.side_effect = Exception("DB Error")

    result = update_alive_agent_status("agent-1", mock_db)
    assert result is False
    mock_db.rollback.assert_called_once()


def test_update_dead_agent_status_exception():
    mock_db = MagicMock()
    mock_db.query.side_effect = Exception("DB Error")

    result = update_dead_agent_status("agent-1", mock_db)
    assert result is False
    mock_db.rollback.assert_called_once()


def test_update_active_status_exception():
    mock_db = MagicMock()
    mock_db.query.side_effect = Exception("DB Error")

    result = update_active_status("agent-1", mock_db)
    assert result is False
    mock_db.rollback.assert_called_once()


def test_get_agent_id_exception():
    mock_db = MagicMock()
    mock_db.query.side_effect = Exception("DB Error")

    result = get_agent_id("Agent 1", mock_db)
    assert result is None


def test_is_agent_recently_alive_exception():
    mock_agent = MagicMock()
    mock_agent.last_heartbeat = datetime.now(timezone.utc)

    with patch("agents.registry_tool_functions.datetime") as mock_datetime:
        mock_datetime.now.side_effect = Exception("Error")
        result = _is_agent_recently_alive(mock_agent)
        assert result is False


def test_get_available_agents_exception():
    mock_db = MagicMock()
    mock_db.query.side_effect = Exception("DB Error")

    result = get_available_agents(mock_db)
    assert result == []


from unittest.mock import PropertyMock
