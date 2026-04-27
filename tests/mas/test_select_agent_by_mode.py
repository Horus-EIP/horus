"""Tests for the explicit dispatch-mode selector."""

from unittest.mock import MagicMock, patch

import pytest

from tasks.decomposition import select_agent_by_mode


def _agent(id_, name, skills, alive=True):
    a = MagicMock()
    a.id = id_
    a.name = name
    a.skills = skills
    a.last_heartbeat = None
    a.status = "active" if alive else "inactive"
    return a


def _db_with_agents(agents):
    db = MagicMock()
    db.query.return_value.all.return_value = agents
    return db


def test_specific_agent_returns_supplied_id():
    target = _agent("uuid-1", "Finance-Analyst", ["financial_analysis"])
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = target

    result = select_agent_by_mode(
        "do thing", ["financial_analysis"], "specific_agent", "uuid-1", db
    )

    assert result[0] == "uuid-1"
    assert result[1] == "do thing"
    assert result[2] is None
    assert result[3] == []


def test_specific_agent_missing_id_falls_back():
    db = MagicMock()
    result = select_agent_by_mode("x", [], "specific_agent", None, db)
    assert result == (None, None, None, [])


def test_specific_agent_unknown_id_falls_back():
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None

    result = select_agent_by_mode("x", [], "specific_agent", "ghost", db)
    assert result == (None, None, None, [])


def test_any_with_skill_prefers_live_agent():
    live = _agent("live", "Finance-Analyst", ["financial_analysis"], alive=True)
    seeded = _agent("seed", "Other", ["financial_analysis"], alive=False)
    db = _db_with_agents([seeded, live])

    with patch(
        "tasks.decomposition._is_agent_recently_alive",
        side_effect=lambda a: a.id == "live",
    ):
        result = select_agent_by_mode(
            "do thing", ["financial_analysis"], "any_with_skill", None, db
        )

    assert result[0] == "live"


def test_any_with_skill_falls_back_to_seeded_when_no_live():
    seeded = _agent("seed", "Finance-Analyst", ["financial_analysis"], alive=False)
    db = _db_with_agents([seeded])

    with patch(
        "tasks.decomposition._is_agent_recently_alive", return_value=False
    ):
        result = select_agent_by_mode(
            "do thing", ["financial_analysis"], "any_with_skill", None, db
        )

    assert result[0] == "seed"


def test_any_with_skill_no_match_falls_back():
    other = _agent("other", "Researcher", ["research"], alive=True)
    db = _db_with_agents([other])

    with patch(
        "tasks.decomposition._is_agent_recently_alive", return_value=True
    ):
        result = select_agent_by_mode(
            "do thing", ["financial_analysis"], "any_with_skill", None, db
        )

    assert result == (None, None, None, [])


def test_any_with_skill_empty_skills_falls_back():
    db = MagicMock()
    result = select_agent_by_mode("do thing", [], "any_with_skill", None, db)
    assert result == (None, None, None, [])


def test_auto_mode_falls_back_to_caller():
    db = MagicMock()
    assert select_agent_by_mode("x", ["s"], "auto", None, db) == (
        None,
        None,
        None,
        [],
    )
    assert select_agent_by_mode("x", ["s"], None, None, db) == (
        None,
        None,
        None,
        [],
    )


def test_unknown_mode_falls_back_to_caller():
    db = MagicMock()
    assert select_agent_by_mode("x", ["s"], "bogus", None, db) == (
        None,
        None,
        None,
        [],
    )
