FROM python:3.11.17-slim

WORKDIR /app

COPY requirements.lock requirements-gpu.lock /app/

ARG TORCH_INDEX_URL=https://pypi.org/simple
RUN case "$TORCH_INDEX_URL" in \
        https://download.pytorch.org/whl/cpu) cp /app/requirements.lock /app/requirements-image.txt ;; \
        *) cp /app/requirements-gpu.lock /app/requirements-image.txt ;; \
    esac

RUN --mount=type=cache,target=/root/.cache/pip \
    torch_pin="$(grep -oE '^torch==[0-9.]+' /app/requirements-image.txt || true)" \
    && if [ -n "$torch_pin" ]; then \
        pip install --timeout=120 --retries=10 --index-url "$TORCH_INDEX_URL" "$torch_pin"; \
    fi

# Cache pip downloads across builds (BuildKit cache mount — kept out of the final
# image) and be patient on slow/flaky networks so a large wheel (torch ~500MB)
# doesn't abort on pip's default 15s read timeout, and a completed download is
# reused on the next rebuild instead of re-fetched.
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --timeout=120 --retries=10 --require-hashes -r /app/requirements-image.txt

# Install OpenTelemetry auto-instrumentation
RUN opentelemetry-bootstrap --action=install

# Decision LLM is downloaded on first container start by entrypoint.sh into a
# mounted volume (see compose ``agent_model_cache``). Image stays slim and CI
# rebuilds are fast.
ENV HF_HUB_DISABLE_TELEMETRY=1

# Copy the agent application as the working dir
COPY ./app/ /app/

COPY entrypoint.sh /entrypoint.sh
# Windows CRLF in build context breaks shebang + `set -eu` lines; strip before run.
RUN sed -i 's/\r$//' /entrypoint.sh && chmod +x /entrypoint.sh

# Default to ONLINE so bootstrap_llm.py can pull on first start. Operators can
# flip both to 1 in their env once the cache volume is warm.
ENV HF_HUB_OFFLINE=0
ENV TRANSFORMERS_OFFLINE=0

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


