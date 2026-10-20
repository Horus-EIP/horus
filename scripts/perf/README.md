# Performance Scripts

Everything that pushes the system harder than a regular test — benchmarks, load tests, resilience/chaos tests, and retrieval-quality measurement. Results from prior benchmark runs are in `results-archive/`.

---

## Benchmarks

## Performance Benchmark Suite

This directory contains performance benchmark scripts for the Horus system.

### Benchmarks

#### MAS API Benchmark (`benchmark_mas.py`)

Benchmarks the Multi-Agent System API (see `src/services/mas` routes):
- `POST /rabbitmq/heartbeat` — RabbitMQ connectivity (baseline)
- `GET /conversations/get-conversations/` — list conversations (auth + `USER_READ`)
- `GET /agents/details/` — list agents (auth + `AGENT_READ`)
- `GET /tasks/stats/queue` — task queue stats (auth + `VIEW_ANALYTICS`)
- `POST /conversations/create-conversation/` — create conversation (auth + `TASK_CREATE`)

Login uses the same OAuth2 form as the web client: `POST /auth/token` with `application/x-www-form-urlencoded` and `grant_type=password`.

```bash
## Install dependencies
pip install httpx

## Run benchmarks (defaults match src/infra/.env: admin / secret)
python benchmark_mas.py --url http://localhost:8000 --iterations 100

## Explicit credentials (or set SUPER_USER_USERNAME / SUPER_USER_PASSWORD in the environment)
python benchmark_mas.py --url http://localhost:8000 --username admin --password secret

## Reuse an existing JWT
python benchmark_mas.py --url http://localhost:8000 --token "<access_token>"

## Export results
python benchmark_mas.py --output my_results.json
```

#### RAG Pipeline Benchmark (`benchmark_rag.py`)

Benchmarks the Knowledge Store service on port **8080** (no `/store` path prefix when calling the container directly; see `src/infra/docker-compose.yml`):
- `GET /health`
- `POST /` — add document (`id`, `title`, `content`, `size`)
- `GET /?query=...&n_results=...` — query (200 with hits, or 404 when nothing matches)

```bash
python benchmark_rag.py --url http://localhost:8080 --iterations 50
```

#### End-to-End LLM Pipeline Benchmark (`benchmark-pipeline.py`)

The MAS/RAG benchmarks above exercise CRUD and the knowledge-store HTTP API but
**not** the actual multi-agent LLM pipeline. `benchmark-pipeline.py` drives the
real path — submit a query via `POST /tasks/new_task/` (`mode=specific_agent`,
so it always lands on the heavy Qwen3-4B worker, not the 1.5B router's
direct-answer short-circuit) and listen on the chat WebSocket
`/chat/{conversation_id}/` for the agent's `task_step` / `task_complete` events.

Because the agent brackets generation with `reasoning.start` / `reasoning.done`
(and `reasoning.done` reports `duration_seconds`), it derives a **clean decode
tok/s** without any code changes or streaming. Fixtures live in `bench_assets/`
(`corpus.jsonl` ingested into the KS, `prompts.jsonl` fixed query set).

```bash
pip install httpx websockets          # tiktoken optional, for better token counts

# quick sanity check against a live stack (1 task, verbose event dump)
python benchmark-pipeline.py --scenario smoke

# full baseline (idle + concurrency + contention), writes results-archive/pipeline-*.{json,md}
python benchmark-pipeline.py --scenario all --label baseline
```

Scenarios: `idle` (sequential single-task), `concurrency` (N tasks at once →
aggregate tok/s + p50/p95), `contention` (generation tok/s with vs. without a
concurrent knowledge-store ingestion load — the idle→loaded decode drop is the
ceiling the NPU embedder offload can recover). Captured per task: `submit_http_ms`,
`first_step_s`, `ttft_proxy_s` (submit→reasoning.start), `decode_s` (reported
inference time), `decode_tok_s`, `e2e_s`, plus nvidia-smi VRAM/util/power per
scenario. Both LLMs decode greedily (`do_sample=False`) so runs are deterministic.

> **Tuning note:** at high `AGENT_MAX_NEW_TOKENS` and the current GPU-memory cap
> (`AGENT_GPU_MEMORY_CAP`, which offloads the 4B to CPU), a single generation can
> take minutes. Trim with `--repeats`, `--concurrency 1,2`, `--gen-count`, and a
> generous `--event-timeout` for a feasible baseline.

#### Prompt tokens per call (`prompt-tokens.py`)

