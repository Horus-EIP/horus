# Load Testing Suite

This directory contains Locust-based load tests for the Horus system.

## Prerequisites

```bash
pip install locust
```

## Running Load Tests

### MAS API Load Test

```bash
# With web UI (recommended for exploratory testing)
locust -f locustfile.py --host=http://localhost:8000

# Open http://localhost:8089 to configure and start the test

# Headless mode (for CI/CD)
locust -f locustfile.py --host=http://localhost:8000 \
    --users 100 \
    --spawn-rate 10 \
    --run-time 5m \
    --headless \
    --csv=results/mas_load
```

### Knowledge Store Load Test

```bash
locust -f knowledge_store_load.py --host=http://localhost:8080 \
    --users 50 \
    --spawn-rate 5 \
    --run-time 5m \
    --headless
```

## User Classes

### MAS Load Test (`locustfile.py`)

| User Type | Description | Weight |
|-----------|-------------|--------|
| `MASUser` | Typical end user | 60% |
| `AgentUser` | Simulated agent | 30% |
| `AdminUser` | Admin operations | 10% |

### Knowledge Store Load Test (`knowledge_store_load.py`)

| User Type | Description | Use Case |
|-----------|-------------|----------|
| `KnowledgeStoreUser` | Mixed operations | General load testing |
| `QueryOnlyUser` | Query-only | Query performance |
| `BurstUser` | Rapid-fire queries | Spike testing |

## Test Scenarios

### Scenario 1: Normal Load
```bash
locust -f locustfile.py --host=http://localhost:8000 \
    --users 50 --spawn-rate 5 --run-time 10m
```

### Scenario 2: Peak Load
```bash
locust -f locustfile.py --host=http://localhost:8000 \
    --users 200 --spawn-rate 20 --run-time 5m
```

### Scenario 3: Stress Test
```bash
locust -f locustfile.py --host=http://localhost:8000 \
    --users 500 --spawn-rate 50 --run-time 15m
```

### Scenario 4: Spike Test
```bash
# Start with low load
locust -f locustfile.py --host=http://localhost:8000 \
    --users 10 --spawn-rate 1 --run-time 2m

# Then spike to high load
locust -f locustfile.py --host=http://localhost:8000 \
    --users 200 --spawn-rate 100 --run-time 2m
```

## Performance Targets

| Metric | Target | Critical |
|--------|--------|----------|
| Avg Response Time | < 200ms | < 500ms |
| 95th Percentile | < 500ms | < 1000ms |
| Error Rate | < 0.1% | < 1% |
| Requests/sec | > 100 | > 50 |

## Output Files

When using `--csv=results/prefix`, Locust generates:
- `prefix_stats.csv` - Request statistics
- `prefix_stats_history.csv` - Time-series data
- `prefix_failures.csv` - Failed requests
- `prefix_exceptions.csv` - Exception details

## Monitoring During Tests

While running load tests, monitor:

1. **Prometheus/Grafana**: http://localhost:3001
   - Request latency
   - Error rates
   - Resource usage

2. **Jaeger**: http://localhost:16686
   - Trace slow requests
   - Find bottlenecks

3. **Docker Stats**:
   ```bash
   docker stats mas agent knowledge_store postgres redis
   ```

## Interpreting Results

### Good Results
- Consistent response times under load
- Error rate stays near 0%
- Linear scaling of requests/sec

### Warning Signs
- Response times increase with load
- Error rate > 1%
- Requests/sec plateaus early

### Breaking Points
- Response times > 5 seconds
- Error rate > 5%
- Timeouts occurring
