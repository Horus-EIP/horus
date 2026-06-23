# Pipeline benchmark — `baseline`

- **Timestamp:** 2026-06-23T19:02:03Z
- **Git commit:** 2415eea
- **GPU:** NVIDIA GeForce RTX 4070 Laptop GPU (driver 610.62, 8188 MiB)
- **MAS:** http://localhost:8000  ·  **KS:** http://localhost:8080
- **Agent:** `16b09ee8-7760-498e-ab3e-0a8f8ad7e4ce` · model `Qwen/Qwen3-4B-Instruct-2507` · device `cuda`
- **Token count method:** approx:chars-over-4
- **Server gen params (resolved):** AGENT_MAX_NEW_TOKENS=3072 (src/infra/.env), KNOWLEDGE_STORE_N_RESULTS=4 (src/infra/.env)

> `decode_s` is the agent's own reported model inference time (reasoning.done.duration_seconds). `ttft_proxy_s` is submit→reasoning.start (routing+retrieval+prefill setup), not true TTFT yet. All times in seconds unless noted.
