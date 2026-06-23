# Pipeline benchmark — `rebaseline`

- **Timestamp:** 2026-06-23T09:34:56Z
- **Git commit:** 76b0d94
- **GPU:** NVIDIA GeForce RTX 4070 Laptop GPU (driver 610.62, 8188 MiB)
- **MAS:** http://localhost:8000  ·  **KS:** http://localhost:8080
- **Agent:** `ca6eca16-0c5c-4caa-be8d-8d1be0b75043` · model `Qwen/Qwen3-4B-Instruct-2507` · device `cuda`
- **Token count method:** approx:chars-over-4
- **Server gen params (resolved):** AGENT_MAX_NEW_TOKENS=3072 (src/infra/.env), KNOWLEDGE_STORE_N_RESULTS=8 (agent settings default)

> `decode_s` is the agent's own reported model inference time (reasoning.done.duration_seconds). `ttft_proxy_s` is submit→reasoning.start (routing+retrieval+prefill setup), not true TTFT yet. All times in seconds unless noted.

## Idle (single task, sequential)

Tasks OK: 12/12 · 4 suspected-spiral excluded from aggregates

| metric | median | mean | p95 | min | max |
|---|---|---|---|---|---|
| ttft_proxy_s | 0.401 | 0.409 | 0.438 | 0.392 | 0.438 |
| decode_s | 6.739 | 6.564 | 9.532 | 3.710 | 9.532 |
| decode_tok_s | 20.444 | 20.304 | 21.839 | 17.905 | 21.839 |
| e2e_s | 17.260 | 16.737 | 24.434 | 7.254 | 24.434 |
| output_tokens | 238.500 | 243.750 | 434.000 | 64.000 | 434.000 |

GPU: VRAM peak 7717.0 MiB · util mean 57.8% · power mean 58.7 W

## Concurrency (N tasks fired simultaneously)

| N | ok | wall_s | aggregate_tok/s | e2e median | e2e p95 | VRAM peak MiB |
|---|---|---|---|---|---|---|
| 1 | 1/1 | 133.62 | 1.15 | 133.59 | 133.59 | 7665.0 |
| 2 | 2/2 | 148.25 | 2.81 | 148.22 | 148.22 | 7699.0 |
| 4 | 1/4 | 240.95 | 0.74 | 124.17 | 124.17 | 7684.0 |
| 8 | 0/0 | 0.00 | 0.00 | 0.00 | 0.00 | 7690.0 |

## Contention (generation vs. concurrent KS ingestion)

KS load: 3 workers, 6 docs embedded during the loaded run.

| state | decode_tok/s median | e2e median | VRAM peak MiB | GPU util mean % |
|---|---|---|---|---|
| idle | 0.00 | 0.00 | 7690.0 | 55.7 |
| under load | 0.00 | 0.00 | 7687.0 | 33.2 |

**Decode tok/s drop under load: None%** — this is the headroom the NPU embedder offload (Phase 6) can recover.
