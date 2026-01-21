"""
settings.py
------------
This module defines configuration settings for the MAS Orchestrator integration.
"""
import os


def get_float_env(key: str, default: float) -> float:
    """Get float environment variable with default value."""
    value = os.getenv(key)
    return float(value) if value else default


def get_int_env(key: str, default: int) -> int:
    """Get integer environment variable with default value."""
    value = os.getenv(key)
    return int(value) if value else default


# When running in Docker, set ORCHESTRATOR_URL to http://mas:8000
ORCHESTRATOR_URL = os.getenv("ORCHESTRATOR_URL", "http://localhost:8000")

# Authentication used by the agent to talk to the MAS orchestrator
# - ORCHESTRATOR_TOKEN: direct bearer token (takes precedence)
# - ORCHESTRATOR_USERNAME / ORCHESTRATOR_PASSWORD: credentials to fetch a token via /auth/token
ORCHESTRATOR_TOKEN = os.getenv("ORCHESTRATOR_TOKEN")
ORCHESTRATOR_USERNAME = os.getenv("ORCHESTRATOR_USERNAME")
ORCHESTRATOR_PASSWORD = os.getenv("ORCHESTRATOR_PASSWORD")

# Agent metadata (sent during registration)
AGENT_DESCRIPTION = os.getenv("AGENT_DESCRIPTION", "Autonomous MAS agent")

# Knowledge Store URL - when running in Docker, set to http://knowledge_store:8080
KNOWLEDGE_STORE_URL = os.getenv("KNOWLEDGE_STORE_URL", "http://localhost:8080")

# Knowledge Store Client Configuration
KNOWLEDGE_STORE_TIMEOUT = get_float_env("KNOWLEDGE_STORE_TIMEOUT", 10.0)
KNOWLEDGE_STORE_MAX_RETRIES = get_int_env("KNOWLEDGE_STORE_MAX_RETRIES", 3)
KNOWLEDGE_STORE_RETRY_DELAY = get_float_env("KNOWLEDGE_STORE_RETRY_DELAY", 1.0)

# Model Configuration
MODEL_NAME = os.getenv("MODEL_NAME", "t5-small")
MODEL_DEVICE = os.getenv("MODEL_DEVICE", "auto")  # "auto", "cpu", "cuda", "cuda:0", etc.