The agent and MAS record the prompt tokens of every LLM call in `agent_llm_prompt_tokens{call,source}` and `mas_llm_prompt_tokens{call,source}` (see "Prompt tokens" in the agent README and "LLM prompts" in the MAS README). `prompt-tokens.py` reads both `/metrics` endpoints (or saved files), prints the number of calls, the average prompt tokens and the calls over budget for each `call`, and exits with 1 when an average is over its budget. It needs only the standard library.

```bash
# before the run: save the counters, so only the run's calls are averaged
python prompt-tokens.py --save results-archive/prompt-tokens-before

# after the run
python prompt-tokens.py --since results-archive/prompt-tokens-before --json results-archive/prompt-tokens.json

# other hosts or budgets
python prompt-tokens.py --agent http://localhost:8001/metrics/ --mas http://localhost:8000/metrics --agent-budget 3000
```

Exit codes: 0 every average is within its budget, 1 one is over, 2 no LLM call was recorded.

### Baseline Metrics

Expected baseline performance targets:

| Metric | Target | Notes |
|--------|--------|-------|
| Health Check | < 10ms | Baseline network latency |
| Conversation List | < 50ms | Database query |
| Agent List | < 50ms | Database query |
| Task Queue Stats | < 100ms | Aggregation query |
| Knowledge Store Query | < 500ms | Vector search + embedding |
| Document Add | < 1000ms | Embedding generation |

### Output Format

`benchmark_mas.py` exports `base_url`, `timestamp`, and per-benchmark `mean_ms`, `median_ms`, `std_dev_ms`, `min_ms`, `max_ms`, `success_rate`.

`benchmark_rag.py` adds `p95_ms`, `p99_ms`, and `avg_results` for the query benchmark.

### Running in CI

For CI/CD pipelines:

```bash
## Run all benchmarks with default settings
python benchmark_mas.py && python benchmark_rag.py

## Check for performance regressions
## Compare against baseline in benchmark_baseline.json
```

---

## Load Tests

## Load Testing Suite

This directory contains Locust-based load tests for the Horus system.

### Prerequisites

```bash
pip install locust
```

### Running Load Tests

#### MAS API Load Test

```bash
## With web UI (recommended for exploratory testing)
locust -f locustfile.py --host=http://localhost:8000

## Open http://localhost:8089 to configure and start the test

## Headless mode (for CI/CD)
locust -f locustfile.py --host=http://localhost:8000 \
    --users 100 \
    --spawn-rate 10 \
    --run-time 5m \
    --headless \
    --csv=results/mas_load
```

#### Knowledge Store Load Test

```bash
locust -f knowledge_store_load.py --host=http://localhost:8080 \
    --users 50 \
    --spawn-rate 5 \
    --run-time 5m \
    --headless
```

### User Classes

#### MAS Load Test (`locustfile.py`)

| User Type | Description | Weight |
|-----------|-------------|--------|
| `MASUser` | Typical end user | 60% |
| `AgentUser` | Simulated agent | 30% |
| `AdminUser` | Admin operations | 10% |

#### Knowledge Store Load Test (`knowledge_store_load.py`)

| User Type | Description | Use Case |
|-----------|-------------|----------|
| `KnowledgeStoreUser` | Mixed operations | General load testing |
| `QueryOnlyUser` | Query-only | Query performance |
| `BurstUser` | Rapid-fire queries | Spike testing |

### Test Scenarios

#### Scenario 1: Normal Load
```bash
locust -f locustfile.py --host=http://localhost:8000 \
    --users 50 --spawn-rate 5 --run-time 10m
```

#### Scenario 2: Peak Load
```bash
locust -f locustfile.py --host=http://localhost:8000 \
    --users 200 --spawn-rate 20 --run-time 5m
```

#### Scenario 3: Stress Test
```bash
locust -f locustfile.py --host=http://localhost:8000 \
    --users 500 --spawn-rate 50 --run-time 15m
```

#### Scenario 4: Spike Test
```bash
## Start with low load
locust -f locustfile.py --host=http://localhost:8000 \
    --users 10 --spawn-rate 1 --run-time 2m

## Then spike to high load
locust -f locustfile.py --host=http://localhost:8000 \
    --users 200 --spawn-rate 100 --run-time 2m
```

### Performance Targets

| Metric | Target | Critical |
|--------|--------|----------|
| Avg Response Time | < 200ms | < 500ms |
| 95th Percentile | < 500ms | < 1000ms |
| Error Rate | < 0.1% | < 1% |
| Requests/sec | > 100 | > 50 |

