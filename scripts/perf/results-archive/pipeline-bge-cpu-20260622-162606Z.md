# Pipeline benchmark — `bge-cpu`

- **Timestamp:** 2026-06-22T16:26:06Z
- **Git commit:** 76b0d94
- **GPU:** NVIDIA GeForce RTX 4070 Laptop GPU (driver 610.62, 8188 MiB)
- **MAS:** http://localhost:8000  ·  **KS:** http://localhost:8080
- **Agent:** `34cdd167-02ba-4a58-b73d-237464e644c9` · model `Qwen/Qwen3-4B-Instruct-2507` · device `cuda`
- **Token count method:** approx:chars-over-4
- **Server gen params (env / assumed default):** AGENT_MAX_NEW_TOKENS=256 (default, server-side), KNOWLEDGE_STORE_N_RESULTS=8 (default, server-side)

> `decode_s` is the agent's own reported model inference time (reasoning.done.duration_seconds). `ttft_proxy_s` is submit→reasoning.start (routing+retrieval+prefill setup), not true TTFT yet. All times in seconds unless noted.

## Idle (single task, sequential)

Tasks OK: 6/6

| metric | median | mean | p95 | min | max |
|---|---|---|---|---|---|
| ttft_proxy_s | 0.439 | 0.442 | 0.472 | 0.425 | 0.472 |
| decode_s | 7.938 | 44.030 | 123.252 | 4.104 | 123.252 |
| decode_tok_s | 22.358 | 24.302 | 51.107 | 1.249 | 51.107 |
| e2e_s | 20.507 | 52.494 | 128.634 | 7.543 | 128.634 |
| output_tokens | 197.000 | 218.000 | 434.000 | 64.000 | 434.000 |

GPU: VRAM peak 7683.0 MiB · util mean 53.3% · power mean 58.7 W

## Concurrency (N tasks fired simultaneously)

| N | ok | wall_s | aggregate_tok/s | e2e median | e2e p95 | VRAM peak MiB |
|---|---|---|---|---|---|---|
| 2 | 2/2 | 150.07 | 2.77 | 83.58 | 150.05 | 7636.0 |

## Contention (generation vs. concurrent KS ingestion)

KS load: 2 workers, 16 docs embedded during the loaded run.

| state | decode_tok/s median | e2e median | VRAM peak MiB | GPU util mean % |
|---|---|---|---|---|
| idle | 47.63 | 24.04 | 7604.0 | 48.4 |
| under load | 23.70 | 35.55 | 7299.0 | 34.1 |

**Decode tok/s drop under load: 50.2%** — this is the headroom the NPU embedder offload (Phase 6) can recover.
