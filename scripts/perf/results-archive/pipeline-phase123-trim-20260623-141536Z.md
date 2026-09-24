# Pipeline benchmark — `phase123-trim`

- **Timestamp:** 2026-06-23T14:15:36Z
- **Git commit:** 76b0d94
- **GPU:** NVIDIA GeForce RTX 4070 Laptop GPU (driver 610.62, 8188 MiB)
- **MAS:** http://localhost:8000  ·  **KS:** http://localhost:8080
- **Agent:** `fe05b209-dd34-4132-af09-33de164ced34` · model `Qwen/Qwen3-4B-Instruct-2507` · device `cuda`
- **Token count method:** approx:chars-over-4
- **Server gen params (resolved):** AGENT_MAX_NEW_TOKENS=3072 (src/infra/.env), KNOWLEDGE_STORE_N_RESULTS=4 (src/infra/.env)

> `decode_s` is the agent's own reported model inference time (reasoning.done.duration_seconds). `ttft_proxy_s` is submit→reasoning.start (routing+retrieval+prefill setup), not true TTFT yet. All times in seconds unless noted.

## Idle (single task, sequential)

Tasks OK: 6/6 · 2 suspected-spiral excluded from aggregates

| metric | median | mean | p95 | min | max |
|---|---|---|---|---|---|
| ttft_proxy_s | 0.508 | 0.521 | 0.613 | 0.457 | 0.613 |
| decode_s | 9.611 | 8.941 | 11.303 | 5.240 | 11.303 |
| decode_tok_s | 17.416 | 16.568 | 17.892 | 13.550 | 17.892 |
| e2e_s | 20.616 | 19.811 | 27.790 | 10.223 | 27.790 |
| output_tokens | 211.000 | 215.000 | 387.000 | 51.000 | 387.000 |

GPU: VRAM peak 7633.0 MiB · util mean 41.5% · power mean 47.5 W
