# Performance Benchmark Suite

This directory contains performance benchmark scripts for the Horus system.

## Benchmarks

### MAS API Benchmark (`benchmark_mas.py`)

Benchmarks the Multi-Agent System API (see `src/services/mas` routes):
- `POST /rabbitmq/heartbeat` — RabbitMQ connectivity (baseline)
- `GET /conversations/get-conversations/` — list conversations (auth + `USER_READ`)
- `GET /agents/details/` — list agents (auth + `AGENT_READ`)
- `GET /tasks/stats/queue` — task queue stats (auth + `VIEW_ANALYTICS`)
- `POST /conversations/create-conversation/` — create conversation (auth + `TASK_CREATE`)

Login uses the same OAuth2 form as the web client: `POST /auth/token` with `application/x-www-form-urlencoded` and `grant_type=password`.

```bash
# Install dependencies
pip install httpx

# Run benchmarks (defaults match src/infra/.env: admin / secret)
python benchmark_mas.py --url http://localhost:8000 --iterations 100

# Explicit credentials (or set SUPER_USER_USERNAME / SUPER_USER_PASSWORD in the environment)
python benchmark_mas.py --url http://localhost:8000 --username admin --password secret

# Reuse an existing JWT
python benchmark_mas.py --url http://localhost:8000 --token "<access_token>"

# Export results
python benchmark_mas.py --output my_results.json
```

### RAG Pipeline Benchmark (`benchmark_rag.py`)

Benchmarks the Knowledge Store service on port **8080** (no `/store` path prefix when calling the container directly; see `src/infra/docker-compose.yml`):
- `GET /health`
- `POST /` — add document (`id`, `title`, `content`, `size`)
- `GET /?query=...&n_results=...` — query (200 with hits, or 404 when nothing matches)

```bash
python benchmark_rag.py --url http://localhost:8080 --iterations 50
```

## Baseline Metrics

Expected baseline performance targets:

| Metric | Target | Notes |
|--------|--------|-------|
| Health Check | < 10ms | Baseline network latency |
| Conversation List | < 50ms | Database query |
| Agent List | < 50ms | Database query |
| Task Queue Stats | < 100ms | Aggregation query |
| Knowledge Store Query | < 500ms | Vector search + embedding |
| Document Add | < 1000ms | Embedding generation |

## Output Format

`benchmark_mas.py` exports `base_url`, `timestamp`, and per-benchmark `mean_ms`, `median_ms`, `std_dev_ms`, `min_ms`, `max_ms`, `success_rate`.

`benchmark_rag.py` adds `p95_ms`, `p99_ms`, and `avg_results` for the query benchmark.

## Running in CI

For CI/CD pipelines:

```bash
# Run all benchmarks with default settings
python benchmark_mas.py && python benchmark_rag.py

# Check for performance regressions
# Compare against baseline in benchmark_baseline.json
```
