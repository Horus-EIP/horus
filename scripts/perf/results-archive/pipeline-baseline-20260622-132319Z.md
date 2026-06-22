# Pipeline benchmark — `baseline`

- **Timestamp:** 2026-06-22T13:23:19Z
- **Git commit:** e1fd512
- **GPU:** NVIDIA GeForce RTX 4070 Laptop GPU (driver 610.62, 8188 MiB)
- **MAS:** http://localhost:8000  ·  **KS:** http://localhost:8080
- **Agent:** `1f5aa7a4-cf7f-430d-a495-d98804a094bc` · model `Qwen/Qwen3-4B-Instruct-2507` · device `cuda`
- **Token count method:** approx:chars-over-4
- **Server gen params (env / assumed default):** AGENT_MAX_NEW_TOKENS=256 (default, server-side), KNOWLEDGE_STORE_N_RESULTS=8 (default, server-side)

> `decode_s` is the agent's own reported model inference time (reasoning.done.duration_seconds). `ttft_proxy_s` is submit→reasoning.start (routing+retrieval+prefill setup), not true TTFT yet. All times in seconds unless noted.

## Idle (single task, sequential)

Tasks OK: 6/6

| metric | median | mean | p95 | min | max |
|---|---|---|---|---|---|
| ttft_proxy_s | 0.515 | 0.525 | 0.605 | 0.491 | 0.605 |
| decode_s | 8.876 | 29.456 | 128.977 | 4.062 | 128.977 |
| decode_tok_s | 22.709 | 22.446 | 43.426 | 1.388 | 43.426 |
| e2e_s | 20.393 | 37.131 | 134.469 | 8.129 | 134.469 |
| output_tokens | 182.000 | 201.333 | 360.000 | 66.000 | 360.000 |

GPU: VRAM peak 7806.0 MiB · util mean 58.2% · power mean 56.9 W

## Concurrency (N tasks fired simultaneously)

| N | ok | wall_s | aggregate_tok/s | e2e median | e2e p95 | VRAM peak MiB |
|---|---|---|---|---|---|---|
| 2 | 2/2 | 23.75 | 10.57 | 16.68 | 20.51 | 7496.0 |

## Contention (generation vs. concurrent KS ingestion)

KS load: 2 workers, 16 docs embedded during the loaded run.

| state | decode_tok/s median | e2e median | VRAM peak MiB | GPU util mean % |
|---|---|---|---|---|
| idle | 44.09 | 19.54 | 7458.0 | 54.4 |
| under load | 29.14 | 29.67 | 7436.0 | 36.7 |

**Decode tok/s drop under load: 33.9%** — this is the headroom the NPU embedder offload (Phase 6) can recover.
