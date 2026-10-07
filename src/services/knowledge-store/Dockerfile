# Builder stage
FROM python:3.11-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /venv
ENV PATH="/venv/bin:$PATH"

RUN pip install --upgrade pip setuptools wheel

COPY requirements.lock requirements-gpu.lock ./

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
# ML wheels don't abort on a slow/flaky network read timeout, and a completed
# download is reused on the next rebuild instead of re-fetched.
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --timeout=120 --retries=10 --require-hashes -r requirements-image.txt

# Final image
FROM python:3.11-slim

WORKDIR /app

# Runtime system dependencies for PDF and OCR processing
RUN apt-get update && apt-get install -y --no-install-recommends \
    poppler-utils \
    tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /venv /venv
ENV PATH=/venv/bin:$PATH

COPY ./app/ app/
COPY ./chroma_data/ chroma_data/

ENV FASTEMBED_CACHE_PATH=/app/.cache/fastembed

# Install OpenTelemetry auto-instrumentation
RUN opentelemetry-bootstrap --action=install
# Pre-download embedding model at build time to avoid latency on first request
RUN python -c "from fastembed import TextEmbedding; TextEmbedding('BAAI/bge-base-en-v1.5')"

# After build, default to no Hub access (embedding weights are in the image cache).
ENV HF_HUB_OFFLINE=1
ENV TRANSFORMERS_OFFLINE=1

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

CMD ["opentelemetry-instrument", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
