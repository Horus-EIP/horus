# Observability Guide

This document describes the observability stack for the Horus Multi-Agent System, including logging, metrics, and distributed tracing.

## Overview

The Horus system implements a comprehensive **all-in-one observability stack** using **SigNoz**:

| Component | Purpose | Technology |
|-----------|---------|------------|
| **Logging** | Structured JSON logs | Python logging + custom formatters |
| **Metrics** | Performance & business metrics | SigNoz (OpenTelemetry-based) |
| **Tracing** | Distributed request tracing | SigNoz (OpenTelemetry-based) |

### Why SigNoz?

SigNoz replaces the traditional Prometheus + Grafana + Jaeger stack with a single, unified solution:

- ✅ **Single UI** for metrics, traces, and logs
- ✅ **OpenTelemetry native** - industry standard
- ✅ **Open source & self-hosted** - free forever
- ✅ **ClickHouse backend** - fast queries at scale
- ✅ **Lower complexity** - one system to learn

## Quick Start

### Accessing SigNoz

After starting the system with `docker compose up`:

| Tool | URL | Purpose |
|------|-----|---------|
| **SigNoz UI** | http://localhost:3301 | Metrics, traces, logs, dashboards |
| MAS Metrics | http://localhost:8000/metrics/ | Raw Prometheus metrics |
| Agent Metrics | http://localhost:8001/metrics/ | Raw Prometheus metrics |
| Knowledge Store Metrics | http://localhost:8080/metrics/ | Raw Prometheus metrics |

### First Time Setup

1. Open http://localhost:3301
2. SigNoz requires no login for local development
3. Navigate to:
   - **Services** → See all services sending telemetry
   - **Traces** → Search and analyze distributed traces
   - **Dashboards** → Create custom dashboards
   - **Alerts** → Set up alerting rules

---

## Structured Logging

### Log Format

All services output structured JSON logs with the following fields:

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

Every request is assigned a correlation ID for tracing:

1. **Incoming requests**: Extracted from `X-Request-ID` or `X-Correlation-ID` headers
2. **Generated**: New UUID if no header present
3. **Propagated**: Passed to downstream services via headers
4. **Response**: Added to response headers for client tracking

### Log Levels

| Level | When to Use |
|-------|-------------|
| DEBUG | Detailed debugging information |
| INFO | Normal operation events |
| WARNING | Unexpected but recoverable situations |
| ERROR | Errors that need attention |
| CRITICAL | System failures |

### Configuration

Environment variables for logging:

```bash
# MAS and Agent services
LOG_LEVEL=INFO          # DEBUG, INFO, WARNING, ERROR
JSON_LOGGING=true       # true for JSON, false for colored console
LOG_DIR=logs            # Directory for log files
```

---

## Metrics with SigNoz

### Viewing Metrics

1. Open SigNoz UI at http://localhost:3301
2. Go to **Dashboards** → **New Dashboard**
3. Add panels using PromQL queries

### MAS Metrics

Available at `http://localhost:8000/metrics/`

#### HTTP Metrics
```promql
# Request count by method, endpoint, status
mas_http_requests_total{method="POST", endpoint="/tasks/new_task/", status_code="200"}

# Request latency histogram
mas_http_request_duration_seconds_bucket{method="POST", endpoint="/tasks/new_task/", le="0.5"}

# Requests in progress
mas_http_requests_in_progress{method="POST", endpoint="/tasks/new_task/"}
```

#### Agent Metrics
```promql
# Total agents by status
mas_agents_total{status="active"}

# Agent registrations
mas_agent_registrations_total{status="success"}

# Agent heartbeats
mas_agent_heartbeats_total{agent_id="...", status="success"}
```

#### Task Metrics
```promql
# Tasks by status
mas_tasks_total{status="completed"}

# Task queue depth
mas_task_queue_depth{status="pending"}

# Task processing time
mas_task_processing_duration_seconds_bucket{agent_id="...", le="5.0"}
```

### Useful Queries in SigNoz

```promql
# Request rate (requests per second)
rate(mas_http_requests_total[5m])

# Error rate
rate(mas_errors_total[5m])

# 95th percentile latency
histogram_quantile(0.95, rate(mas_http_request_duration_seconds_bucket[5m]))

# Active agents
mas_agents_total{status="active"}

# Task queue depth
mas_task_queue_depth{status="pending"}
```

---

## Distributed Tracing with SigNoz

### Viewing Traces

1. Open SigNoz UI at http://localhost:3301
2. Go to **Traces**
3. Filter by:
   - Service name (e.g., `mas`)
   - Operation name
   - Duration (e.g., `> 1s`)
   - Tags/attributes

### Understanding Traces

A trace shows the full journey of a request:

```
[MAS] POST /tasks/new_task/
  ├── [MAS] select_agent_for_task
  │     └── [MAS] LLM query
  ├── [MAS] insert_new_task (DB)
  └── [MAS] publish_to_rabbitmq
      └── [Agent] process_task
            ├── [Agent] RAG query
            │     └── [KnowledgeStore] /store/query
            └── [Agent] model_inference
```

### Adding Custom Spans

```python
from core.tracing import create_span, add_span_attributes

# Create a span for custom operations
with create_span("my_operation", {"key": "value"}) as span:
    # Do work...
    span.set_attribute("result", "success")
```

