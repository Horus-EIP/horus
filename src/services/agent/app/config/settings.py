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

RABBITMQ_PORT = get_int_env("RABBITMQ_PORT", 5672)

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
# Chunks merged into RAG context (default 8; was effectively 1 via client default and hurt recall).
KNOWLEDGE_STORE_N_RESULTS = get_int_env("KNOWLEDGE_STORE_N_RESULTS", 8)

# Model Configuration (causal instruct LLM; same default hub id as MAS)
MODEL_NAME = os.getenv("MODEL_NAME", "Qwen/Qwen3-4B-Instruct-2507")
MODEL_DEVICE = os.getenv("MODEL_DEVICE", "auto")  # "auto", "cpu", "cuda", "cuda:0", etc.

AGENT_TYPE = os.getenv("AGENT_TYPE", "general")
# Delegation Configuration
DELEGATION_TIMEOUT = get_float_env("DELEGATION_TIMEOUT", 30.0)
MAX_DELEGATION_DEPTH = get_int_env("MAX_DELEGATION_DEPTH", 5)
