# Pipeline benchmark — `rebaseline-concurrency`

- **Timestamp:** 2026-06-23T10:47:47Z
- **Git commit:** 76b0d94
- **GPU:** NVIDIA GeForce RTX 4070 Laptop GPU (driver 610.62, 8188 MiB)
- **MAS:** http://localhost:8000  ·  **KS:** http://localhost:8080
- **Agent:** `ca6eca16-0c5c-4caa-be8d-8d1be0b75043` · model `Qwen/Qwen3-4B-Instruct-2507` · device `cuda`
- **Token count method:** approx:chars-over-4
- **Server gen params (resolved):** AGENT_MAX_NEW_TOKENS=3072 (src/infra/.env), KNOWLEDGE_STORE_N_RESULTS=8 (agent settings default)

> `decode_s` is the agent's own reported model inference time (reasoning.done.duration_seconds). `ttft_proxy_s` is submit→reasoning.start (routing+retrieval+prefill setup), not true TTFT yet. All times in seconds unless noted.

## Concurrency (N tasks fired simultaneously)

| N | ok | wall_s | aggregate_tok/s | e2e median | e2e p95 | VRAM peak MiB |
|---|---|---|---|---|---|---|
| 1 | 1/1 | 8.97 | 7.36 | 8.92 | 8.92 | 7592.0 |
| 2 | 2/2 | 23.11 | 9.09 | 15.81 | 22.77 | 7615.0 |
| 4 | 4/4 | 188.69 | 2.38 | 22.53 | 29.34 | 7696.0 |
| 8 | 6/8 | 243.26 | 3.89 | 206.41 | 238.87 | 7689.0 |
