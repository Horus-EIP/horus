"""Coverage-focused unit tests for ``agents.registry_tool_functions``.

Hermetic: the DB ``Session`` is a ``MagicMock`` and every external side
effect (RabbitMQ queue creation, skill-cache upsert/evict) is patched so
the registry CRUD/heartbeat logic is exercised in isolation.

For each function we assert the success path, the not-found / empty path,
and the error / exception branch, plus the module's special branches
(``ProgrammingError`` table-missing handling, naive-datetime coercion,
Manager exclusion, agent-type string normalisation, liveness window).
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from sqlalchemy.exc import ProgrammingError

from agents import registry_tool_functions as rtf
from db.models import AgentTypes

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _make_agent(**overrides):
    """A lightweight stand-in for an ``Agents`` ORM row.

    ``SimpleNamespace`` lets attribute access (``agent.skills`` etc.) work
    without dragging in SQLAlchemy mapping machinery.
    """
    base = {
        "id": "agent-123",
        "name": "ResearchBot",
        "skills": ["search", "summarise"],
        "description": "A research agent",
        "status": "active",
        "last_heartbeat": datetime.now(UTC),
        "type": AgentTypes.RESEARCHER,
        "created_at": datetime.now(UTC),
        "api_key": "hashed",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _db_first(value):
    """MagicMock session whose ``.query().filter().first()`` yields ``value``."""
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = value
    return db


def _db_all(value):
    """MagicMock session whose ``.query().all()`` yields ``value``.

    ``.query().filter().all()`` returns the same list so callers that filter
    (e.g. ``get_agent_by_type``) also see it.
    """
    db = MagicMock()
    db.query.return_value.all.return_value = value
    db.query.return_value.filter.return_value.all.return_value = value
    return db


def _programming_error(message: str) -> ProgrammingError:
    return ProgrammingError("SELECT 1", {}, Exception(message))


# --------------------------------------------------------------------------- #
# Auto-isolate every external side effect for the whole module.
# --------------------------------------------------------------------------- #


@pytest.fixture(autouse=True)
def _isolate_side_effects(monkeypatch):
    """Neutralise RabbitMQ and skill-cache so no test reaches the network.

    These are monkeypatched (auto-revert) rather than mutated in place.
    """
    monkeypatch.setattr(rtf.rabbitmq_instance, "create_queue", MagicMock())
    monkeypatch.setattr(rtf, "_skill_cache_upsert", MagicMock())
    monkeypatch.setattr(rtf, "_skill_cache_evict", MagicMock())
    yield


# --------------------------------------------------------------------------- #
# _skill_cache_upsert / _skill_cache_evict (call the REAL ones here)
# --------------------------------------------------------------------------- #


class TestSkillCacheHelpers:
    """Drive the genuine helper bodies (the autouse fixture only swaps the
    module-level names; ``_ORIG_*`` keep references to the real functions)."""

    def test_upsert_real_forwards_args(self, monkeypatch):
        fake = MagicMock()
        mod = SimpleNamespace(upsert_agent=fake)
        monkeypatch.setitem(sys.modules, "core.skill_cache", mod)
        _ORIG_UPSERT("a1", "name", ["s1", "s2"], "desc")
        fake.assert_called_once_with("a1", "name", ["s1", "s2"], "desc")

    def test_upsert_real_handles_none_skills_and_description(self, monkeypatch):
        fake = MagicMock()
        mod = SimpleNamespace(upsert_agent=fake)
        monkeypatch.setitem(sys.modules, "core.skill_cache", mod)
        _ORIG_UPSERT("a1", "name", None, None)
        fake.assert_called_once_with("a1", "name", [], "")

    def test_upsert_real_swallows_exceptions(self, monkeypatch):
        mod = SimpleNamespace(
            upsert_agent=MagicMock(side_effect=RuntimeError("boom"))
        )
        monkeypatch.setitem(sys.modules, "core.skill_cache", mod)
        _ORIG_UPSERT("a1", "n", ["s"], "d")  # must not raise

    def test_evict_real_forwards_args(self, monkeypatch):
        fake = MagicMock()
        mod = SimpleNamespace(evict_agent=fake)
        monkeypatch.setitem(sys.modules, "core.skill_cache", mod)
        _ORIG_EVICT("a1")
        fake.assert_called_once_with("a1")

    def test_evict_real_swallows_exceptions(self, monkeypatch):
        mod = SimpleNamespace(
            evict_agent=MagicMock(side_effect=RuntimeError("boom"))
        )
        monkeypatch.setitem(sys.modules, "core.skill_cache", mod)
        _ORIG_EVICT("a1")  # must not raise


# --------------------------------------------------------------------------- #
# _get_all_agents_internal / get_all_agents
# --------------------------------------------------------------------------- #


class TestGetAllAgentsInternal:
    def test_returns_agents_and_touches_attrs(self):
        a1, a2 = _make_agent(id="1"), _make_agent(id="2")
        db = _db_all([a1, a2])
        result = rtf._get_all_agents_internal(db)
        assert result == [a1, a2]

    def test_empty(self):
        db = _db_all([])
        assert rtf._get_all_agents_internal(db) == []

    def test_programming_error_table_missing_returns_empty(self):
        db = MagicMock()
        db.query.return_value.all.side_effect = _programming_error(
            'relation "agents" does not exist'
        )
        assert rtf._get_all_agents_internal(db) == []

    def test_programming_error_other_returns_empty(self):
        db = MagicMock()
        db.query.return_value.all.side_effect = _programming_error("syntax error")
        assert rtf._get_all_agents_internal(db) == []

    def test_generic_exception_returns_empty(self):
        db = MagicMock()
        db.query.return_value.all.side_effect = RuntimeError("connection lost")
        assert rtf._get_all_agents_internal(db) == []

    def test_get_all_agents_wrapper_delegates(self):
        a1 = _make_agent()
        db = _db_all([a1])
        assert rtf.get_all_agents(db) == [a1]


# --------------------------------------------------------------------------- #
# _update_alive_agent_status_internal
# --------------------------------------------------------------------------- #


class TestUpdateAliveInternal:
    def test_success_sets_active_and_commits(self):
        agent = _make_agent(status="dead")
        db = _db_first(agent)
        assert rtf._update_alive_agent_status_internal("agent-123", db) is True
        assert agent.status == "active"
        assert agent.last_heartbeat is not None
        db.commit.assert_called_once()

    def test_not_found_returns_false(self):
        db = _db_first(None)
        assert rtf._update_alive_agent_status_internal("missing", db) is False
        db.commit.assert_not_called()

    def test_exception_rolls_back(self):
        agent = _make_agent()
        db = _db_first(agent)
        db.commit.side_effect = RuntimeError("db down")
        assert rtf._update_alive_agent_status_internal("agent-123", db) is False
        db.rollback.assert_called_once()


# --------------------------------------------------------------------------- #
# _update_dead_agent_status_internal
# --------------------------------------------------------------------------- #


class TestUpdateDeadInternal:
    def test_success_aware_heartbeat(self):
        agent = _make_agent(last_heartbeat=datetime.now(UTC) - timedelta(seconds=30))
        db = _db_first(agent)
        assert rtf._update_dead_agent_status_internal("agent-123", db) is True
        assert agent.status == "dead"
        db.commit.assert_called_once()

    def test_success_naive_heartbeat_is_coerced(self):
        # Naive datetime exercises the ``tzinfo is None`` branch.
        agent = _make_agent(last_heartbeat=datetime.now())  # noqa: DTZ005
        db = _db_first(agent)
        assert rtf._update_dead_agent_status_internal("agent-123", db) is True
        assert agent.status == "dead"

    def test_not_found_returns_false(self):
        db = _db_first(None)
        assert rtf._update_dead_agent_status_internal("missing", db) is False

    def test_exception_rolls_back(self):
        agent = _make_agent()
        db = _db_first(agent)
        db.commit.side_effect = RuntimeError("db down")
        assert rtf._update_dead_agent_status_internal("agent-123", db) is False
        db.rollback.assert_called_once()


# --------------------------------------------------------------------------- #
# _batch_update_agent_status_internal
# --------------------------------------------------------------------------- #


class TestBatchUpdateInternal:
    def test_updates_present_skips_missing(self):
        present = _make_agent(id="present", status="active")
        # First lookup returns the agent, second returns None (missing id).
        db = MagicMock()
        db.query.return_value.filter.return_value.first.side_effect = [present, None]
        statuses = {"present": "dead", "missing": "active"}
        assert rtf._batch_update_agent_status_internal(statuses, db) is True
        assert present.status == "dead"
        db.commit.assert_called_once()

    def test_empty_dict_still_commits(self):
        db = MagicMock()
        assert rtf._batch_update_agent_status_internal({}, db) is True
        db.commit.assert_called_once()

    def test_exception_rolls_back(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = _make_agent()
        db.commit.side_effect = RuntimeError("db down")
        assert rtf._batch_update_agent_status_internal({"a": "dead"}, db) is False
        db.rollback.assert_called_once()


# --------------------------------------------------------------------------- #
# create_agent
# --------------------------------------------------------------------------- #


class TestCreateAgent:
    def test_success_returns_id_and_plaintext_key(self):
        db = MagicMock()
        agent_id, api_key = rtf.create_agent(
            "ResearchBot", ["search"], "desc", db, AgentTypes.RESEARCHER
        )
        assert isinstance(agent_id, str) and len(agent_id) > 0
        # Plaintext key is returned (not the bcrypt hash) and is non-trivial.
        assert isinstance(api_key, str) and len(api_key) >= 20
        assert not api_key.startswith("$2b$")  # not the bcrypt hash
        db.add.assert_called_once()
        db.commit.assert_called_once()
        db.refresh.assert_called_once()
        # Queue + skill cache side effects fired.
        rtf.rabbitmq_instance.create_queue.assert_called_once()
        rtf._skill_cache_upsert.assert_called_once()
        # The stored api_key on the row is the bcrypt hash, not the plaintext.
        stored = db.add.call_args[0][0]
        assert stored.api_key != api_key
        assert rtf.bcrypt_context.verify(api_key, stored.api_key)

    def test_failure_rolls_back_and_returns_none_none(self):
        db = MagicMock()
        db.commit.side_effect = RuntimeError("db down")
        agent_id, api_key = rtf.create_agent(
            "Bot", ["s"], "d", db, AgentTypes.GENERAL
        )
        assert agent_id is None and api_key is None
        db.rollback.assert_called_once()
        # Side effects must NOT fire on the failure path.
        rtf.rabbitmq_instance.create_queue.assert_not_called()
        rtf._skill_cache_upsert.assert_not_called()


# --------------------------------------------------------------------------- #
# delete_agent
# --------------------------------------------------------------------------- #


class TestDeleteAgent:
    def test_success(self):
        agent = _make_agent()
        db = MagicMock()
        db.get.return_value = agent
        assert rtf.delete_agent("agent-123", db) is True
        db.delete.assert_called_once_with(agent)
        db.commit.assert_called_once()
        rtf._skill_cache_evict.assert_called_once_with("agent-123")

    def test_not_found_returns_false(self):
        db = MagicMock()
        db.get.return_value = None
        assert rtf.delete_agent("missing", db) is False
        db.delete.assert_not_called()
        rtf._skill_cache_evict.assert_not_called()

    def test_exception_rolls_back(self):
        db = MagicMock()
        db.get.return_value = _make_agent()
        db.commit.side_effect = RuntimeError("db down")
        assert rtf.delete_agent("agent-123", db) is False
        db.rollback.assert_called_once()


# --------------------------------------------------------------------------- #
# get_agent_details
# --------------------------------------------------------------------------- #


class TestGetAgentDetails:
    def test_success_returns_full_tuple(self):
        agent = _make_agent()
        db = _db_first(agent)
        result = rtf.get_agent_details("agent-123", db)
        assert result == (
            "agent-123",
            agent.name,
            agent.skills,
            agent.status,
            agent.last_heartbeat,
            agent.description,
            agent.created_at,
        )

    def test_not_found_returns_all_none(self):
        db = _db_first(None)
        assert rtf.get_agent_details("missing", db) == (None,) * 7

    def test_exception_returns_all_none(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.side_effect = RuntimeError("x")
        assert rtf.get_agent_details("agent-123", db) == (None,) * 7


# --------------------------------------------------------------------------- #
# update_alive_agent_status / update_active_status (route wrappers)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "func", [rtf.update_alive_agent_status, rtf.update_active_status]
)
class TestUpdateActiveWrappers:
    def test_success(self, func):
        agent = _make_agent(status="dead")
        db = _db_first(agent)
        assert func("agent-123", db) is True
        assert agent.status == "active"
        db.commit.assert_called_once()

    def test_not_found(self, func):
        db = _db_first(None)
        assert func("missing", db) is False
        db.commit.assert_not_called()

    def test_exception_rolls_back(self, func):
        agent = _make_agent()
        db = _db_first(agent)
        db.commit.side_effect = RuntimeError("db down")
        assert func("agent-123", db) is False
        db.rollback.assert_called_once()


# --------------------------------------------------------------------------- #
# update_dead_agent_status
# --------------------------------------------------------------------------- #


class TestUpdateDeadStatus:
    def test_success_sets_inactive(self):
        agent = _make_agent(status="active")
        db = _db_first(agent)
        assert rtf.update_dead_agent_status("agent-123", db) is True
        assert agent.status == "inactive"
        db.commit.assert_called_once()

    def test_not_found(self):
        db = _db_first(None)
        assert rtf.update_dead_agent_status("missing", db) is False

    def test_exception_rolls_back(self):
        agent = _make_agent()
        db = _db_first(agent)
        db.commit.side_effect = RuntimeError("db down")
        assert rtf.update_dead_agent_status("agent-123", db) is False
        db.rollback.assert_called_once()


# --------------------------------------------------------------------------- #
# get_agent_id
# --------------------------------------------------------------------------- #


class TestGetAgentId:
    def test_success(self):
        db = _db_first(_make_agent(id="found-id"))
        assert rtf.get_agent_id("ResearchBot", db) == "found-id"

    def test_not_found(self):
        db = _db_first(None)
        assert rtf.get_agent_id("ghost", db) is None

    def test_exception(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.side_effect = RuntimeError("x")
        assert rtf.get_agent_id("ResearchBot", db) is None


# --------------------------------------------------------------------------- #
# get_agent_by_type
# --------------------------------------------------------------------------- #


class TestGetAgentByType:
    def test_empty_type_returns_none(self):
        assert rtf.get_agent_by_type("", MagicMock()) is None

    def test_match_among_active_enum_type(self):
        a = _make_agent(id="r1", type=AgentTypes.RESEARCHER, created_at="2024-01-01")
        db = _db_all([a])
        assert rtf.get_agent_by_type("researcher", db) == "r1"

    def test_strips_dotted_hallucination(self):
        a = _make_agent(id="r1", type=AgentTypes.RESEARCHER)
        db = _db_all([a])
        # "AgentTypes.RESEARCHER" -> "researcher"
        assert rtf.get_agent_by_type("AgentTypes.RESEARCHER", db) == "r1"

    def test_string_type_value_match(self):
        # ``type`` is a plain string (no ``.value``) -> exercises the
        # ``hasattr(..., "value")`` False branch.
        a = _make_agent(id="g1", type="general")
        db = _db_all([a])
        assert rtf.get_agent_by_type("general", db) == "g1"

    def test_sorted_newest_first(self):
        old = _make_agent(id="old", type=AgentTypes.WRITER, created_at="2020-01-01")
        new = _make_agent(id="new", type=AgentTypes.WRITER, created_at="2024-01-01")
        db = _db_all([old, new])
        assert rtf.get_agent_by_type("writer", db) == "new"

    def test_fallback_to_any_agent_when_none_active(self):
        # Active query returns [], fallback query returns a matching agent.
        inactive = _make_agent(id="x1", type=AgentTypes.ANALYST, status="dead")
        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = []  # active=[]
        db.query.return_value.all.return_value = [inactive]  # fallback
        assert rtf.get_agent_by_type("analyst", db) == "x1"

    def test_no_match_returns_none(self):
        a = _make_agent(id="r1", type=AgentTypes.RESEARCHER)
        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = [a]
        db.query.return_value.all.return_value = [a]
        assert rtf.get_agent_by_type("nonexistent", db) is None

    def test_exception_returns_none(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.all.side_effect = RuntimeError("x")
        assert rtf.get_agent_by_type("researcher", db) is None


# --------------------------------------------------------------------------- #
# _is_agent_recently_alive
# --------------------------------------------------------------------------- #


class TestIsAgentRecentlyAlive:
    def test_no_heartbeat_returns_false(self):
        assert rtf._is_agent_recently_alive(_make_agent(last_heartbeat=None)) is False

    def test_recent_aware_heartbeat_true(self):
        a = _make_agent(last_heartbeat=datetime.now(UTC) - timedelta(seconds=10))
        assert rtf._is_agent_recently_alive(a) is True

    def test_recent_naive_heartbeat_coerced_true(self):
        a = _make_agent(last_heartbeat=datetime.now())  # noqa: DTZ005
        assert rtf._is_agent_recently_alive(a) is True

    def test_stale_heartbeat_false(self):
        a = _make_agent(last_heartbeat=datetime.now(UTC) - timedelta(seconds=500))
        assert rtf._is_agent_recently_alive(a, max_age_seconds=90) is False

    def test_exception_returns_false(self):
        # ``last_heartbeat`` truthy but not a datetime -> subtraction raises.
        a = _make_agent(last_heartbeat="not-a-datetime")
        assert rtf._is_agent_recently_alive(a) is False


# --------------------------------------------------------------------------- #
# get_available_agents
# --------------------------------------------------------------------------- #


class TestGetAvailableAgents:
    def test_excludes_manager_and_returns_alive_tuples(self):
        manager = _make_agent(id="m", name="Manager", type=AgentTypes.MANAGER)
        alive = _make_agent(
            id="a1",
            name="ResearchBot",
            description="desc",
            type=AgentTypes.RESEARCHER,
            last_heartbeat=datetime.now(UTC),
        )
        stale = _make_agent(
            id="a2",
            name="OldBot",
            last_heartbeat=datetime.now(UTC) - timedelta(seconds=999),
        )
        db = _db_all([manager, alive, stale])
        result = rtf.get_available_agents(db)
        assert result == [("a1", "ResearchBot", "desc", AgentTypes.RESEARCHER)]

    def test_none_description_becomes_empty_string(self):
        alive = _make_agent(
            id="a1",
            name="Bot",
            description=None,
            last_heartbeat=datetime.now(UTC),
        )
        db = _db_all([alive])
        result = rtf.get_available_agents(db)
        assert result == [("a1", "Bot", "", alive.type)]

    def test_no_agents_returns_empty(self):
        db = _db_all([])
        assert rtf.get_available_agents(db) == []

    def test_programming_error_table_missing_returns_empty(self):
        db = MagicMock()
        db.query.return_value.all.side_effect = _programming_error(
            'relation "agents" does not exist'
        )
        assert rtf.get_available_agents(db) == []

    def test_programming_error_other_returns_empty(self):
        db = MagicMock()
        db.query.return_value.all.side_effect = _programming_error("boom")
        assert rtf.get_available_agents(db) == []

    def test_generic_exception_returns_empty(self):
        db = MagicMock()
        db.query.return_value.all.side_effect = RuntimeError("x")
        assert rtf.get_available_agents(db) == []


# --------------------------------------------------------------------------- #
# Capture the genuine helper implementations at import time so the autouse
# fixture (which replaces them with MagicMocks) doesn't hide their bodies.
# --------------------------------------------------------------------------- #

_ORIG_UPSERT = rtf._skill_cache_upsert
_ORIG_EVICT = rtf._skill_cache_evict
