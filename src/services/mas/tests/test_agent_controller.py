# tests/test_agent_heartbeat_controller.py
import asyncio
from datetime import datetime, timedelta

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
    fixed_now = datetime.now()

    class FixedDateTime(controller.datetime.datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed_now if tz is None else fixed_now.replace(tzinfo=tz)

    monkeypatch.setattr(controller.datetime, "datetime", FixedDateTime)

    agents = {
        "a-active": {"last_heartbeat": fixed_now, "status": "inactive"},  # -> active
        "b-inactive": {
            "last_heartbeat": fixed_now - timedelta(seconds=40),
            "status": "active",
        },  # -> inactive
        "c-edge-active": {
            "last_heartbeat": fixed_now - timedelta(seconds=30),
            "status": "inactive",
        },  # == seuil -> active
    }

    monkeypatch.setattr(controller, "get_all_agents", lambda: agents, raising=True)

    await controller.check_agent_heartbeat(test_mode=True)

    assert agents["a-active"]["status"] == "active"
    assert agents["b-inactive"]["status"] == "inactive"
    assert agents["c-edge-active"]["status"] == "active"


@pytest.mark.asyncio
async def test_heartbeat_handles_empty_registry(monkeypatch, one_cycle_sleep):
    monkeypatch.setattr(controller, "get_all_agents", lambda: {}, raising=True)
    await controller.check_agent_heartbeat(test_mode=True)
