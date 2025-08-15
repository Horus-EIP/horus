import datetime as dt
import time
import uuid

import pytest

from agents.registry_tool_functions import (agent_registry, create_agent,
                                            delete_agent, get_agent_details,
                                            get_all_agents,
                                            update_alive_agent_status)

# ---------- Fixtures ----------


@pytest.fixture(autouse=True)
def clean_registry():
    agent_registry.clear()
    yield
    agent_registry.clear()


# ---------- Helpers ----------


def _is_valid_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
        return True
    except Exception:
        return False


# ---------- Tests: create_agent ----------


def test_create_agent_returns_uuid_and_sets_fields():
    agent_id = create_agent("Alice", ["nlp", "retrieval"])
    assert _is_valid_uuid(agent_id)
    assert agent_id in agent_registry
    info = agent_registry[agent_id]
    assert info["name"] == "Alice"
    assert info["skills"] == ["nlp", "retrieval"]
    assert info["status"] == "active"
    assert isinstance(info["last_heartbeat"], dt.datetime)


def test_create_multiple_agents_unique_ids():
    ids = {create_agent(f"agent{i}", []) for i in range(10)}
    assert len(ids) == 10
    assert all(_is_valid_uuid(i) for i in ids)


def test_create_agent_allows_empty_skills():
    agent_id = create_agent("NoSkills", [])
    assert agent_registry[agent_id]["skills"] == []


def test_create_agent_unicode_name_and_skills():
    agent_id = create_agent("Élodie🚀", ["résumé", "vision"])
    info = agent_registry[agent_id]
    assert info["name"] == "Élodie🚀"
    assert info["skills"] == ["résumé", "vision"]


# ---------- Tests: get_all_agents ----------


def test_get_all_agents_reflects_created_agents():
    a1 = create_agent("A1", [])
    a2 = create_agent("A2", ["x"])
    reg = get_all_agents()
    assert a1 in reg and a2 in reg
    assert reg[a2]["skills"] == ["x"]


# ---------- Tests: get_agent_details ----------


def test_get_agent_details_found_returns_expected_tuple():
    agent_id = create_agent("Bob", ["vision"])
    result = get_agent_details(agent_id)
    assert isinstance(result, tuple)
    assert len(result) == 5
    rid, name, skills, status, heartbeat = result
    assert rid == agent_id
    assert name == "Bob"
    assert skills == ["vision"]
    assert status in ("active", "inactive")
    assert isinstance(heartbeat, dt.datetime)


def test_get_agent_details_not_found_should_return_5_nones():
    result = get_agent_details("00000000-0000-0000-0000-000000000000")
    assert isinstance(result, tuple)
    assert len(result) == 5
    assert all(x is None for x in result)


def test_get_agent_details_not_found_current_behavior():
    result = get_agent_details("00000000-0000-0000-0000-000000000000")
    assert isinstance(result, tuple)
    assert len(result) == 5
    assert all(x is None for x in result)


# ---------- Tests: update_alive_agent_status ----------


def test_update_alive_agent_status_updates_timestamp_and_status():
    agent_id = create_agent("Carol", ["nlp"])
    before = agent_registry[agent_id]["last_heartbeat"]
    agent_registry[agent_id]["status"] = "inactive"
    agent_registry[agent_id]["last_heartbeat"] = before - dt.timedelta(seconds=60)

    updated = update_alive_agent_status(agent_id)
    assert updated is True
    after = agent_registry[agent_id]["last_heartbeat"]
    assert agent_registry[agent_id]["status"] == "active"
    assert after > before - dt.timedelta(seconds=30)


def test_update_alive_agent_status_returns_false_if_missing():
    assert update_alive_agent_status("does-not-exist") is False


# ---------- Tests: delete_agent ----------


def test_delete_agent_success_removes_entry():
    agent_id = create_agent("Dave", [])
    assert agent_id in agent_registry
    ok = delete_agent(agent_id)
    assert ok is True
    assert agent_id not in agent_registry


def test_delete_agent_returns_false_when_not_found():
    assert delete_agent("00000000-0000-0000-0000-000000000000") is False


def test_delete_agent_clears_info_before_removal():
    agent_id = create_agent("Eve", ["x"])
    info_ref = agent_registry[agent_id]
    assert info_ref
    assert delete_agent(agent_id) is True
    assert info_ref == {}
    assert agent_id not in agent_registry


# ---------- Tests: timing-ish (sanity) ----------


def test_last_heartbeat_monotonicity_on_multiple_updates():
    agent_id = create_agent("Frank", [])
    t1 = agent_registry[agent_id]["last_heartbeat"]
    time.sleep(0.01)
    update_alive_agent_status(agent_id)
    t2 = agent_registry[agent_id]["last_heartbeat"]
    assert t2 >= t1
