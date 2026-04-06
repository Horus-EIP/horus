import atexit
import logging
import os
import socket
import subprocess
import sys
import time
from unittest.mock import MagicMock

# Mock heavy ML libraries to avoid slow imports and GPU requirements
sys.modules["torch"] = MagicMock()
mock_transformers = MagicMock()
class MockBnBConfig:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)
mock_transformers.BitsAndBytesConfig = MockBnBConfig
sys.modules["transformers"] = mock_transformers
sys.modules["bitsandbytes"] = MagicMock()

import pytest
import structlog

# Force test mode
os.environ["TEST_MODE"] = "1"
os.environ["llm_autoinit"] = "0" # Force disable LLM loading during tests
# os.environ["llm_autoinit"] = "1" # Don't force this globally to avoid download in CI


def _is_port_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=1):
            return True
    except Exception:
        return False


@pytest.fixture(autouse=True)
def configure_structlog_for_testing():
    """
    Configure structlog to use standard logging for tests,
    so that caplog can capture logs.
    """
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(ensure_ascii=False),
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
    )


@pytest.fixture(scope="session", autouse=True)
def ensure_server_running():
    """Ensure the local server is running for integration tests.

    If nothing listens on localhost:8000, this fixture will start the
    repository's `run_local.sh` script (which runs migrations and starts uvicorn)
    in a background process and wait for the port to be available. The process
    is terminated at the end of the test session.
    """
    host = os.getenv("TEST_HOST", "localhost")
    port = int(os.getenv("TEST_PORT", "8000"))

    if os.getenv("TEST_MODE") == "1":
        # In test mode, we assume unit tests/mocks and don't need external server
        yield
        return

    if _is_port_open(host, port):
        # Server already running, nothing to do
        yield
        return

    # Try to load env file from repo infra
    tests_dir = os.path.dirname(__file__)
    repo_service_dir = os.path.abspath(os.path.join(tests_dir, ".."))
    infra_env = os.path.abspath(os.path.join(repo_service_dir, "..", "infra", ".env"))

    env = os.environ.copy()
    if os.path.exists(infra_env):
        with open(infra_env, "r") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    k, v = line.split("=", 1)
                    env[k.strip()] = v.strip()

    # Ensure we don't auto-init heavy LLMs during tests
    env.setdefault("LLM_AUTOINIT", "0")

    # Start the run_local.sh script which runs migrations and starts uvicorn
    run_script = os.path.join(repo_service_dir, "run_local.sh")
    if not os.path.exists(run_script):
        pytest.skip(
            "run_local.sh not found; cannot start local server for integration tests"
        )

    proc = subprocess.Popen(["bash", "run_local.sh"], cwd=repo_service_dir, env=env)

    def _cleanup():
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            proc.kill()

    atexit.register(_cleanup)

    # Wait for server port to become available
    for _ in range(60):
        if _is_port_open(host, port):
            break
        time.sleep(1)
    else:
        _cleanup()
        pytest.skip("Could not start server for integration tests (port not open)")

    yield

    # Teardown: terminate process
    _cleanup()


import os

import pytest


@pytest.hookimpl(tryfirst=True)
def pytest_load_initial_conftests(early_config, parser, args):
    os.environ["LLM_AUTOINIT"] = "0"


@pytest.fixture(scope="session", autouse=True)
def create_test_database_tables():
    """Ensure all database tables exist before running tests"""
    from db.database import Base, engine
    # Import all models to register them with Base metadata
    from db.models import (Agents, Conversations, CriticalLogs, Messages, Task,
                           TaskResult, Users)

    # Create all tables based on SQLAlchemy models
    Base.metadata.create_all(bind=engine)

    yield

    # Optionally, drop all tables after tests (comment out to keep data)
    # Base.metadata.drop_all(bind=engine)
