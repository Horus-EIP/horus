# Telemetry Posture - Horus Multi-Agent System

**Document Type:** Telemetry & Data Collection Disclosure  
**Version:** 1.0  
**Last Updated:** January 2026  
**Classification:** Internal

---

## 1. Overview

This document describes the telemetry, metrics, and logging data collected by the Horus Multi-Agent System, how it is used, and how users can control this data collection.

### 1.1 Purpose

Telemetry is collected to:
- Monitor system health and performance
- Debug issues and improve reliability
- Understand usage patterns for optimization
- Ensure security and detect anomalies

### 1.2 Principles

- **Transparency:** All data collection documented
- **Minimization:** Collect only what's necessary
- **Control:** Users can opt-out where applicable
- **Security:** Telemetry data protected like other data

---

## 2. Telemetry Categories

### 2.1 Categories Overview

| Category | Default State | Opt-Out Available | Contains PII |
|----------|---------------|-------------------|--------------|
| System Metrics | Enabled | No | No |
| Application Logs | Enabled | Configurable | Minimal |
| Distributed Traces | Enabled | Configurable | No |
| User Analytics | Disabled | N/A | N/A |
| Error Reports | Enabled | Configurable | Minimal |

---

## 3. System Metrics

### 3.1 Infrastructure Metrics

**What is collected:**
- CPU and memory usage per container
- Network I/O statistics
- Disk usage and I/O
- Container health status

**How it's collected:**
- Docker stats API
- Prometheus node exporter (if deployed)

**Retention:** 15 days

**Example:**
```
container_cpu_usage_seconds_total{container="mas"} 123.45
container_memory_usage_bytes{container="mas"} 536870912
```

### 3.2 Application Metrics

**MAS Metrics:**
| Metric | Description | Labels |
|--------|-------------|--------|
| `mas_http_requests_total` | Total HTTP requests | method, endpoint, status |
| `mas_http_request_duration_seconds` | Request latency | method, endpoint |
| `mas_agents_total` | Active agents | status |
| `mas_tasks_total` | Task count | status |
| `mas_errors_total` | Error count | type, component |
| `mas_websocket_connections` | Active WebSocket connections | - |

**Agent Metrics:**
| Metric | Description | Labels |
|--------|-------------|--------|
| `agent_tasks_processed_total` | Tasks processed | status |
| `agent_rag_query_duration_seconds` | RAG query time | - |
| `agent_model_inference_seconds` | Model inference time | - |

**Knowledge Store Metrics:**
| Metric | Description | Labels |
|--------|-------------|--------|
| `ks_queries_total` | Total queries | collection |
| `ks_query_duration_seconds` | Query latency | collection |
| `ks_documents_total` | Document count | collection |

### 3.3 What is NOT Collected

- Do not include User identities in metrics
- Do not include Message content
- Do not include Document content
- Do not include IP addresses
- Do not include Query text

---

## 4. Application Logs

### 4.1 Log Content

**Information Logged:**
- Timestamp (ISO 8601)
- Log level (DEBUG, INFO, WARN, ERROR)
- Component/service name
- Correlation ID (for request tracing)
- Event description
- Non-PII context data

**Example Log Entry:**
```json
{
  "timestamp": "2026-01-12T10:30:00Z",
  "level": "INFO",
  "logger": "mas.tasks",
  "message": "Task created",
  "correlation_id": "abc-123-def",
  "task_id": "task_456",
  "agent_id": "agent_789"
}
```

### 4.2 PII Handling in Logs

**Sanitized:**
- Usernames → User ID only
- Email addresses → Not logged
- IP addresses → Hashed or omitted
- Passwords → Never logged
- Query content → Not logged in production

**Configuration:**
```python
# core/config.py
LOG_SANITIZE_PII = True  # Enable PII sanitization
LOG_LEVEL = "INFO"       # Production default
```

### 4.3 Log Levels

| Level | Contents | When Used |
|-------|----------|-----------|
| ERROR | Exception details, stack traces | System errors |
| WARN | Potential issues | Degraded operations |
| INFO | Key events | Normal operations |
| DEBUG | Detailed flow | Development only |

### 4.4 Log Retention

| Environment | Retention | Storage |
|-------------|-----------|---------|
| Production | 30 days | Centralized logging |
| Development | 7 days | Container stdout |

---

## 5. Distributed Traces

### 5.1 Trace Content

**What is included:**
- Trace ID (unique identifier)
- Span ID (operation identifier)
- Operation name
- Duration
- Service name
- HTTP method and status code
- Non-sensitive attributes

**What is NOT included:**
- Do not include Request/response bodies
- Do not include User identifiers
- Do not include Authentication tokens
- Do not include Document content

### 5.2 Trace Example

```
Trace: abc123
├── Span: MAS receive request (50ms)
│   ├── method: POST
│   ├── path: /tasks/new_task/
│   └── status: 200
├── Span: Task publish (10ms)
│   └── queue: task_queue
└── Span: Agent process (3000ms)
    └── status: completed
```

### 5.3 Sampling

**Default Configuration:**
- 100% sampling in development
- 10% sampling in production (adjustable)

```python
# core/tracing.py
SAMPLING_RATE = 0.1  # 10% of traces
```

---

## 6. Error Reporting

### 6.1 Error Report Content

**Included:**
- Error type and message
- Stack trace (code paths only)
- Correlation ID
- Timestamp
- Service/component name
- Environment (dev/staging/prod)

**Not Included:**
- Do not include User data
- Do not include Request payloads
- Do not include Sensitive configuration

### 6.2 Example Error Report

