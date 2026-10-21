"""Hermetic API-layer fixtures for MAS.

Every fixture in this file replaces an external dependency with an in-process
fake so tests under ``tests/mas/api/`` need **no Docker, no live Postgres,
no live Redis, no live RabbitMQ** to run.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from auth.auth_tool_functions import get_current_user, verify_agent_api_key
from db.database import Base, get_db

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


@pytest.fixture
def as_agent() -> dict:
    return _user_payload("agent", user_id=4, username="agent")


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


@pytest.fixture
def routing_db():
    from db.models import Conversations  # noqa: PLC0415

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    session.add(Conversations(id=7, owner_username="user", name="Q4 review"))
    session.commit()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture
def mas_client(routing_db):
    from tasks.routes import router  # noqa: PLC0415

    def _factory(user: dict) -> httpx.AsyncClient:
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_db] = lambda: routing_db
        app.dependency_overrides[get_current_user] = lambda: user
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://mas"
        )

    return _factory


@pytest.fixture
def submit_task(routing_db, mas_client, monkeypatch):
    from tasks import routes  # noqa: PLC0415
    from tasks.task_jobs import task_jobs  # noqa: PLC0415

    outcomes: list[dict] = []
    route_for_real = routes.run_routing_job

    async def recording_job(*args, **kwargs):
        outcome = await route_for_real(*args, **kwargs)
        outcomes.append(outcome)
        return outcome

    monkeypatch.setattr(routes, "SessionLocal", lambda: routing_db)
    monkeypatch.setattr(routes, "run_routing_job", recording_job)

    async def _submit(body: dict, *, user: dict, headers: dict | None = None):
        jobs_before = len(outcomes)
        async with mas_client(user) as client:
            response = await client.post("/tasks/new_task/", json=body, headers=headers or {})
        await task_jobs.drain()
        return SimpleNamespace(
            response=response,
            outcome=outcomes[-1] if len(outcomes) > jobs_before else None,
        )

    return _submit
