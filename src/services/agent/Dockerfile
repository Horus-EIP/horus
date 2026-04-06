FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt /app/requirements.txt

RUN pip install --no-cache-dir -r /app/requirements.txt

# Install OpenTelemetry auto-instrumentation
RUN opentelemetry-bootstrap --action=install

# Copy the agent application as the working dir
COPY ./app/ /app/

ENV ORCHESTRATOR_URL=http://mas:8000
ENV RABBITMQ_HOST=rabbitmq

# OpenTelemetry Configuration for Tempo
ENV OTEL_SERVICE_NAME=agent
ENV OTEL_EXPORTER_OTLP_ENDPOINT=http://tempo:4317
ENV OTEL_EXPORTER_OTLP_PROTOCOL=grpc
ENV OTEL_TRACES_EXPORTER=otlp
ENV OTEL_METRICS_EXPORTER=none
ENV OTEL_LOGS_EXPORTER=none

EXPOSE 8001

# Use opentelemetry-instrument for auto-instrumentation (no --reload flag)
CMD ["opentelemetry-instrument", "uvicorn", "agent_server.server:app", "--host", "0.0.0.0", "--port", "8001"]