### Trace Context Propagation

Trace context is automatically propagated via headers:
- `traceparent` - W3C Trace Context
- `X-Request-ID` - Correlation ID

For manual propagation to external services:
```python
from core.tracing import inject_trace_context

headers = inject_trace_context({"Authorization": "..."})
requests.post(external_url, headers=headers)
```

---

## Configuration Reference

### MAS Environment Variables

```bash
# Logging
LOG_LEVEL=INFO
JSON_LOGGING=true
LOG_DIR=logs

# Tracing (OpenTelemetry)
OTEL_ENABLED=true
OTEL_SERVICE_NAME=mas
OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4317

# Task configuration
TASK_TIMEOUT_SECONDS=300
```

### Agent Environment Variables

```bash
AGENT_LOG_LEVEL=INFO
AGENT_JSON_LOGGING=true
```

### Knowledge Store Environment Variables

```bash
LOG_LEVEL=INFO
JSON_LOGGING=true
```

---

## Alerting in SigNoz

### Setting Up Alerts

1. Go to **Alerts** in SigNoz UI
2. Click **New Alert**
3. Choose alert type:
   - **Metric-based**: PromQL queries
   - **Trace-based**: Latency/error thresholds
   - **Log-based**: Log pattern matching

### Key Metrics to Alert On

| Metric | Warning | Critical |
|--------|---------|----------|
| Error rate | > 1% | > 5% |
| Response time (p95) | > 500ms | > 2s |
| Active agents | < 2 | 0 |
| Task queue depth | > 100 | > 500 |
| Failed heartbeats | > 5/min | > 20/min |

### Example Alert Rule

In SigNoz UI, create an alert with:

- **Query**: `rate(mas_errors_total[5m]) > 0.05`
- **Condition**: When value is above threshold
- **Duration**: 5 minutes
- **Severity**: Warning
- **Notification**: Configure Slack, email, PagerDuty, etc.

---

## Architecture

```
┌─────────────┐     ┌─────────────┐     ┌─────────────────┐
│     MAS     │────▶│    OTEL     │────▶│   ClickHouse    │
│   Service   │     │  Collector  │     │   (Storage)     │
└─────────────┘     └─────────────┘     └─────────────────┘
       │                   │                     │
       │                   │                     ▼
┌─────────────┐           │           ┌─────────────────┐
│    Agent    │───────────┤           │  SigNoz Query   │
│   Service   │           │           │    Service      │
└─────────────┘           │           └─────────────────┘
       │                   │                     │
┌─────────────┐           │                     ▼
│  Knowledge  │───────────┘           ┌─────────────────┐
│    Store    │                       │  SigNoz Frontend│
└─────────────┘                       │   (Web UI)      │
                                      └─────────────────┘
                                              │
                                              ▼
                                      http://localhost:3301
```

### Components

| Container | Purpose | Port |
|-----------|---------|------|
| `otel-collector` | Receives telemetry (OTLP) | 4317, 4318 |
| `clickhouse` | Time-series database | Internal |
| `signoz-query` | Query API backend | Internal |
| `signoz-frontend` | Web UI | 3301 |

---

## Troubleshooting

### No Metrics in SigNoz

1. Check services are running: `docker ps`
2. Verify OTEL collector is healthy:
   ```bash
   docker logs otel-collector
   ```
3. Test metrics endpoint:
   ```bash
   curl http://localhost:8000/metrics/
   ```
4. Check OTEL collector config scrape targets

### Traces Not Showing

1. Verify OTEL_ENABLED=true in service environment
2. Check OTEL exporter endpoint connectivity:
   ```bash
   docker exec mas curl -v http://otel-collector:4317
   ```
3. Check collector logs for errors

### ClickHouse Issues

1. Check ClickHouse health:
   ```bash
   docker logs clickhouse
   ```
2. Verify disk space isn't full
3. Check ulimits are properly set

### Logs Not in JSON Format

1. Set `JSON_LOGGING=true` in environment
2. Restart the service
3. Verify in container logs: `docker logs mas`

---

## Performance Impact

Observability overhead is minimal:
- Logging: ~1ms per request
- Metrics: ~0.5ms per request
- Tracing: ~2ms per request (when enabled)

To reduce overhead in production:
- Set `LOG_LEVEL=WARNING`
- Sample traces: Configure sampling in OTEL collector

---

## Comparison: Before vs After

| Aspect | Before (3 tools) | After (SigNoz) |
|--------|------------------|----------------|
| **Containers** | Prometheus + Grafana + Jaeger (3) | SigNoz stack (4)* |
| **UIs to learn** | 3 different UIs | 1 unified UI |
| **Query languages** | PromQL + TraceQL | PromQL (familiar) |
| **Storage** | Prometheus TSDB + Badger | ClickHouse (unified) |
| **Alerting** | Separate setup | Built-in |

*SigNoz uses 4 containers (ClickHouse, Query Service, Frontend, OTEL Collector) but provides a unified experience.

---

## References

- [SigNoz Documentation](https://signoz.io/docs/)
- [OpenTelemetry Python](https://opentelemetry.io/docs/instrumentation/python/)
- [ClickHouse Documentation](https://clickhouse.com/docs/)
- [SigNoz GitHub](https://github.com/SigNoz/signoz)
