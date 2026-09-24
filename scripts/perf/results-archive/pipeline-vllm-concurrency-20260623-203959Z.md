# Pipeline benchmark — `vllm-concurrency`

- **Timestamp:** 2026-06-23T20:39:59Z
- **Git commit:** 2415eea
- **GPU:** NVIDIA GeForce RTX 4070 Laptop GPU (driver 610.62, 8188 MiB)
- **MAS:** http://localhost:8000  ·  **KS:** http://localhost:8080
- **Agent:** `16b09ee8-7760-498e-ab3e-0a8f8ad7e4ce` · model `Qwen/Qwen3-4B-Instruct-2507` · device `cuda`
- **Token count method:** approx:chars-over-4
- **Server gen params (resolved):** AGENT_MAX_NEW_TOKENS=3072 (src/infra/.env), KNOWLEDGE_STORE_N_RESULTS=4 (src/infra/.env)

> `decode_s` is the agent's own reported model inference time (reasoning.done.duration_seconds). `ttft_proxy_s` is submit→reasoning.start (routing+retrieval+prefill setup), not true TTFT yet. All times in seconds unless noted.

## Concurrency (N tasks fired simultaneously)

| N | ok | wall_s | aggregate_tok/s | e2e median | e2e p95 | VRAM peak MiB |
|---|---|---|---|---|---|---|
| 1 | 1/1 | 3.94 | 19.05 | 0.89 | 0.89 | 2522.0 |
| 2 | 2/2 | 4.55 | 32.96 | 1.15 | 1.20 | 2544.0 |
| 4 | 4/4 | 4.91 | 61.05 | 1.31 | 1.36 | 2510.0 |
| 8 | 8/8 | 8.71 | 68.85 | 4.17 | 4.71 | 2509.0 |
