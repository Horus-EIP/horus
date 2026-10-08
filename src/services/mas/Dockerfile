FROM python:3.11.17-slim

ENV DEBIAN_FRONTEND=noninteractive

WORKDIR /app

COPY requirements.lock requirements-gpu.lock ./

# Install build dependencies for grpcio and other packages.
# --no-install-recommends avoids manpages/man-db triggers that often yield apt exit 100 in slim images.
RUN apt-get update -o Acquire::Retries=5 \
    && apt-get install -y --no-install-recommends \
        curl \
        build-essential \
        g++ \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* /var/cache/apt/archives/*

ARG TORCH_INDEX_URL=https://pypi.org/simple
RUN case "$TORCH_INDEX_URL" in \
        https://download.pytorch.org/whl/cpu) cp requirements.lock requirements-image.txt ;; \
        *) cp requirements-gpu.lock requirements-image.txt ;; \
    esac

RUN --mount=type=cache,target=/root/.cache/pip \
    torch_pin="$(grep -oE '^torch==[0-9.]+' requirements-image.txt || true)" \
    && if [ -n "$torch_pin" ]; then \
        pip install --timeout=120 --retries=10 --index-url "$TORCH_INDEX_URL" "$torch_pin"; \
    fi

# Cache pip downloads across builds (BuildKit) + patient timeouts/retries so large
# ML wheels (torch ~500MB) don't abort on a slow/flaky network read timeout, and a
# completed download is reused on the next rebuild instead of re-fetched.
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --use-deprecated=legacy-resolver --timeout=120 --retries=10 --require-hashes -r requirements-image.txt

# Install OpenTelemetry auto-instrumentation
RUN opentelemetry-bootstrap --action=install

COPY . .

# Orchestrator LLM is NOT baked into the image anymore. It downloads on first
# container start into a mounted named volume (see entrypoint.sh + compose
# ``mas_model_cache`` volume). Keeps the image at ~3 GB instead of ~11 GB and
# makes rebuilds fast.

# Sentence-embedding model for skill suggestion. ~90 MB, CPU-only, used by
# /tasks/suggest-skills. Small enough to bake in so the suggest endpoint works
# the moment the container is up.
ENV HF_HUB_DISABLE_TELEMETRY=1
ENV FASTEMBED_CACHE_PATH=/app/models/fastembed
RUN python -c "from fastembed import TextEmbedding; TextEmbedding('sentence-transformers/all-MiniLM-L6-v2')"

# Default to ONLINE for the first run so bootstrap_llm.py can pull the LLM.
# Operators can flip both to 1 in their env once the cache volume is warm.
ENV HF_HUB_OFFLINE=0
ENV TRANSFORMERS_OFFLINE=0

ENV RABBITMQ_HOST=rabbitmq

# OpenTelemetry Configuration for Tempo
ENV OTEL_SERVICE_NAME=mas
ENV OTEL_EXPORTER_OTLP_ENDPOINT=http://tempo:4317
ENV OTEL_EXPORTER_OTLP_PROTOCOL=grpc
ENV OTEL_TRACES_EXPORTER=otlp
ENV OTEL_METRICS_EXPORTER=none
ENV OTEL_LOGS_EXPORTER=none

COPY --from=notices THIRD_PARTY_NOTICES /usr/share/doc/horus/THIRD_PARTY_NOTICES
COPY --from=notices LICENSES /usr/share/doc/horus/LICENSES
COPY --from=notices NOTICES /usr/share/doc/horus/NOTICES

EXPOSE 8000

RUN chmod +x entrypoint.sh

ENTRYPOINT ["/bin/bash", "entrypoint.sh"]


