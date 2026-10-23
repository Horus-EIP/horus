"""
Test Suite: Agent Status Update Functions

Tests for internal agent status update functions:
- _update_alive_agent_status_internal()
- _update_dead_agent_status_internal()
- _batch_update_agent_status_internal()
"""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.orm import Session

from agents.registry_tool_functions import (
    _batch_update_agent_status_internal,
    _update_alive_agent_status_internal,
    _update_dead_agent_status_internal,
)
from db.models import Agents


class TestUpdateAliveAgentStatusInternal:
    """Test suite for _update_alive_agent_status_internal function"""

    def test_update_alive_agent_status_success(self, caplog):
        """Test successful update of agent heartbeat to active"""
        agent_id = str(uuid.uuid4())

        # Create mock agent
        mock_agent = MagicMock(spec=Agents)
        mock_agent.id = agent_id
        mock_agent.status = "inactive"
        mock_agent.last_heartbeat = datetime.now(timezone.utc) - timedelta(minutes=5)

        # Create mock database session
        mock_db = MagicMock(spec=Session)
        mock_db.query.return_value.filter.return_value.first.return_value = mock_agent

        # Execute function
        result = _update_alive_agent_status_internal(agent_id, mock_db)

        # Assertions
        assert result is True
        assert mock_agent.status == "active"
        assert mock_db.commit.called
        assert any(
            "Agent heartbeat updated successfully" in record.message for record in caplog.records
        )

    def test_update_alive_agent_status_agent_not_found(self, caplog):
        """Test when agent is not found"""
        agent_id = str(uuid.uuid4())

        # Mock database session with no agent found
        mock_db = MagicMock(spec=Session)
        mock_db.query.return_value.filter.return_value.first.return_value = None

        # Execute function
        result = _update_alive_agent_status_internal(agent_id, mock_db)

        # Assertions
        assert result is False
        assert not mock_db.commit.called
        assert any(
            "Agent not found for heartbeat update" in record.message for record in caplog.records
        )

    def test_update_alive_agent_status_database_error(self, caplog):
        """Test handling of database errors during heartbeat update"""
        agent_id = str(uuid.uuid4())

        # Create mock agent
        mock_agent = MagicMock(spec=Agents)
        mock_agent.id = agent_id

        # Mock database session that raises exception on commit
        mock_db = MagicMock(spec=Session)
        mock_db.query.return_value.filter.return_value.first.return_value = mock_agent
        mock_db.commit.side_effect = Exception("Database connection error")

        # Execute function
        result = _update_alive_agent_status_internal(agent_id, mock_db)

        # Assertions
        assert result is False
        assert mock_db.rollback.called
        assert any("Error updating agent heartbeat" in record.message for record in caplog.records)

    def test_update_alive_agent_status_updates_timestamp(self):
        """Test that last_heartbeat is updated to current time"""
        agent_id = str(uuid.uuid4())
        before_time = datetime.now(timezone.utc)

        # Create mock agent
        mock_agent = MagicMock(spec=Agents)
        mock_agent.id = agent_id
        old_heartbeat = before_time - timedelta(minutes=10)
        mock_agent.last_heartbeat = old_heartbeat

        # Mock database session
        mock_db = MagicMock(spec=Session)
        mock_db.query.return_value.filter.return_value.first.return_value = mock_agent

        # Execute function
        result = _update_alive_agent_status_internal(agent_id, mock_db)

        after_time = datetime.now(timezone.utc)

        # Assertions
        assert result is True
        # Verify heartbeat was updated (not equal to old value)
        assert mock_agent.last_heartbeat != old_heartbeat


