# Performance — KPIs, Tests, and Optimization

EIP Tech 4 — Objective D. This page declares the project's performance indicators with explicit targets, links the benchmark / load / resilience / quality scripts that measure them, and records before/after results when we apply an optimization.

---

## Chosen KPIs

We track **three** indicators (per the guide's recommendation of 2–3). Each has a numeric target, a measurement script, and, where Prometheus has the data, a panel or query on the in-app admin metrics page (`/admin/metrics`, which replaced the Grafana dashboard).

| # | KPI | Target | What it answers | Measured by | Dashboard panel |
|---|-----|--------|-----------------|-------------|-----------------|
| **K1** | **End-to-end chat latency (p95)** | **< 2 000 ms** under 20 concurrent users | "How long does a user wait between sending a message and seeing the first agent token?" | [`scripts/perf/load-locust.py`](../../scripts/perf/load-locust.py) + Prometheus histogram `mas_task_processing_seconds` (task creation to completed result, buckets up to 1 800 s) | Admin → Metrics (`/admin/metrics`) → "MAS Task Processing Time" (p50 and p95 from `mas_task_processing_seconds_bucket`) |
| **K2** | **RAG retrieval quality (keyword-match precision @ top-5)** | **≥ 0.80** on the standard query set in [`scripts/perf/quality-benchmark.py`](../../scripts/perf/quality-benchmark.py) | "When the user asks about topic X, do the retrieved chunks actually mention X?" | [`scripts/perf/quality-benchmark.py`](../../scripts/perf/quality-benchmark.py) (new) + [`retrieval-quality.py`](../../scripts/perf/retrieval-quality.py) | N/A — JSON output committed to `scripts/perf/results-archive/` |
| **K3** | **Read-endpoint throughput (req/s)** | **≥ 200 req/s** sustained on `/conversations` + `/agents/details` with cache warm | "Does the API survive a dashboard polling burst?" | [`scripts/perf/throughput-locust.py`](../../scripts/perf/throughput-locust.py) (zero think-time, pre-injected token) + [`benchmark-mas.py`](../../scripts/perf/benchmark-mas.py) for the cache A/B | Admin → Metrics (`/admin/metrics`) → Custom query `sum(rate(http_requests_total{job="mas-api"}[1m]))` |

Why these three: K1 = user-perceived performance, K2 = product-perceived quality (latency without quality is meaningless for RAG), K3 = system-perceived headroom under realistic dashboard polling.

---

## Tracking table — current values

| KPI | Target | Last measured | Result | Pass? | Run command |
|-----|--------|---------------|--------|-------|-------------|
| K1 — chat p95 | < 2 000 ms | 2026-05-31 | **50 ms** p95 (0 % errors, 818 req, 20 concurrent users) → `locust-baseline_stats.csv` | ✅ | `cd scripts/perf && python3 -m locust -f load-locust.py --headless -u 20 -r 5 -t 2m --host http://localhost:8000` |
| K2 — retrieval P@5 | ≥ 0.80 | 2026-05-31 | **0.79** keyword-match precision @5 over 8 canonical queries → `quality-baseline-20260531.json` | ⚠️ marginal (0.01 under target; corpus = `demo_assets/`) | `python3 scripts/perf/quality-benchmark.py --label baseline --no-chat` |
| K3 — read throughput | ≥ 200 req/s | 2026-05-31 | **81 req/s** sustained on `/conversations` + `/agents/details` (30 users, zero think-time, 0 % errors, p95 640 ms) → `throughput-baseline_stats.csv` | ❌ under target — endpoints saturate **without** the read-cache; this is exactly the gap **Opt-1** closes | `MAS_TOKEN=… python3 -m locust -f scripts/perf/throughput-locust.py --headless -u 30 -r 10 -t 30s --host http://localhost:8000` |

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
- **Result (2026-05-31):** no measurable delta — the `MAS_READ_CACHE_ENABLED` flag is accepted by the compose restart but the Redis read-cache path is **not yet active in code**, so baseline ≈ optimized within run-to-run noise (mean ms, baseline → optimized): Conversation List 8.4 → 9.4 · Agent List 7.7 → 7.8 · Task Queue Stats 7.5 → 9.3 · Conversation Create 11.3 → 11.8 · Health 15.5 → 15.3. Both phases 100 % success over 200 iterations. The A/B harness is wired and ready to demonstrate the speed-up the moment the `@cache_aside` decorator lands. Raw JSONs: `scripts/perf/results-archive/cache-baseline-20260531-163910Z.json` and `cache-optimized-20260531-163910Z.json`.
- **Trade-off (per guide):** quality + 0 (read-only data, stale by ≤ 10 s) · performance + measured · cost: trivial (single Redis already running) · time: ~half a day.

### Opt-2 — `[ next optimization slot, e.g. embedding batch size in Knowledge Store ]`

`[ FILL when measured ]`

### Opt-3 — `[ next optimization slot ]`

`[ FILL when measured ]`

---

## CPU-only machines (dev plan B-91)

The CPU path is measured with the 100-question test set and llama-bench on the reference machine `cpu16` (16 GB of RAM, CPU only, AVX2). Results go to [`benchmarks/`](../../benchmarks/README.md); [ADR-006](../adr/ADR-006-low-ram-machines.md) uses them to decide what happens under 16 GB.

| Measurement | Date | Result | File |
|---|---|---|---|
| Old CPU profile (Qwen2.5-1.5B router in MAS, Qwen3-4B in bf16 in the agent, both with Transformers), one grounded question, 12-core laptop with 64 GB of RAM | 2026-09-01 | **14 min 14 s**, wrong answer (the anti-spiral guard replaced it). Retrieval ranked the right document first. | [`cpu-transformers-2026-09-01.json`](../../benchmarks/cpu-transformers-2026-09-01.json) |
| llama-bench, Qwen3-4B Q4_K_M and Q5_K_M, build b11382, `cpu16` | not run yet | | `benchmarks/cpu16-<date>.json` |
| 100 questions, `cpu-standard` on llama-server, `cpu16` | not run yet | | `benchmarks/eval-cpu16-standard-<date>.json` |
| 100 questions, the 4B with a 4,096 context and a q8_0 KV cache (ADR-006 option B), `cpu16` | not run yet | | `benchmarks/eval-cpu16-lean-<date>.json` |

```bash
python scripts/benchmarks/run-llama-bench.py --models-dir <folder> --fetch
python scripts/eval/run-eval.py --label eval-cpu16-standard --reference cpu16 --sample-resources
python scripts/benchmarks/compare-benchmarks.py benchmarks/cpu-transformers-2026-09-01.json benchmarks/eval-cpu16-standard-<date>.json
```

The comparison prints the dev plan's §10 table (tokens per second, time to first token, total time, routing time and method, peak RAM and swap, answer and source correctness) in Markdown, ready for a pull request.

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
| Test set evaluation (100 questions) | [`run-eval.py`](../../scripts/eval/run-eval.py) | Time to first token, total time, routing time and method, peak RAM and swap, answer and source correctness | Before and after every dev plan task of phases 1 to 8 |
| Model speed | [`run-llama-bench.py`](../../scripts/benchmarks/run-llama-bench.py) | llama-bench prompt processing and generation, KV cache types, thread counts | When the llama.cpp build, the model or the reference machine changes |

---

## Result artefacts

Raw benchmark output (JSON) is committed to [`scripts/perf/results-archive/`](../../scripts/perf/results-archive/). Each file is named `<benchmark>-<label>-<YYYYMMDD>.json` so before/after pairs are obvious at a glance.

Dashboard screenshots taken during load tests live under [`greenlight/grafana-screenshots/`](../../greenlight/grafana-screenshots/). Use [`scripts/perf/capture-dashboards.sh`](../../scripts/perf/capture-dashboards.sh) to capture them automatically.

---

## Review

- **Owner:** Loup Marquez
- **Last full benchmark run:** 2026-05-31 (K1 load test, K2 RAG quality, Opt-1 cache A/B; stack via `src/infra/docker compose`)
- **Next planned run:** before EIP greenlight
- **Linked docs:** [operations.md](../operations.md) (monitoring section) · [architecture.md](../architecture.md) (service deep dives)
