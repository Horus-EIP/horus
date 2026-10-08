# Benchmark

|  | run |
|---|---|
| Files | eval-laptop-cpu-standard-2026-10-06.json |
| Label | eval-laptop-cpu-standard |
| Run started | 2026-10-06T10:40:37Z |
| Machine | dev-laptop: AMD Ryzen AI 9 HX 370 (12 cores) (12 cores, AVX2) |
| RAM | 64 GB host, Docker VM 31 GiB, LPDDR5, 7500 MT/s |
| Docker memory | 30.88 GiB |
| Disk | NVMe SSD |
| llama.cpp / runtime | b11382 |
| Model | qwen3-4b-instruct-2507-Q4_K_M.gguf |
| Model SHA-256 | 3605803b982c… |
| Test set | 1.0.0 (f6f11ee2fe10…) |
| llama-bench rows shown | — |

- eval-laptop-cpu-standard: 100 answers still wait for the two reviewers.

## Section 10 metrics

| Metric | How it's measured | run |
|---|---|---|
| Prompt processing pp512 (t/s) | llama-bench | — |
| Prompt processing pp2048 (t/s) | llama-bench | — |
| Generation tg128 (t/s) | llama-bench | — |
| Prompt processing pp512, depth 4096 (t/s) | llama-bench | — |
| Prompt processing pp2048, depth 4096 (t/s) | llama-bench | — |
| Generation tg128, depth 4096 (t/s) | llama-bench | — |
| Questions | test set items run | 100 |
| Time to first token, median (s) | first streamed token | 18.8 s (n=86) |
| Time to first token, p90 (s) | first streamed token | 39.4 s (n=86) |
| Total time, median (s) | submit to final answer | 18.2 s (n=100) |
| Total time, p90 (s) | submit to final answer | 81.5 s (n=100) |
| Total time, whole run (s) | sum over the questions | 3,588.4 s (n=100) |
| Prompt reading per question, median (s) | llama-server /metrics | 13.2 s (n=100) |
| Generation speed in the stack (t/s) | llama-server /metrics | 11.4 t/s (n=100) |
| Routing decision, median (ms) | MAS /metrics, B-92 router | 18 ms (n=100) |
| Routing decision without the LLM, p90 (ms) | MAS /metrics, B-92 router | 23 ms (n=64) |
| Routed by the LLM fallback (%) | MAS /metrics, B-92 router | 36.0% (n=100) |
| Routing methods | MAS /metrics, B-92 router | embedding 58, llm 36, rules 6 |
| Submit to dispatch, median (ms) | task events, queue wait included | 137 ms (n=100) |
| Peak RAM of the stack (ADR-006 P) (GiB) | docker stats total + model pages left out, in one sample | 8.34 GiB |
| Peak RAM, all containers at once (GiB) | docker stats samples | 7.90 GiB |
| Model pages docker stats left out (GiB) | llama-server RssFile, memory.stat, in the sample of P | 0.44 GiB |
| Peak RAM, llm container (GiB) | docker stats | — |
| Peak RAM, llm, since it started (GiB) | cgroup memory.peak | — |
| Out-of-memory kills | cgroup memory.events | 0 |
| Container restarts | docker inspect | 0 |
| Peak swap used (GiB) | Docker host /proc/meminfo | 0.00 GiB |
| Swap growth during the questions (GiB) | Docker host /proc/meminfo | 0.00 GiB |
| Install time without the model (min) | clean VM (not in these files) | — |
| Peak disk during install (GB) | clean VM (not in these files) | — |
| Answer correct, two reviewers (%) | manual review | — |
| Answer correct, automatic (%) | answer patterns | 93.0% (n=100) |
| Source correct (%) | expected document | 96.7% (n=90) |
| Canned fallback answers | spiral, timeout, watchdog | 0 (n=100) |
| KV cache K/V (q8_0 quality check) | llama-server arguments | f16/f16 |