class TestUpdateDeadAgentStatusInternal:
    """Test suite for _update_dead_agent_status_internal function"""

    def test_update_dead_agent_status_success(self, caplog):
        """Test successful marking of agent as dead"""
        agent_id = str(uuid.uuid4())

        # Create mock agent
        mock_agent = MagicMock(spec=Agents)
        mock_agent.id = agent_id
        mock_agent.status = "active"
        mock_agent.last_heartbeat = datetime.now(timezone.utc) - timedelta(minutes=15)

        # Create mock database session
        mock_db = MagicMock(spec=Session)
        mock_db.query.return_value.filter.return_value.first.return_value = mock_agent

        # Execute function
        result = _update_dead_agent_status_internal(agent_id, mock_db)

        # Assertions
        assert result is True
        assert mock_agent.status == "dead"
        assert mock_db.commit.called
        assert any("Agent marked as dead" in record.message for record in caplog.records)

    def test_update_dead_agent_status_agent_not_found(self, caplog):
        """Test when agent is not found for marking as dead"""
        agent_id = str(uuid.uuid4())

        # Mock database session with no agent found
        mock_db = MagicMock(spec=Session)
        mock_db.query.return_value.filter.return_value.first.return_value = None

        # Execute function
        result = _update_dead_agent_status_internal(agent_id, mock_db)

        # Assertions
        assert result is False
        assert not mock_db.commit.called
        assert any(
            "Agent not found for marking dead" in record.message for record in caplog.records
        )

    def test_update_dead_agent_status_database_error(self, caplog):
        """Test handling of database errors when marking agent as dead"""
        agent_id = str(uuid.uuid4())

        # Create mock agent
        mock_agent = MagicMock(spec=Agents)
        mock_agent.id = agent_id
        mock_agent.last_heartbeat = datetime.now(timezone.utc) - timedelta(minutes=20)

        # Mock database session that raises exception
        mock_db = MagicMock(spec=Session)
        mock_db.query.return_value.filter.return_value.first.return_value = mock_agent
        mock_db.commit.side_effect = Exception("Database transaction failed")

        # Execute function
        result = _update_dead_agent_status_internal(agent_id, mock_db)

        # Assertions
        assert result is False
        assert mock_db.rollback.called
        assert any("Error updating agent status" in record.message for record in caplog.records)

    def test_update_dead_agent_status_logs_heartbeat_age(self, caplog):
        """Test that the age of last heartbeat is logged"""
        agent_id = str(uuid.uuid4())
        heartbeat_age_seconds = 900  # 15 minutes

        # Create mock agent with specific heartbeat time
        mock_agent = MagicMock(spec=Agents)
        mock_agent.id = agent_id
        mock_agent.status = "active"
        mock_agent.last_heartbeat = datetime.now(timezone.utc) - timedelta(
            seconds=heartbeat_age_seconds
        )

        # Mock database session
        mock_db = MagicMock(spec=Session)
        mock_db.query.return_value.filter.return_value.first.return_value = mock_agent

        # Execute function
        result = _update_dead_agent_status_internal(agent_id, mock_db)

        # Assertions
        assert result is True
        # Verify that a log message was created with heartbeat age information
        assert any(
            "Agent marked as dead" in record.message and "ago" in record.message
            for record in caplog.records
        )


