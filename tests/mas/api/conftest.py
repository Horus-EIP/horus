"""Hermetic API-layer fixtures for MAS.

Every fixture in this file replaces an external dependency with an in-process
fake so tests under ``tests/mas/api/`` need **no Docker, no live Postgres,
no live Redis, no live RabbitMQ** to run.

The contract:

* ``client`` — a FastAPI TestClient bound to an app that includes the router
  under test, with all `Depends(...)` external services overridden.
* ``mock_db`` — a `MagicMock()` standing in for a SQLAlchemy session.
* ``as_admin`` / ``as_manager`` / ``as_user`` — token-shaped fixtures that
  override `get_current_user` to return the matching role payload.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from auth.auth_tool_functions import get_current_user
from db.database import get_db


# --------------------------------------------------------------------------- #
# Database
# --------------------------------------------------------------------------- #


@pytest.fixture
def mock_db() -> MagicMock:
    """A MagicMock standing in for a SQLAlchemy ``Session``.

    Tests configure the chain (``query().filter().first()``…) as they need.
    """
    return MagicMock()


# --------------------------------------------------------------------------- #
# Auth — token-shaped fixtures
# --------------------------------------------------------------------------- #


def _user_payload(role: str, username: str | None = None) -> dict:
    return {
        "user_id": f"{role}-id",
        "username": username or role,
        "role": role,
    }


@pytest.fixture
def as_admin() -> dict:
    return _user_payload("admin")


@pytest.fixture
def as_manager() -> dict:
    return _user_payload("manager")


@pytest.fixture
def as_user() -> dict:
    return _user_payload("user")


# --------------------------------------------------------------------------- #
# App / client factory
# --------------------------------------------------------------------------- #


@pytest.fixture
def make_client(mock_db: MagicMock):
    """Factory returning a TestClient with the given router mounted and the
    standard external dependencies overridden.

    Usage::

        from users.routes import router
        def test_something(make_client, as_admin):
            client = make_client(router, current_user=as_admin)
            r = client.get("/users/me")
            assert r.status_code == 200
    """

    def _factory(router, current_user: dict | None = None) -> TestClient:
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_db] = lambda: mock_db
        if current_user is not None:
            app.dependency_overrides[get_current_user] = lambda: current_user
        return TestClient(app)

    return _factory
