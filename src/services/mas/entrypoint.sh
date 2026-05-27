#!/bin/bash

echo "Starting MAS Service Container..."

# Download the orchestrator LLM if missing. No-op when the model volume is
# already populated; fails loudly if HF_HUB_OFFLINE=1 and the model isn't there.
echo "Bootstrapping orchestrator LLM (if missing)..."
python bootstrap_llm.py || { echo "LLM bootstrap failed"; exit 1; }

# Run migrations
echo "Running Database Migrations..."
(cd db && alembic upgrade head)

# Initialize database (create admin user)
echo "Initializing Database..."
python -c "from db.init_setup import init_db; init_db()"

# Start the application with OpenTelemetry auto-instrumentation
echo "Starting Uvicorn with OpenTelemetry..."
exec opentelemetry-instrument uvicorn main:app --host 0.0.0.0 --port 8000