class TestBatchUpdateAgentStatusInternal:
    """Test suite for _batch_update_agent_status_internal function"""

    def test_batch_update_agent_status_success(self, caplog):
        """Test successful batch update of multiple agents"""
        agent_ids = [str(uuid.uuid4()) for _ in range(3)]
        agent_statuses = {
            agent_ids[0]: "active",
            agent_ids[1]: "dead",
            agent_ids[2]: "inactive",
        }

        # Create mock agents
        mock_agents = {}
        for agent_id in agent_ids:
            mock_agent = MagicMock(spec=Agents)
            mock_agent.id = agent_id
            mock_agents[agent_id] = mock_agent

        # Mock database session
        mock_db = MagicMock(spec=Session)

        def mock_query_filter(agent_id):
            return mock_agents.get(agent_id)

        mock_db.query.return_value.filter.return_value.first.side_effect = lambda: (
            mock_agents.get(
                [k for k in mock_agents.keys()][
                    len(mock_db.query.return_value.filter.return_value.first.call_args_list) - 1
                ]
            )
            if mock_db.query.return_value.filter.return_value.first.call_count > 0
            else None
        )

        # Simplified approach: manually set up the mock
        agents_found = list(mock_agents.values())
        mock_db.query.return_value.filter.return_value.first.side_effect = agents_found

        # Execute function
        result = _batch_update_agent_status_internal(agent_statuses, mock_db)

        # Assertions
        assert result is True
        assert mock_db.commit.called
        assert any(
            f"Batch updated {len(agent_statuses)} agents" in record.message
            for record in caplog.records
        )

    def test_batch_update_agent_status_empty_dict(self, caplog):
        """Test batch update with empty agent statuses dictionary"""
        agent_statuses = {}

        # Mock database session
        mock_db = MagicMock(spec=Session)

        # Execute function
        result = _batch_update_agent_status_internal(agent_statuses, mock_db)

        # Assertions
        assert result is True
        assert mock_db.commit.called
        assert any("Batch updated 0 agents" in record.message for record in caplog.records)

    def test_batch_update_agent_status_partial_agents_found(self, caplog):
        """Test batch update when only some agents are found"""
        agent_ids = [str(uuid.uuid4()) for _ in range(3)]
        agent_statuses = {
            agent_ids[0]: "active",
            agent_ids[1]: "dead",
            agent_ids[2]: "inactive",
        }

        # Create mock agents - only 2 of 3 exist
        mock_agent_1 = MagicMock(spec=Agents)
        mock_agent_1.id = agent_ids[0]
        mock_agent_2 = MagicMock(spec=Agents)
        mock_agent_2.id = agent_ids[1]

        agents_found = [mock_agent_1, mock_agent_2, None]  # Third agent not found

        # Mock database session
        mock_db = MagicMock(spec=Session)
        mock_db.query.return_value.filter.return_value.first.side_effect = agents_found

        # Execute function
        result = _batch_update_agent_status_internal(agent_statuses, mock_db)

        # Assertions
        assert result is True
        assert mock_db.commit.called
        # Verify that only found agents were updated
        assert mock_agent_1.status == "active"
        assert mock_agent_2.status == "dead"

    def test_batch_update_agent_status_database_error(self, caplog):
        """Test handling of database errors during batch update"""
        agent_ids = [str(uuid.uuid4()) for _ in range(2)]
        agent_statuses = {agent_ids[0]: "active", agent_ids[1]: "dead"}

        # Create mock agents
        mock_agent_1 = MagicMock(spec=Agents)
        mock_agent_1.id = agent_ids[0]
        mock_agent_2 = MagicMock(spec=Agents)
        mock_agent_2.id = agent_ids[1]

        # Mock database session that raises exception on commit
        mock_db = MagicMock(spec=Session)
        mock_db.query.return_value.filter.return_value.first.side_effect = [
            mock_agent_1,
            mock_agent_2,
        ]
        mock_db.commit.side_effect = Exception("Database write error")

        # Execute function
        result = _batch_update_agent_status_internal(agent_statuses, mock_db)

        # Assertions
        assert result is False
        assert mock_db.rollback.called
        assert any("Error batch updating agents" in record.message for record in caplog.records)

    def test_batch_update_agent_status_with_multiple_status_types(self, caplog):
        """Test batch update with various status values"""
        agent_ids = [str(uuid.uuid4()) for _ in range(4)]
        agent_statuses = {
            agent_ids[0]: "active",
            agent_ids[1]: "inactive",
            agent_ids[2]: "dead",
            agent_ids[3]: "paused",
        }

        # Create mock agents
        mock_agents = []
        for agent_id in agent_ids:
            mock_agent = MagicMock(spec=Agents)
            mock_agent.id = agent_id
            mock_agents.append(mock_agent)

        # Mock database session
        mock_db = MagicMock(spec=Session)
        mock_db.query.return_value.filter.return_value.first.side_effect = mock_agents

        # Execute function
        result = _batch_update_agent_status_internal(agent_statuses, mock_db)

        # Assertions
        assert result is True
        assert mock_db.commit.called
        # Verify each agent got the correct status
        assert mock_agents[0].status == "active"
        assert mock_agents[1].status == "inactive"
        assert mock_agents[2].status == "dead"
        assert mock_agents[3].status == "paused"

    def test_batch_update_agent_status_logs_status_changes(self, caplog):
        """Test that status changes are logged with agent details"""
        agent_ids = [str(uuid.uuid4()) for _ in range(2)]
        agent_statuses = {agent_ids[0]: "active", agent_ids[1]: "dead"}

        # Create mock agents
        mock_agent_1 = MagicMock(spec=Agents)
        mock_agent_1.id = agent_ids[0]
        mock_agent_2 = MagicMock(spec=Agents)
        mock_agent_2.id = agent_ids[1]

        # Mock database session
        mock_db = MagicMock(spec=Session)
        mock_db.query.return_value.filter.return_value.first.side_effect = [
            mock_agent_1,
            mock_agent_2,
        ]

        # Execute function
        result = _batch_update_agent_status_internal(agent_statuses, mock_db)

        # Assertions
        assert result is True
        # Verify that status changes are logged
        assert any(
            "Batch updated" in record.message and "Status changes" in record.message
            for record in caplog.records
        )


