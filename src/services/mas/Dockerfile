FROM python:3.13-slim

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


