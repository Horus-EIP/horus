# Pipeline benchmark — `vllm-aggfix`

- **Timestamp:** 2026-06-23T18:11:16Z
- **Git commit:** 76b0d94
- **GPU:** NVIDIA GeForce RTX 4070 Laptop GPU (driver 610.62, 8188 MiB)
- **MAS:** http://localhost:8000  ·  **KS:** http://localhost:8080
- **Agent:** `9f79a0c7-27c6-4868-9ed9-dfc9341b44d6` · model `Qwen/Qwen3-4B-Instruct-2507` · device `cuda`
- **Token count method:** approx:chars-over-4
- **Server gen params (resolved):** AGENT_MAX_NEW_TOKENS=3072 (src/infra/.env), KNOWLEDGE_STORE_N_RESULTS=4 (src/infra/.env)

> `decode_s` is the agent's own reported model inference time (reasoning.done.duration_seconds). `ttft_proxy_s` is submit→reasoning.start (routing+retrieval+prefill setup), not true TTFT yet. All times in seconds unless noted.

## Idle (single task, sequential)

Tasks OK: 6/6

| metric | median | mean | p95 | min | max |
|---|---|---|---|---|---|
| ttft_proxy_s | 0.543 | 0.576 | 0.737 | 0.472 | 0.737 |
| decode_s | 3.635 | 4.123 | 6.862 | 2.649 | 6.862 |
| decode_tok_s | 33.521 | 33.273 | 35.577 | 31.002 | 35.577 |
| e2e_s | 4.373 | 4.756 | 7.411 | 3.244 | 7.411 |
| output_tokens | 108.000 | 137.333 | 318.000 | 76.000 | 318.000 |

GPU: VRAM peak 7598.0 MiB · util mean 77.7% · power mean 44.2 W
