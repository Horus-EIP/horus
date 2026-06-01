"""Hermetic API-layer fixtures for MAS.

Every fixture in this file replaces an external dependency with an in-process
fake so tests under ``tests/mas/api/`` need **no Docker, no live Postgres,
no live Redis, no live RabbitMQ** to run.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from auth.auth_tool_functions import get_current_user, verify_agent_api_key
from db.database import get_db


# --------------------------------------------------------------------------- #
# Database
# --------------------------------------------------------------------------- #


@pytest.fixture
def mock_db() -> MagicMock:
    """A MagicMock standing in for a SQLAlchemy ``Session``."""
    return MagicMock()


# --------------------------------------------------------------------------- #
# Auth — token-shaped fixtures.
# ``id`` mirrors the JWT 'id' field the handlers read with ``user.get("id")``.
# --------------------------------------------------------------------------- #


def _user_payload(role: str, *, user_id: int = 1, username: str | None = None) -> dict:
    return {
        "id": user_id,
        "user_id": str(user_id),
        "username": username or role,
        "role": role,
    }


@pytest.fixture
def as_admin() -> dict:
    return _user_payload("admin", user_id=1, username="admin")


@pytest.fixture
def as_manager() -> dict:
    return _user_payload("manager", user_id=2, username="manager")


@pytest.fixture
def as_user() -> dict:
    return _user_payload("user", user_id=3, username="user")


# --------------------------------------------------------------------------- #
# App / client factory
# --------------------------------------------------------------------------- #


@pytest.fixture
def make_client(mock_db: MagicMock):
    """Factory returning a TestClient with the given router mounted.

    ``current_user``      overrides ``get_current_user`` (Authorization JWT).
    ``agent_api_auth``    overrides ``verify_agent_api_key`` (X-API-Key headers).
    """

    def _factory(
        router,
        current_user: dict | None = None,
        agent_api_auth: tuple[str, str] | None = None,
    ) -> TestClient:
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_db] = lambda: mock_db
        if current_user is not None:
            app.dependency_overrides[get_current_user] = lambda: current_user
        if agent_api_auth is not None:
            app.dependency_overrides[verify_agent_api_key] = lambda: agent_api_auth
        return TestClient(app)

    return _factory
