# 3.11 matches the agent image and PyTorch cu124 wheels on the extra index; 3.13 often
# resolved to a CPU-only torch wheel → cuda.is_available()=False → huge RAM, no GPU use.
FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive

WORKDIR /app

COPY ./requirements.txt ./requirements.txt

# Install build dependencies for grpcio and other packages.
# --no-install-recommends avoids manpages/man-db triggers that often yield apt exit 100 in slim images.
RUN apt-get update -o Acquire::Retries=5 \
    && apt-get install -y --no-install-recommends \
        curl \
        build-essential \
        g++ \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* /var/cache/apt/archives/*

RUN pip install --no-cache-dir --use-deprecated=legacy-resolver -r requirements.txt

# Install OpenTelemetry auto-instrumentation
RUN opentelemetry-bootstrap --action=install

COPY . .

# Orchestrator LLM: download once at image build (needs network during `docker build` only).
ARG DOWNLOAD_LLM=1
ENV HF_HUB_DISABLE_TELEMETRY=1
RUN if [ "$DOWNLOAD_LLM" = "1" ]; then \
    mkdir -p models && \
    python -c "from huggingface_hub import snapshot_download; snapshot_download(repo_id='Qwen/Qwen3-4B-Instruct-2507', local_dir='models/Qwen3_instruct_4B', local_dir_use_symlinks=False)"; \
    fi

# Prefer local files; block accidental Hub access when running air-gapped (override in .env if needed).
ENV HF_HUB_OFFLINE=1
ENV TRANSFORMERS_OFFLINE=1

ENV RABBITMQ_HOST=rabbitmq

# OpenTelemetry Configuration for Tempo
ENV OTEL_SERVICE_NAME=mas
ENV OTEL_EXPORTER_OTLP_ENDPOINT=http://tempo:4317
ENV OTEL_EXPORTER_OTLP_PROTOCOL=grpc
ENV OTEL_TRACES_EXPORTER=otlp
ENV OTEL_METRICS_EXPORTER=none
ENV OTEL_LOGS_EXPORTER=none

EXPOSE 8000

RUN chmod +x entrypoint.sh

ENTRYPOINT ["/bin/bash", "entrypoint.sh"]


