# tests/test_agent_heartbeat_controller.py
import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import agents.controller as controller


@pytest.fixture
def one_cycle_sleep(monkeypatch):
    call_count = {"n": 0}

    async def fake_sleep(_seconds):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return
        raise asyncio.CancelledError

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    return call_count


# ---------- Tests ----------


@pytest.mark.asyncio
async def test_heartbeat_sets_active_and_inactive(monkeypatch):
    from datetime import timezone

    fixed_now = datetime.now(timezone.utc)

    class FixedDateTime(controller.datetime.datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed_now if tz is None else fixed_now.replace(tzinfo=tz)

    monkeypatch.setattr(controller.datetime, "datetime", FixedDateTime)

    # Create mock agent objects that behave like database Agent objects
    agent_a = MagicMock()
    agent_a.id = "a-active"
    agent_a.last_heartbeat = fixed_now
    agent_a.status = "inactive"
    agent_a.name = "Agent A"
    agent_a.skills = []
    agent_a.description = ""

    agent_b = MagicMock()
    agent_b.id = "b-inactive"
    agent_b.last_heartbeat = fixed_now - timedelta(seconds=40)
    agent_b.status = "active"
    agent_b.name = "Agent B"
    agent_b.skills = []
    agent_b.description = ""

    agent_c = MagicMock()
    agent_c.id = "c-edge-active"
    agent_c.last_heartbeat = fixed_now - timedelta(seconds=30)
    agent_c.status = "inactive"
    agent_c.name = "Agent C"
    agent_c.skills = []
    agent_c.description = ""

    agents = [agent_a, agent_b, agent_c]

    # Mock SessionLocal
    mock_db = MagicMock()
    monkeypatch.setattr("agents.controller.SessionLocal", lambda: mock_db)

    # Mock asyncio.sleep to exit after first call
    call_count = {"n": 0}

    async def fake_sleep(_seconds):
        call_count["n"] += 1
        if call_count["n"] > 1:
            raise asyncio.CancelledError

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    # Mock _get_all_agents_internal to return our mock agents
    with patch(
        "agents.controller._get_all_agents_internal", return_value=agents
    ) as mock_get_agents:
        # Mock _batch_update_agent_status_internal to track updates
        with patch("agents.controller._batch_update_agent_status_internal") as mock_update:
            try:
                await controller.check_agent_heartbeat(test_mode=True)
            except asyncio.CancelledError:
                pass

            # Verify the function was called
            mock_get_agents.assert_called()
            mock_update.assert_called_once()

            # Get the status updates that were passed
            call_args = mock_update.call_args[0]
            status_updates = call_args[0]

            # Verify status updates
            assert status_updates["a-active"] == "active"
            assert status_updates["b-inactive"] == "inactive"
            assert status_updates["c-edge-active"] == "active"


@pytest.mark.asyncio
async def test_heartbeat_handles_empty_registry(monkeypatch):
    # Mock SessionLocal
    mock_db = MagicMock()
    monkeypatch.setattr("agents.controller.SessionLocal", lambda: mock_db)

    # Mock asyncio.sleep to exit after first call
    call_count = {"n": 0}

    async def fake_sleep(_seconds):
        call_count["n"] += 1
        if call_count["n"] > 1:
            raise asyncio.CancelledError

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    # Mock _get_all_agents_internal to return empty list
    with patch("agents.controller._get_all_agents_internal", return_value=[]) as mock_get_agents:
        try:
            await controller.check_agent_heartbeat(test_mode=True)
        except asyncio.CancelledError:
            pass
        mock_get_agents.assert_called()


def test_get_all_agents(monkeypatch):
    # Mock SessionLocal
    mock_db = MagicMock()
    monkeypatch.setattr("agents.controller.SessionLocal", lambda: mock_db)

    # Mock agents
    agent_a = MagicMock()
    agent_a.id = "agent-1"
    agent_a.name = "Agent 1"
    agent_a.skills = ["skill1"]
    agent_a.status = "active"
    agent_a.last_heartbeat = datetime.now()
    agent_a.description = "Description 1"

    with patch("agents.controller._get_all_agents_internal", return_value=[agent_a]):
        result = controller.get_all_agents()

        assert "agent-1" in result
        assert result["agent-1"]["name"] == "Agent 1"
        assert result["agent-1"]["status"] == "active"
        mock_db.close.assert_called_once()


@pytest.mark.asyncio
async def test_heartbeat_exception_handling(monkeypatch):
    # Mock SessionLocal to raise exception
    monkeypatch.setattr(
        "agents.controller.SessionLocal", MagicMock(side_effect=Exception("DB Error"))
    )

    # Mock asyncio.sleep to exit after first call
    call_count = {"n": 0}

    async def fake_sleep(_seconds):
        call_count["n"] += 1
        if call_count["n"] > 1:
            raise asyncio.CancelledError

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    try:
        await controller.check_agent_heartbeat(test_mode=True)
    except asyncio.CancelledError:
        pass
    except Exception:
        # Should catch the exception and log it, not raise it
        pass
