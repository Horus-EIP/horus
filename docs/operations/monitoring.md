# Monitoring and observability

This document describes the monitoring stack shipped with **`src/infra/docker-compose.yml`** (repository root): metrics (Prometheus), traces (Tempo, OTLP), dashboards (Grafana), plus admin UIs for data stores.

---

## Stack overview

| Layer | Components |
|-------|------------|
| Data stores | PostgreSQL, Redis, RabbitMQ, ChromaDB (Knowledge Store volume) |
| Metrics | Prometheus scrapes MAS, Agent, and Knowledge Store `/metrics` endpoints |
| Traces | Grafana Tempo receives OTLP from application containers |
| Logs | Grafana Loki ingests stdout/stderr from **all Docker Compose services** via Promtail (Docker service discovery); explore in Grafana or open the **Stack logs (Loki)** dashboard |
| Visualization | Grafana (Prometheus + Tempo + Loki datasources provisioned from **`src/infra/grafana/datasources.yaml`**) |
| Admin UIs | PgAdmin, RedisInsight, RabbitMQ management plugin |

The default Compose file does **not** include SigNoz, a standalone OpenTelemetry Collector service, PostgreSQL Exporter, or Metabase. If you add those services, extend this document accordingly.

### Quick start

```bash
cd src/infra
docker compose up -d
```

PostgreSQL is started with `pg_stat_statements` preloading (see the `postgres` service `command` in Compose). If you change extension-related settings, restart the stack: `docker compose down && docker compose up -d`.

---

## Grafana

Primary UI for metrics and traces in local development.

| Item | Value |
|------|--------|
| URL | http://localhost:3301 |
| Map | Host port `3301` maps to Grafana’s internal port `3000` |

Default credentials in Compose: `admin` / `admin`. Anonymous viewers are enabled for local use; tighten `GF_AUTH_*` for production.

### Provisioned dashboards

Compose mounts **`src/infra/grafana/provisioning/dashboards/`** (provider YAML) and **`src/infra/grafana/dashboards/`** (JSON dashboards, e.g. `mas_dashboard.json`) into the Grafana container. After `docker compose up -d`, open **Dashboards** in Grafana; if you changed mounts, restart Grafana: `docker compose up -d grafana`.

### Provisioned datasources

- **Prometheus** at `http://prometheus:9090` (Docker network; used by Grafana panels and Explore).
- **Tempo** at `http://tempo:3200` for trace queries; trace-to-metrics links use the Prometheus datasource.
- **Loki** at `http://loki:3100` for log queries (labels include `compose_service`, `compose_project`, `container`).

### Log retention and integrity (Loki)

In **`src/infra/grafana/loki.yaml`**, the compactor has **`retention_enabled: false`** (no automatic expiry of old logs) and **`limits_config.allow_deletes: false`** (the log-deletion API is off). Loki’s ingest path is append-only: existing lines are not updated in place through the query API.

That is **not** cryptographic immutability: anyone who can remove the Docker volume or files on disk can still destroy data. For strict write-once retention (for example compliance), use object storage with **Object Lock** (or an enterprise log archive) and restrict who can change buckets or Compose volumes.

### Optional manual steps

1. **Explore**: Open **Explore**, choose **Tempo** or **Prometheus**, and run queries or trace lookups.
2. **Dashboards**: Import community dashboards if needed; Prometheus scrape jobs are defined in **`src/infra/grafana/prometheus.yaml`**.

---

## Prometheus

| Item | Value |
|------|--------|
| Scrape config (mounted in Compose) | **`src/infra/grafana/prometheus.yaml`** |
| Jobs | `prometheus` (self), `mas-api`, `agent-api`, `knowledge-store` |

**Host access:** The `prometheus` service has **no** `ports:` mapping in the default Compose file. You cannot open `http://localhost:9090` on the host unless you add a port mapping. Use either:

- **Grafana** (Explore or dashboards) against the Prometheus datasource, or  
- **Docker**: `docker exec -it prometheus wget -qO- http://localhost:9090/api/v1/targets` (or add `9090:9090` under `prometheus` for local debugging only).

### Verification

Inside the Docker network, targets should include `mas:8000`, `agent:8001`, and `knowledge_store:8080` when those services are up. There is no `postgres` scrape job in the default config.

---

## Tempo (distributed tracing)

| Item | Value |
|------|--------|
| OTLP gRPC (from apps) | `tempo:4317` inside the network; host ports `4317` / `4318` are published for optional external collectors |
| App env | `OTEL_EXPORTER_OTLP_ENDPOINT=http://tempo:4317` (set per service in Compose) |

View traces in Grafana (**Explore** → **Tempo**).

---

## Application metrics endpoints

When services run on the host (not only in Docker), raw Prometheus text format is available at:

| Service | URL (default local) |
|---------|---------------------|
| MAS | http://localhost:8000/metrics/ |
| Agent | http://localhost:8001/metrics/ |
| Knowledge Store | http://localhost:8080/metrics/ |

---

## PgAdmin 4

- **URL:** http://localhost:5433  
- **Credentials:** `PGADMIN_DEFAULT_EMAIL` and `PGADMIN_DEFAULT_PASSWORD` in `src/infra/.env`.