```json
{
  "error_type": "DatabaseConnectionError",
  "message": "Connection refused",
  "stack_trace": "File db/database.py, line 45...",
  "correlation_id": "xyz-789",
  "timestamp": "2026-01-12T10:35:00Z",
  "service": "mas",
  "environment": "production"
}
```

---

## 7. User Analytics

### 7.1 Current State

**User analytics is DISABLED by default.**

No user behavior tracking is performed unless explicitly enabled.

### 7.2 If Enabled (Future)

If user analytics were enabled, it would collect:
- Feature usage (anonymized)
- Session duration (aggregated)
- Error frequency (no user correlation)

**Would NOT collect:**
- Do not include Individual user tracking
- Do not include Query content
- Do not include Browsing history
- Do not include Third-party tracking

---

## 8. Data Flow

### 8.1 Telemetry Data Flow

```
┌─────────────┐
│   Service   │
│  (MAS/Agent)│
└──────┬──────┘
       │
       ▼
┌─────────────┐     ┌─────────────┐
│   Metrics   │────▶│ Prometheus  │────▶ Retention: 15 days
└─────────────┘     └─────────────┘
       │
       ▼
┌─────────────┐     ┌─────────────┐
│    Logs     │────▶│   stdout    │────▶ Retention: 30 days
└─────────────┘     └─────────────┘
       │
       ▼
┌─────────────┐     ┌─────────────┐
│   Traces    │────▶│   Jaeger    │────▶ Retention: 7 days
└─────────────┘     └─────────────┘
```

### 8.2 Storage Locations

| Data Type | Storage | Encryption | Access Control |
|-----------|---------|------------|----------------|
| Metrics | Prometheus | No | Network isolation |
| Logs | Container/Host | Optional | File permissions |
| Traces | Jaeger | No | Network isolation |

---

## 9. Configuration

### 9.1 Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `LOG_LEVEL` | INFO | Logging verbosity |
| `LOG_FORMAT` | json | Log format (json/text) |
| `OTEL_TRACES_SAMPLER_ARG` | 0.1 | Trace sampling rate |
| `METRICS_ENABLED` | true | Enable/disable metrics |
| `TRACING_ENABLED` | true | Enable/disable tracing |

### 9.2 Disable Telemetry

**Disable Metrics:**
```yaml
# docker-compose.yml
services:
  mas:
    environment:
      - METRICS_ENABLED=false
```

**Disable Tracing:**
```yaml
services:
  mas:
    environment:
      - TRACING_ENABLED=false
```

**Reduce Logging:**
```yaml
services:
  mas:
    environment:
      - LOG_LEVEL=WARN
```

---

## 10. Third-Party Services

### 10.1 Current State

**No telemetry is sent to external services by default.**

All telemetry is stored and processed locally within the deployment.

### 10.2 If External Services Used

If cloud observability services are configured (e.g., Datadog, New Relic):

| Requirement | Implementation |
|-------------|----------------|
| Data Processing Agreement | Required |
| PII Filtering | Must be enabled |
| Region Selection | EU preferred for GDPR |
| Encryption | TLS required |

---

## 11. User Controls

### 11.1 Available Controls

| Control | How to Apply |
|---------|--------------|
| Disable metrics collection | Set `METRICS_ENABLED=false` |
| Disable tracing | Set `TRACING_ENABLED=false` |
| Reduce log verbosity | Set `LOG_LEVEL=WARN` |
| Request data deletion | Contact administrator |

### 11.2 Operator Controls

| Control | How to Apply |
|---------|--------------|
| Adjust retention periods | Update Prometheus/Jaeger config |
| Configure sampling | Set `OTEL_TRACES_SAMPLER_ARG` |
| Filter sensitive data | Configure log sanitization |
| Export telemetry | Use Prometheus/Jaeger export APIs |

---

## 12. Compliance Alignment

### 12.1 GDPR Alignment

| Requirement | Status |
|-------------|--------|
| Lawful basis for processing | Legitimate interest (system operation) |
| Purpose limitation | Documented purposes only |
| Data minimization | No PII in telemetry |
| Storage limitation | Defined retention periods |
| Transparency | This document |

### 12.2 Security Measures

| Measure | Implementation |
|---------|----------------|
| Access control | Network isolation |
| Encryption | TLS available |
| Audit logging | Enabled |
| Data integrity | Prometheus TSDB |

---

## 13. Change Log

| Date | Change |
|------|--------|
| Jan 2026 | Initial telemetry posture documented |

---

## 14. Contact

For questions about telemetry:
- **Technical:** Development team
- **Privacy:** Data protection officer (if designated)
- **Compliance:** Legal/compliance team

---

## Appendix: Metric Reference

### MAS Service Metrics

```prometheus
# HTTP metrics
mas_http_requests_total{method="POST", endpoint="/tasks/new_task/", status_code="200"} 1234
mas_http_request_duration_seconds_bucket{method="GET", endpoint="/agents/", le="0.1"} 500

# Agent metrics
mas_agents_total{status="active"} 3
mas_agent_heartbeats_total{agent_id="agent_001", status="success"} 150

# Task metrics
mas_tasks_total{status="completed"} 500
mas_task_queue_depth{status="pending"} 5

# Error metrics
mas_errors_total{type="ValidationError", component="tasks"} 12
```

### Knowledge Store Metrics

```prometheus
# Query metrics
ks_queries_total{collection="default"} 1000
ks_query_duration_seconds_bucket{collection="default", le="0.5"} 950

# Document metrics
ks_documents_total{collection="default"} 250
ks_embedding_generation_seconds_bucket{le="1.0"} 240
```
