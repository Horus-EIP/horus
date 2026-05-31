# Performance — KPIs, Tests, and Optimization

EIP Tech 4 — Objective D. This page declares the project's performance indicators with explicit targets, links the benchmark / load / resilience / quality scripts that measure them, and records before/after results when we apply an optimization.

---

## Chosen KPIs

We track **three** indicators (per the guide's recommendation of 2–3). Each has a numeric target, a measurement script, and a Grafana panel.

| # | KPI | Target | What it answers | Measured by | Dashboard panel |
|---|-----|--------|-----------------|-------------|-----------------|
| **K1** | **End-to-end chat latency (p95)** | **< 2 000 ms** under 20 concurrent users | "How long does a user wait between sending a message and seeing the first agent token?" | [`scripts/perf/load-locust.py`](../../scripts/perf/load-locust.py) + Prometheus histogram `mas_task_processing_time_seconds_bucket` | Grafana → MAS Overview → "Task processing time (p95)" |
| **K2** | **RAG retrieval quality (keyword-match precision @ top-5)** | **≥ 0.80** on the standard query set in [`scripts/perf/quality-benchmark.py`](../../scripts/perf/quality-benchmark.py) | "When the user asks about topic X, do the retrieved chunks actually mention X?" | [`scripts/perf/quality-benchmark.py`](../../scripts/perf/quality-benchmark.py) (new) + [`retrieval-quality.py`](../../scripts/perf/retrieval-quality.py) | N/A — JSON output committed to `scripts/perf/results-archive/` |
| **K3** | **Read-endpoint throughput (req/s)** | **≥ 200 req/s** sustained on `/conversations` + `/agents/details` with cache warm | "Does the API survive a dashboard polling burst?" | [`scripts/perf/benchmark-mas.py`](../../scripts/perf/benchmark-mas.py) with `--label baseline` vs `--label cached` | Grafana → MAS Overview → "HTTP requests/sec" |

Why these three: K1 = user-perceived performance, K2 = product-perceived quality (latency without quality is meaningless for RAG), K3 = system-perceived headroom under realistic dashboard polling.

---

## Tracking table — current values

| KPI | Target | Last measured | Result | Pass? | Run command |
|-----|--------|---------------|--------|-------|-------------|
| K1 — chat p95 | < 2 000 ms | `[ TO RUN ]` | — | — | `cd scripts/perf && locust -f load-locust.py --headless -u 20 -r 5 -t 2m` |
| K2 — retrieval P@5 | ≥ 0.80 | `[ TO RUN ]` | — | — | `python scripts/perf/quality-benchmark.py --label baseline` |
| K3 — read throughput | ≥ 200 req/s | `[ TO RUN ]` | — | — | `python scripts/perf/benchmark-mas.py --label baseline` then re-run with `--label cached` |

**To use this file as a real jury deliverable:** run each command, copy the resulting JSON into `scripts/perf/results-archive/`, and update the "Last measured" / "Result" / "Pass?" columns above with a link to the result file and the commit SHA.

---

## Optimization log — before/after

This section records every optimization we shipped, with measured impact. Empty entries are placeholders to be filled as you run.

### Opt-1 — Redis cache on read-heavy endpoints

- **Hypothesis:** `/conversations` and `/agents/details` are polled by the web client every few seconds; caching them in Redis for 10 s should cut DB load and lift K3 above target.
- **Change:** add a `@cache_aside(ttl=10)` decorator on the two route handlers (`src/services/mas/conversations/routes.py`, `src/services/mas/agents/routes.py`). Behind feature flag `MAS_READ_CACHE_ENABLED` (default off in tests, on in compose).
- **Measurement protocol:**
  1. `MAS_READ_CACHE_ENABLED=0 docker compose up -d --force-recreate mas`
  2. `python scripts/perf/benchmark-mas.py --label baseline-no-cache`
  3. `MAS_READ_CACHE_ENABLED=1 docker compose up -d --force-recreate mas`
  4. `python scripts/perf/benchmark-mas.py --label optimized-cache`
  5. Take Grafana screenshot of MAS Overview during step 4 → `greenlight/grafana-screenshots/opt1-cache-on.png`
- **Result:** `[ TO MEASURE ]`
- **Trade-off (per guide):** quality + 0 (read-only data, stale by ≤ 10 s) · performance + measured · cost: trivial (single Redis already running) · time: ~half a day.

### Opt-2 — `[ next optimization slot, e.g. embedding batch size in Knowledge Store ]`

`[ FILL when measured ]`

### Opt-3 — `[ next optimization slot ]`

`[ FILL when measured ]`

---

## Test types we run

| Test type | Script | What it stresses | When we run it |
|-----------|--------|------------------|----------------|
| Latency benchmark (MAS REST) | [`benchmark-mas.py`](../../scripts/perf/benchmark-mas.py) | Per-endpoint mean/median/p95 across N iterations | Before each release |
| RAG benchmark | [`benchmark-rag.py`](../../scripts/perf/benchmark-rag.py) | End-to-end RAG cycle (retrieve + decide) | Before each release |
| Load test (concurrent users) | [`load-locust.py`](../../scripts/perf/load-locust.py) | Sustained traffic, scaling user count | Before greenlight, before final defence |
| Knowledge Store load | [`load-knowledge-store.py`](../../scripts/perf/load-knowledge-store.py) | Upload + query bursts | Before greenlight |
| Resilience / chaos | [`resilience.py`](../../scripts/perf/resilience.py) | RabbitMQ death, ChromaDB restart, Postgres failover | Once per sprint |
| Retrieval quality | [`retrieval-quality.py`](../../scripts/perf/retrieval-quality.py) | Recall on a curated query set | Whenever the embedding model or chunker changes |
| Quality benchmark (keyword + output assertions) | [`quality-benchmark.py`](../../scripts/perf/quality-benchmark.py) | Keyword-match precision, answer-contains assertions | Each release + after any RAG pipeline change |

---

## Result artefacts

Raw benchmark output (JSON) is committed to [`scripts/perf/results-archive/`](../../scripts/perf/results-archive/). Each file is named `<benchmark>-<label>-<YYYYMMDD>.json` so before/after pairs are obvious at a glance.

Dashboard screenshots taken during load tests live under [`greenlight/grafana-screenshots/`](../../greenlight/grafana-screenshots/). Use [`scripts/perf/capture-dashboards.sh`](../../scripts/perf/capture-dashboards.sh) to capture them automatically.

---

## Review

- **Owner:** Loup Marquez
- **Last full benchmark run:** `[ TO FILL ]`
- **Next planned run:** before EIP greenlight
- **Linked docs:** [operations.md](../operations.md) (monitoring section) · [architecture.md](../architecture.md) (service deep dives)
