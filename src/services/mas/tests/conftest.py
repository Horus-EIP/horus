import os
import sys
import time
import socket
import subprocess
import atexit

import pytest


def _is_port_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=1):
            return True
    except Exception:
        return False


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
        pytest.skip("run_local.sh not found; cannot start local server for integration tests")

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
    from db.models import Users, Agents, Messages, Task, TaskResult, CriticalLogs, Conversations
    
    # Create all tables based on SQLAlchemy models
    Base.metadata.create_all(bind=engine)
    
    yield
    
    # Optionally, drop all tables after tests (comment out to keep data)
    # Base.metadata.drop_all(bind=engine)
