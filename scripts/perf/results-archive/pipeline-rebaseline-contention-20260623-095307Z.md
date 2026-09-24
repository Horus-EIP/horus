# Pipeline benchmark — `rebaseline-contention`

- **Timestamp:** 2026-06-23T09:53:07Z
- **Git commit:** 76b0d94
- **GPU:** NVIDIA GeForce RTX 4070 Laptop GPU (driver 610.62, 8188 MiB)
- **MAS:** http://localhost:8000  ·  **KS:** http://localhost:8080
- **Agent:** `ca6eca16-0c5c-4caa-be8d-8d1be0b75043` · model `Qwen/Qwen3-4B-Instruct-2507` · device `cuda`
- **Token count method:** approx:chars-over-4
- **Server gen params (resolved):** AGENT_MAX_NEW_TOKENS=3072 (src/infra/.env), KNOWLEDGE_STORE_N_RESULTS=8 (agent settings default)

> `decode_s` is the agent's own reported model inference time (reasoning.done.duration_seconds). `ttft_proxy_s` is submit→reasoning.start (routing+retrieval+prefill setup), not true TTFT yet. All times in seconds unless noted.

## Contention (generation vs. concurrent KS ingestion)

KS load: 3 workers, 75 docs embedded during the loaded run.

| state | decode_tok/s median | e2e median | VRAM peak MiB | GPU util mean % |
|---|---|---|---|---|
| idle | 21.50 | 20.06 | 7632.0 | 55.8 |
| under load | 7.94 | 56.87 | 7644.0 | 33.9 |

**Decode tok/s drop under load: 63.1%** — this is the headroom the NPU embedder offload (Phase 6) can recover.
