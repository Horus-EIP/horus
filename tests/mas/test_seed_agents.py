"""Tests for the default agent seeder."""

from unittest.mock import MagicMock, patch

import pytest

from db.seed_agents import DEFAULT_AGENTS, seed_default_agents


def _mock_db_with_existing_names(names):
    db = MagicMock()
    db.query.return_value.all.return_value = [(n,) for n in names]
    return db


def test_seed_inserts_all_when_db_empty():
    db = _mock_db_with_existing_names([])

    with patch("db.seed_agents.bcrypt_context.hash", return_value="$2b$hash"):
        inserted = seed_default_agents(db)

    assert inserted == len(DEFAULT_AGENTS)
    assert db.add.call_count == len(DEFAULT_AGENTS)
    db.commit.assert_called_once()


def test_seed_is_idempotent():
    existing = {entry["name"] for entry in DEFAULT_AGENTS}
    db = _mock_db_with_existing_names(existing)

    with patch("db.seed_agents.bcrypt_context.hash", return_value="$2b$hash"):
        inserted = seed_default_agents(db)

    assert inserted == 0
    db.add.assert_not_called()
    db.commit.assert_not_called()


def test_seed_inserts_only_missing():
    half = {DEFAULT_AGENTS[0]["name"], DEFAULT_AGENTS[2]["name"]}
    db = _mock_db_with_existing_names(half)

    with patch("db.seed_agents.bcrypt_context.hash", return_value="$2b$hash"):
        inserted = seed_default_agents(db)

    assert inserted == len(DEFAULT_AGENTS) - len(half)
    assert db.add.call_count == inserted
    db.commit.assert_called_once()


def test_seed_default_lineup_has_five_distinct_agents():
    names = [entry["name"] for entry in DEFAULT_AGENTS]
    assert len(names) == 5
    assert len(set(names)) == 5
    # Spot-check the demo lineup the EIP demo references.
    assert "Finance-Analyst" in names
    assert "Compliance-Officer" in names
    assert "General-Assistant" in names
