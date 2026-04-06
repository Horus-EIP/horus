
echo "Starting MAS Service Container..."

# Run migrations
echo "Running Database Migrations..."
(cd db && alembic upgrade head)

# Initialize database (create admin user)
echo "Initializing Database..."
python -c "from db.init_setup import init_db; init_db()"

# Start the application with OpenTelemetry auto-instrumentation
echo "Starting Uvicorn with OpenTelemetry..."
exec opentelemetry-instrument uvicorn main:app --host 0.0.0.0 --port 8000