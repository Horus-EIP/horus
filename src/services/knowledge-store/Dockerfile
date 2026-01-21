FROM python:3.9-slim

WORKDIR /

COPY requirements.txt .
COPY ./app/ app/
COPY ./chroma_data/ chroma_data/

RUN pip install --no-cache-dir -r requirements.txt

# Install OpenTelemetry auto-instrumentation
RUN opentelemetry-bootstrap --action=install

# Create document storage directories
RUN mkdir -p documents/txt documents/pdf documents/docx documents/image

# OpenTelemetry Configuration for Tempo
ENV OTEL_SERVICE_NAME=knowledge-store
ENV OTEL_EXPORTER_OTLP_ENDPOINT=http://tempo:4317
ENV OTEL_EXPORTER_OTLP_PROTOCOL=grpc
ENV OTEL_TRACES_EXPORTER=otlp
ENV OTEL_METRICS_EXPORTER=none
ENV OTEL_LOGS_EXPORTER=none

EXPOSE 8080

# Use opentelemetry-instrument for auto-instrumentation (no --reload flag)
CMD ["opentelemetry-instrument", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]


