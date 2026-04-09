FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt /app/requirements.txt

RUN pip install --no-cache-dir -r /app/requirements.txt

# Install OpenTelemetry auto-instrumentation
RUN opentelemetry-bootstrap --action=install

# Network only during docker build: snapshot Qwen into /opt (survives dev bind-mount of /app).
ARG DOWNLOAD_LLM=1
ENV HF_HUB_DISABLE_TELEMETRY=1
RUN if [ "$DOWNLOAD_LLM" = "1" ]; then \
    mkdir -p /opt/llm-bundle && \
    python -c "from huggingface_hub import snapshot_download; snapshot_download(repo_id='Qwen/Qwen3-4B-Instruct-2507', local_dir='/opt/llm-bundle/Qwen3_instruct_4B', local_dir_use_symlinks=False)"; \
    fi

# Copy the agent application as the working dir
COPY ./app/ /app/

COPY entrypoint.sh /entrypoint.sh
# Windows CRLF in build context breaks shebang + `set -eu` lines; strip before run.
RUN sed -i 's/\r$//' /entrypoint.sh && chmod +x /entrypoint.sh

# Default: no Hub calls at runtime if the bundle or host app/models is populated.
ENV HF_HUB_OFFLINE=1
ENV TRANSFORMERS_OFFLINE=1

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

# Invoke via sh so we never rely on kernel shebang (avoids "no such file" with bad CRLF/bash).
ENTRYPOINT ["/bin/sh", "/entrypoint.sh"]
# Use opentelemetry-instrument for auto-instrumentation (no --reload flag)
CMD ["opentelemetry-instrument", "uvicorn", "agent_server.server:app", "--host", "0.0.0.0", "--port", "8001"]


