"""Service-level fixtures for MAS tests.

Hermetic — no external services. No Postgres, no Redis, no RabbitMQ, no
LLM downloads. Heavy ML libraries are replaced with ``MagicMock`` so the
import graph stays light.

The api/ subpackage adds its own fixtures (``make_client``, ``mock_db``,
``as_admin`` / ``as_manager`` / ``as_user``) — see
``tests/mas/api/conftest.py``.

The live-server launcher that used to live here (subprocess + run-mas.sh)
moved to ``scripts/integration-checks/conftest.py`` and only runs when you
invoke pytest with ``-m requires_stack``.
"""

from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock

# --------------------------------------------------------------------------- #
# 1. Mock heavy / GPU-bound libraries BEFORE any service code is imported.
# --------------------------------------------------------------------------- #

sys.modules["torch"] = MagicMock()

_mock_transformers = MagicMock()


class _MockBnBConfig:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


_mock_transformers.BitsAndBytesConfig = _MockBnBConfig
sys.modules["transformers"] = _mock_transformers
sys.modules["bitsandbytes"] = MagicMock()

# --------------------------------------------------------------------------- #
# 2. Force the application into test mode and silence telemetry exporters.
# --------------------------------------------------------------------------- #

os.environ["TEST_MODE"] = "1"
os.environ["llm_autoinit"] = "0"
os.environ["LLM_AUTOINIT"] = "0"
os.environ["OTEL_ENABLED"] = "false"
os.environ["OTEL_SDK_DISABLED"] = "true"
os.environ.setdefault("OTEL_TRACES_EXPORTER", "none")

# A predictable JWT secret keeps token tests reproducible.
os.environ.setdefault("JWT_SECRET_KEY", "ci-secret-not-for-production")
os.environ.setdefault("JWT_ALGORITHM", "HS256")
os.environ.setdefault("SUPER_USER_USERNAME", "admin")
os.environ.setdefault("SUPER_USER_PASSWORD", "admin")

# In-memory SQLite for any test that touches the SQLAlchemy session helpers.
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

import pytest  # noqa: E402

# --------------------------------------------------------------------------- #
# 3. Lightweight, autouse hygiene fixtures.
# --------------------------------------------------------------------------- #


@pytest.fixture(autouse=True)
def configure_structlog_for_testing():
    """Wire structlog to stdlib logging so ``caplog`` can see records."""
    try:
        import structlog  # noqa: PLC0415
    except ImportError:
        # structlog isn't always installed in CI's lighter venvs — fine.
        yield
        return

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(ensure_ascii=False),
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
    )
    yield


@pytest.fixture(autouse=True)
def task_event_store(monkeypatch):
    import fakeredis  # noqa: PLC0415

    import core.task_events as task_events  # noqa: PLC0415
    import tasks.agent_answers as agent_answers  # noqa: PLC0415
    import tasks.idempotency as idempotency  # noqa: PLC0415

    store = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(task_events, "redis_db", store)
    monkeypatch.setattr(idempotency, "redis_db", store)
    monkeypatch.setattr(agent_answers, "redis_db", store)
    task_events._publish_locks.clear()
    yield store
    task_events._publish_locks.clear()


@pytest.hookimpl(tryfirst=True)
def pytest_load_initial_conftests(early_config, parser, args):
    """Belt-and-braces: re-assert no LLM autoinit before anything imports."""
    os.environ["LLM_AUTOINIT"] = "0"
