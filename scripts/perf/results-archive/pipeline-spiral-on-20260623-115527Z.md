# Pipeline benchmark — `spiral-on`

- **Timestamp:** 2026-06-23T11:55:27Z
- **Git commit:** 76b0d94
- **GPU:** NVIDIA GeForce RTX 4070 Laptop GPU (driver 610.62, 8188 MiB)
- **MAS:** http://localhost:8000  ·  **KS:** http://localhost:8080
- **Agent:** `d858dd50-9c5e-4fc2-9f72-a61378411c28` · model `Qwen/Qwen3-4B-Instruct-2507` · device `cuda`
- **Token count method:** approx:chars-over-4
- **Server gen params (resolved):** AGENT_MAX_NEW_TOKENS=3072 (src/infra/.env), KNOWLEDGE_STORE_N_RESULTS=8 (agent settings default)

> `decode_s` is the agent's own reported model inference time (reasoning.done.duration_seconds). `ttft_proxy_s` is submit→reasoning.start (routing+retrieval+prefill setup), not true TTFT yet. All times in seconds unless noted.

## Idle (single task, sequential)

Tasks OK: 6/6 · 4 suspected-spiral excluded from aggregates

| metric | median | mean | p95 | min | max |
|---|---|---|---|---|---|
| ttft_proxy_s | 12.220 | 12.220 | 20.930 | 3.510 | 20.930 |
| decode_s | 6.979 | 6.979 | 12.838 | 1.120 | 12.838 |
| decode_tok_s | 14.746 | 14.746 | 20.564 | 8.929 | 20.564 |
| e2e_s | 23.904 | 23.904 | 24.605 | 23.204 | 24.605 |
| output_tokens | 126.000 | 126.000 | 170.000 | 82.000 | 170.000 |

GPU: VRAM peak 7723.0 MiB · util mean 61.1% · power mean 54.5 W