### Output Files

When using `--csv=results/prefix`, Locust generates:
- `prefix_stats.csv` - Request statistics
- `prefix_stats_history.csv` - Time-series data
- `prefix_failures.csv` - Failed requests
- `prefix_exceptions.csv` - Exception details

### Monitoring During Tests

While running load tests, monitor:

1. **Metrics** (Prometheus): https://localhost:3000/admin/metrics
   - Task Queue Depth
   - Task Errors Rate
   - Active Agents

2. **Logs** (Loki): https://localhost:3000/admin/logs
   - Request errors
   - Service log streams

3. **Traces** (Tempo): https://localhost:3000/admin/traces
   - Trace slow requests
   - Find bottlenecks

   > Observability (logs/metrics/traces) is now viewed live in the web client's
   > `/admin` pages (admin role required). Prometheus, Loki, and Tempo still run
   > as backends inside the Docker network but are no longer exposed via Grafana.

4. **Docker Stats**:
   ```bash
   docker stats mas agent knowledge_store postgres redis
   ```

### Interpreting Results

#### Good Results
- Consistent response times under load
- Error rate stays near 0%
- Linear scaling of requests/sec

#### Warning Signs
- Response times increase with load
- Error rate > 1%
- Requests/sec plateaus early

#### Breaking Points
- Response times > 5 seconds
- Error rate > 5%
- Timeouts occurring

---

## Resilience Tests

## Resilience Tests

End-to-end tests to verify system behavior under failure conditions.

### Quick Start

```bash
## Install dependencies
pip install httpx

## Run all tests
python test_resilience.py --url http://localhost:8000 --ks-url http://localhost:8080
```

### Tests Included

#### 1. Data Persistence
Verifies that data created in the system persists correctly and can be retrieved.

#### 2. Conversation Recovery
Tests that conversation data survives and can be queried after system operations.

#### 3. Agent Re-registration
Verifies agents are tracked correctly and status is maintained.

#### 4. Knowledge Store Recovery
Tests that the Knowledge Store is accessible and can handle queries.

#### 5. Graceful Degradation
Verifies the system returns appropriate error codes (404, 401) for error conditions.

#### 6. Concurrent Requests
Tests system behavior under concurrent load (10 simultaneous requests).

### Manual Resilience Testing

#### Test MAS Restart

```bash
## 1. Create some data
curl -X POST http://localhost:8000/conversations/create \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"name": "Test Conversation"}'

## 2. Restart MAS
docker restart mas

## 3. Wait for MAS to come back
sleep 30

## 4. Verify data persists
curl http://localhost:8000/conversations/all \
  -H "Authorization: Bearer <token>"
```

#### Test RabbitMQ Restart

```bash
## 1. Restart RabbitMQ
docker restart rabbitmq

## 2. Wait for recovery
sleep 30

## 3. Verify MAS reconnects
curl -X POST http://localhost:8000/rabbitmq/heartbeat

## 4. Verify agents re-register
curl http://localhost:8000/agents/
```

#### Test PostgreSQL Restart

```bash
## 1. Restart PostgreSQL
docker restart postgres

## 2. Wait for recovery
sleep 20

## 3. Verify MAS reconnects
curl http://localhost:8000/conversations/all \
  -H "Authorization: Bearer <token>"
```

#### Test Agent Failure

```bash
## 1. Stop agent
docker stop agent

## 2. Verify MAS handles absence
curl http://localhost:8000/agents/

## 3. Restart agent
docker start agent

## 4. Wait for re-registration
sleep 30

## 5. Verify agent is back
curl http://localhost:8000/agents/
```

#### Test Knowledge Store Unavailability

```bash
## 1. Stop knowledge store
docker stop knowledge_store

## 2. Verify system handles gracefully
## (Tasks should fail with appropriate error)

## 3. Restart knowledge store
docker start knowledge_store

## 4. Verify recovery
curl http://localhost:8080/health
```

### Expected Behavior

| Scenario | Expected Behavior |
|----------|-------------------|
| MAS restart | Data persists, connections re-establish |
| RabbitMQ restart | MAS reconnects, agents re-register |
| PostgreSQL restart | MAS reconnects, data preserved |
| Agent failure | Tasks fail gracefully, no data loss |
| Knowledge Store down | Queries fail with error, system stable |

### Success Criteria

- ✅ All data persists across restarts
- ✅ Services reconnect automatically
- ✅ No data corruption
- ✅ Graceful error handling
- ✅ Concurrent requests handled correctly
