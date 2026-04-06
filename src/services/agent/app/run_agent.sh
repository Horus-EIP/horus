#!/bin/bash

# Configuration for local development
export ORCHESTRATOR_URL="http://localhost:8000"

# Credentials matching src/infra/.env
export ORCHESTRATOR_USERNAME="admin"
export ORCHESTRATOR_PASSWORD="secret"

# RabbitMQ Credentials (from src/infra/.env)
export RABBITMQ_HOST="localhost"
export RABBITMQ_USER="user"
export RABBITMQ_PASSWORD="password"
export RABBITMQ_PORT="5672"

# Observability
export OTEL_EXPORTER_OTLP_ENDPOINT="http://localhost:4317"

# Agent Settings
export AGENT_DESCRIPTION="Data Extraction Agent"
export MODEL_NAME="t5-small"

echo "Starting Agent Server on port 8001..."
uvicorn agent_server.server:app --host 0.0.0.0 --port 8001
