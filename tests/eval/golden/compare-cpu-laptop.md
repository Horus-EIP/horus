# Benchmark

|  | run |
|---|---|
| Files | cpu-laptop-2026-10-06.json |
| Label | cpu-laptop |
| Run started | 2026-10-06T11:51:56Z |
| Machine | dev-laptop: AMD Ryzen AI 9 HX 370 (12 cores) (12 cores, AVX2) |
| RAM | 64 GB host, Docker VM 31 GiB, LPDDR5, 7500 MT/s |
| Docker memory | 30.88 GiB |
| Disk | NVMe SSD |
| llama.cpp / runtime | b11382 |
| Model | qwen3-4b-instruct-2507-Q4_K_M.gguf, qwen3-4b-instruct-2507-Q5_K_M.gguf |
| Model SHA-256 | 3605803b982c…, 5bde5e9d8836… |
| Test set | — |
| llama-bench rows shown | qwen3-4b-instruct-2507-Q4_K_M.gguf, KV f16/f16, the fastest thread count |

## Section 10 metrics

| Metric | How it's measured | run |
|---|---|---|
| Prompt processing pp512 (t/s) | llama-bench | 172.6 t/s (t=12) |
| Prompt processing pp2048 (t/s) | llama-bench | 141.3 t/s (t=12) |
| Generation tg128 (t/s) | llama-bench | 24.1 t/s (t=12) |
| Prompt processing pp512, depth 4096 (t/s) | llama-bench | 86.9 t/s (t=12) |
| Prompt processing pp2048, depth 4096 (t/s) | llama-bench | 80.1 t/s (t=12) |
| Generation tg128, depth 4096 (t/s) | llama-bench | 14.2 t/s (t=12) |
| Questions | test set items run | — |
| Time to first token, median (s) | first streamed token | — |
| Time to first token, p90 (s) | first streamed token | — |
| Total time, median (s) | submit to final answer | — |
| Total time, p90 (s) | submit to final answer | — |
| Total time, whole run (s) | sum over the questions | — |
| Prompt reading per question, median (s) | llama-server /metrics | — |
| Generation speed in the stack (t/s) | llama-server /metrics | — |
| Routing decision, median (ms) | MAS /metrics, B-92 router | — |
| Routing decision without the LLM, p90 (ms) | MAS /metrics, B-92 router | — |
| Routed by the LLM fallback (%) | MAS /metrics, B-92 router | — |
| Routing methods | MAS /metrics, B-92 router | — |
| Submit to dispatch, median (ms) | task events, queue wait included | — |
| Peak RAM of the stack (ADR-006 P) (GiB) | docker stats total + model pages left out, in one sample | — |
| Peak RAM, all containers at once (GiB) | docker stats samples | — |
| Model pages docker stats left out (GiB) | llama-server RssFile, memory.stat, in the sample of P | — |
| Peak RAM, llm container (GiB) | docker stats | — |
| Peak RAM, llm, since it started (GiB) | cgroup memory.peak | — |
| Out-of-memory kills | cgroup memory.events | — |
| Container restarts | docker inspect | — |
| Peak swap used (GiB) | Docker host /proc/meminfo | — |
| Swap growth during the questions (GiB) | Docker host /proc/meminfo | — |
| Install time without the model (min) | clean VM (not in these files) | — |
| Peak disk during install (GB) | clean VM (not in these files) | — |
| Answer correct, two reviewers (%) | manual review | — |
| Answer correct, automatic (%) | answer patterns | — |
| Source correct (%) | expected document | — |
| Canned fallback answers | spiral, timeout, watchdog | — |
| KV cache K/V (q8_0 quality check) | llama-server arguments | — |

## llama-bench, every configuration