Register a server with host `postgres`, port `5432`, database `postgres` (or your `POSTGRES_DB`), using `POSTGRES_USER` / `POSTGRES_PASSWORD` from `.env`.

---

## RedisInsight

- **URL:** http://localhost:5540  
- Add database: host `redis`, port `6379`, password from `REDIS_PASSWORD` in `.env`.

---

## RabbitMQ management

- **URL:** http://localhost:15672  
- **Credentials:** `RABBITMQ_USER` / `RABBITMQ_PASSWORD` in `.env`.

Monitor queues and connections for `mas` and `agent` consumers.

---

## Structured logging

### Log format

Services can emit structured JSON logs (example shape):

```json
{
  "timestamp": "2026-01-12T10:30:00.000Z",
  "level": "INFO",
  "logger": "task",
  "message": "Task created: task-123",
  "module": "routes",
  "function": "create_new_task",
  "line": 260,
  "correlation_id": "550e8400-e29b-41d4-a716-446655440000",
  "extra": {
    "task_id": "task-123",
    "agent_id": "agent-456",
    "conversation_id": 1
  }
}
```

### Correlation IDs

1. Incoming requests: `X-Request-ID` or `X-Correlation-ID` when present  
2. Otherwise: generated UUID  
3. Propagated downstream via headers  
4. Returned on responses where middleware supports it  

### Log levels

| Level | Use |
|-------|-----|
| DEBUG | Verbose diagnostics |
| INFO | Normal operation |
| WARNING | Recoverable anomalies |
| ERROR | Failures requiring attention |
| CRITICAL | Severe failures |

### Typical environment variables

```bash
LOG_LEVEL=INFO
JSON_LOGGING=true
```

---

## Metrics reference (MAS examples)

PromQL examples assume metric names exported by the MAS service; verify with `/metrics` if names differ.

```promql
rate(mas_http_requests_total[5m])
histogram_quantile(0.95, rate(mas_http_request_duration_seconds_bucket[5m]))
```

---

## Distributed tracing (application code)

Trace context is propagated via standard headers (for example W3C `traceparent` and correlation IDs) where instrumentation is enabled.

Example pattern (adjust imports to your service’s tracing module):

```python
from core.tracing import create_span, add_span_attributes

with create_span("my_operation", {"key": "value"}) as span:
    span.set_attribute("result", "success")
```

---

## Alerting

Grafana can alert on Prometheus metrics (rules and contact points configured in Grafana, not in the minimal Compose defaults). Suggested thresholds for your own rules:

| Signal | Warning | Critical |
|--------|---------|----------|
| Error rate | greater than 1% | greater than 5% |
| p95 latency | greater than 500 ms | greater than 2 s |
| Active agents | fewer than 2 | zero |
| Task queue depth | greater than 100 | greater than 500 |

---

## Environment variables reference

### MAS (excerpt)

```bash
LOG_LEVEL=INFO
JSON_LOGGING=true
OTEL_ENABLED=true
OTEL_SERVICE_NAME=mas
OTEL_EXPORTER_OTLP_ENDPOINT=http://tempo:4317
TASK_TIMEOUT_SECONDS=300
```

In Docker Compose, `OTEL_EXPORTER_OTLP_ENDPOINT` points at the `tempo` service, not a separate OpenTelemetry Collector container.

### Agent and Knowledge Store

Follow the same `OTEL_*` pattern as in Compose for each service; see service-specific env blocks in `docker-compose.yml`.

---

## Performance impact

Observability adds small per-request overhead (logging, metrics, tracing). To reduce load in production: raise `LOG_LEVEL`, use trace sampling if configured in instrumentation, and reserve sufficient resources for Tempo and Prometheus volumes.

---

## Troubleshooting

### Grafana shows no Prometheus data

- Confirm `prometheus`, `mas`, `agent`, and `knowledge_store` containers are running.  
- In Grafana → Explore → Prometheus, run a simple query such as `up`.  
- If Prometheus is unreachable from Grafana, check the Docker network and **`src/infra/grafana/datasources.yaml`**.

### Cannot open Prometheus on the host

- Expected with the default Compose file: add a host port for `prometheus` or use Grafana / `docker exec` as described above.

### No traces in Grafana

- Ensure `OTEL_ENABLED=true` and `OTEL_EXPORTER_OTLP_ENDPOINT=http://tempo:4317` for the service.  
- Check `docker logs tempo` and that the app container can resolve `tempo`.

### Connection refused from PgAdmin to the database

- From PgAdmin running in Docker, use host `postgres`, not `localhost`.

### Slow query panels empty

- Confirm `pg_stat_statements` is loaded (`postgres` service command in Compose).  
- Test in SQL: `SELECT * FROM pg_stat_statements LIMIT 5;`

### Logs not JSON

- Set `JSON_LOGGING=true` and restart the service.

---

## References

- [Grafana documentation](https://grafana.com/docs/)  
- [Prometheus documentation](https://prometheus.io/docs/)  
- [Grafana Tempo documentation](https://grafana.com/docs/tempo/latest/)  
- [OpenTelemetry Python](https://opentelemetry.io/docs/languages/python/)
