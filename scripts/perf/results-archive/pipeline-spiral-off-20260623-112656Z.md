# Pipeline benchmark — `spiral-off`

- **Timestamp:** 2026-06-23T11:26:56Z
- **Git commit:** 76b0d94
- **GPU:** NVIDIA GeForce RTX 4070 Laptop GPU (driver 610.62, 8188 MiB)
- **MAS:** http://localhost:8000  ·  **KS:** http://localhost:8080
- **Agent:** `ca6eca16-0c5c-4caa-be8d-8d1be0b75043` · model `Qwen/Qwen3-4B-Instruct-2507` · device `cuda`
- **Token count method:** approx:chars-over-4
- **Server gen params (resolved):** AGENT_MAX_NEW_TOKENS=3072 (src/infra/.env), KNOWLEDGE_STORE_N_RESULTS=8 (agent settings default)

> `decode_s` is the agent's own reported model inference time (reasoning.done.duration_seconds). `ttft_proxy_s` is submit→reasoning.start (routing+retrieval+prefill setup), not true TTFT yet. All times in seconds unless noted.

## Idle (single task, sequential)

Tasks OK: 6/6 · 4 suspected-spiral excluded from aggregates

| metric | median | mean | p95 | min | max |
|---|---|---|---|---|---|
| ttft_proxy_s | 17.227 | 17.227 | 30.732 | 3.721 | 30.732 |
| decode_s | 7.719 | 7.719 | 14.210 | 1.228 | 14.210 |
| decode_tok_s | 13.361 | 13.361 | 18.578 | 8.143 | 18.578 |
| e2e_s | 30.107 | 30.107 | 35.107 | 25.107 | 35.107 |
| output_tokens | 126.000 | 126.000 | 170.000 | 82.000 | 170.000 |

GPU: VRAM peak 7697.0 MiB · util mean 60.9% · power mean 56.6 W