| Model | Test | Depth | KV K/V | Threads | run (t/s) |
|---|---|---|---|---|---|
| qwen3-4b-instruct-2507-Q4_K_M.gguf | pp512 | 0 | f16/f16 | 12 | 172.6 t/s (± 5.45) |
| qwen3-4b-instruct-2507-Q4_K_M.gguf | pp2048 | 0 | f16/f16 | 12 | 141.3 t/s (± 0.22) |
| qwen3-4b-instruct-2507-Q4_K_M.gguf | tg128 | 0 | f16/f16 | 12 | 24.1 t/s (± 1.23) |
| qwen3-4b-instruct-2507-Q4_K_M.gguf | pp512 | 4096 | f16/f16 | 12 | 86.9 t/s (± 0.43) |
| qwen3-4b-instruct-2507-Q4_K_M.gguf | pp2048 | 4096 | f16/f16 | 12 | 80.1 t/s (± 0.3) |
| qwen3-4b-instruct-2507-Q4_K_M.gguf | tg128 | 4096 | f16/f16 | 12 | 14.2 t/s (± 0.44) |
| qwen3-4b-instruct-2507-Q4_K_M.gguf | pp512 | 0 | f16/q8_0 | 12 | 111.7 t/s (± 1.3) |
| qwen3-4b-instruct-2507-Q4_K_M.gguf | pp2048 | 0 | f16/q8_0 | 12 | 52.0 t/s (± 0.06) |
| qwen3-4b-instruct-2507-Q4_K_M.gguf | tg128 | 0 | f16/q8_0 | 12 | 23.7 t/s (± 0.92) |
| qwen3-4b-instruct-2507-Q4_K_M.gguf | pp512 | 4096 | f16/q8_0 | 12 | 15.0 t/s (± 0.02) |
| qwen3-4b-instruct-2507-Q4_K_M.gguf | pp2048 | 4096 | f16/q8_0 | 12 | 12.5 t/s (± 0.04) |
| qwen3-4b-instruct-2507-Q4_K_M.gguf | tg128 | 4096 | f16/q8_0 | 12 | 8.93 t/s (± 0.16) |
| qwen3-4b-instruct-2507-Q4_K_M.gguf | pp512 | 0 | q8_0/f16 | 12 | 149.4 t/s (± 2.26) |
| qwen3-4b-instruct-2507-Q4_K_M.gguf | pp2048 | 0 | q8_0/f16 | 12 | 105.3 t/s (± 1.47) |
| qwen3-4b-instruct-2507-Q4_K_M.gguf | tg128 | 0 | q8_0/f16 | 12 | 23.4 t/s (± 1.89) |
| qwen3-4b-instruct-2507-Q4_K_M.gguf | pp512 | 4096 | q8_0/f16 | 12 | 43.5 t/s (± 0.17) |
| qwen3-4b-instruct-2507-Q4_K_M.gguf | pp2048 | 4096 | q8_0/f16 | 12 | 36.7 t/s (± 0.04) |
| qwen3-4b-instruct-2507-Q4_K_M.gguf | tg128 | 4096 | q8_0/f16 | 12 | 13.2 t/s (± 0.26) |
| qwen3-4b-instruct-2507-Q4_K_M.gguf | pp512 | 0 | q8_0/q8_0 | 12 | 109.2 t/s (± 8.5) |
| qwen3-4b-instruct-2507-Q4_K_M.gguf | pp2048 | 0 | q8_0/q8_0 | 12 | 52.6 t/s (± 0.08) |
| qwen3-4b-instruct-2507-Q4_K_M.gguf | tg128 | 0 | q8_0/q8_0 | 12 | 23.6 t/s (± 0.49) |
| qwen3-4b-instruct-2507-Q4_K_M.gguf | pp512 | 4096 | q8_0/q8_0 | 12 | 15.4 t/s (± 0.02) |
| qwen3-4b-instruct-2507-Q4_K_M.gguf | pp2048 | 4096 | q8_0/q8_0 | 12 | 13.1 t/s (± 0.04) |
| qwen3-4b-instruct-2507-Q4_K_M.gguf | tg128 | 4096 | q8_0/q8_0 | 12 | 8.52 t/s (± 0.1) |
| qwen3-4b-instruct-2507-Q5_K_M.gguf | pp512 | 0 | f16/f16 | 12 | 264.5 t/s (± 2.6) |
| qwen3-4b-instruct-2507-Q5_K_M.gguf | pp2048 | 0 | f16/f16 | 12 | 200.8 t/s (± 2.94) |
| qwen3-4b-instruct-2507-Q5_K_M.gguf | tg128 | 0 | f16/f16 | 12 | 20.6 t/s (± 0.18) |
| qwen3-4b-instruct-2507-Q5_K_M.gguf | pp512 | 4096 | f16/f16 | 12 | 110.5 t/s (± 9.13) |
| qwen3-4b-instruct-2507-Q5_K_M.gguf | pp2048 | 4096 | f16/f16 | 12 | 96.9 t/s (± 0.07) |
| qwen3-4b-instruct-2507-Q5_K_M.gguf | tg128 | 4096 | f16/f16 | 12 | 13.0 t/s (± 0.13) |
| qwen3-4b-instruct-2507-Q5_K_M.gguf | pp512 | 0 | f16/q8_0 | 12 | 140.1 t/s (± 5.19) |
| qwen3-4b-instruct-2507-Q5_K_M.gguf | pp2048 | 0 | f16/q8_0 | 12 | 57.8 t/s (± 0.15) |
| qwen3-4b-instruct-2507-Q5_K_M.gguf | tg128 | 0 | f16/q8_0 | 12 | 20.3 t/s (± 1.88) |
| qwen3-4b-instruct-2507-Q5_K_M.gguf | pp512 | 4096 | f16/q8_0 | 12 | 14.9 t/s (± 0.99) |
| qwen3-4b-instruct-2507-Q5_K_M.gguf | pp2048 | 4096 | f16/q8_0 | 12 | 13.0 t/s (± 0.04) |
| qwen3-4b-instruct-2507-Q5_K_M.gguf | tg128 | 4096 | f16/q8_0 | 12 | 8.46 t/s (± 0.06) |
| qwen3-4b-instruct-2507-Q5_K_M.gguf | pp512 | 0 | q8_0/f16 | 12 | 231.3 t/s (± 6.15) |
| qwen3-4b-instruct-2507-Q5_K_M.gguf | pp2048 | 0 | q8_0/f16 | 12 | 138.3 t/s (± 1.88) |
| qwen3-4b-instruct-2507-Q5_K_M.gguf | tg128 | 0 | q8_0/f16 | 12 | 20.3 t/s (± 0.67) |
| qwen3-4b-instruct-2507-Q5_K_M.gguf | pp512 | 4096 | q8_0/f16 | 12 | 47.5 t/s (± 2.06) |
| qwen3-4b-instruct-2507-Q5_K_M.gguf | pp2048 | 4096 | q8_0/f16 | 12 | 39.6 t/s (± 0.04) |
| qwen3-4b-instruct-2507-Q5_K_M.gguf | tg128 | 4096 | q8_0/f16 | 12 | 12.4 t/s (± 0.01) |
| qwen3-4b-instruct-2507-Q5_K_M.gguf | pp512 | 0 | q8_0/q8_0 | 12 | 148.0 t/s (± 2.83) |
| qwen3-4b-instruct-2507-Q5_K_M.gguf | pp2048 | 0 | q8_0/q8_0 | 12 | 59.7 t/s (± 0.78) |
| qwen3-4b-instruct-2507-Q5_K_M.gguf | tg128 | 0 | q8_0/q8_0 | 12 | 19.9 t/s (± 0.08) |
| qwen3-4b-instruct-2507-Q5_K_M.gguf | pp512 | 4096 | q8_0/q8_0 | 12 | 15.3 t/s (± 0.4) |
| qwen3-4b-instruct-2507-Q5_K_M.gguf | pp2048 | 4096 | q8_0/q8_0 | 12 | 12.4 t/s (± 0.01) |
| qwen3-4b-instruct-2507-Q5_K_M.gguf | tg128 | 4096 | q8_0/q8_0 | 12 | 5.92 t/s (± 0.06) |