class TestAgentStatusUpdateIntegration:
    """Integration tests for agent status update functions"""

    def test_multiple_status_updates_sequence(self, caplog):
        """Test sequential updates: alive -> dead -> alive"""
        agent_id = str(uuid.uuid4())

        # Create mock agent
        mock_agent = MagicMock(spec=Agents)
        mock_agent.id = agent_id
        mock_agent.status = "inactive"
        mock_agent.last_heartbeat = datetime.now(timezone.utc)

        # Mock database session
        mock_db = MagicMock(spec=Session)
        mock_db.query.return_value.filter.return_value.first.return_value = mock_agent

        # Step 1: Mark as active
        result1 = _update_alive_agent_status_internal(agent_id, mock_db)
        assert result1 is True
        assert mock_agent.status == "active"

        # Step 2: Mark as dead
        result2 = _update_dead_agent_status_internal(agent_id, mock_db)
        assert result2 is True
        assert mock_agent.status == "dead"

        # Step 3: Mark as active again
        result3 = _update_alive_agent_status_internal(agent_id, mock_db)
        assert result3 is True
        assert mock_agent.status == "active"

    def test_concurrent_heartbeat_and_batch_updates(self):
        """Test that heartbeat updates and batch updates work independently"""
        agent_ids = [str(uuid.uuid4()) for _ in range(3)]

        # Create mock agents
        mock_agents = {}
        for agent_id in agent_ids:
            mock_agent = MagicMock(spec=Agents)
            mock_agent.id = agent_id
            mock_agent.status = "active"
            mock_agent.last_heartbeat = datetime.now(timezone.utc)
            mock_agents[agent_id] = mock_agent

        # Mock database session
        mock_db = MagicMock(spec=Session)

        # Simulate heartbeat update for agent 1
        mock_db.query.return_value.filter.return_value.first.return_value = mock_agents[
            agent_ids[0]
        ]
        result_heartbeat = _update_alive_agent_status_internal(agent_ids[0], mock_db)
        assert result_heartbeat is True

        # Simulate batch update for agents 2 and 3
        batch_statuses = {agent_ids[1]: "dead", agent_ids[2]: "inactive"}
        agents_list = [mock_agents[agent_ids[1]], mock_agents[agent_ids[2]]]
        mock_db.query.return_value.filter.return_value.first.side_effect = agents_list

        result_batch = _batch_update_agent_status_internal(batch_statuses, mock_db)
        assert result_batch is True
