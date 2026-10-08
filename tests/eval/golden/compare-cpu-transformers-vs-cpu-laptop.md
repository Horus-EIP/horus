# Benchmark comparison

|  | before | after |
|---|---|---|
| Files | cpu-transformers-2026-09-01.json | cpu-laptop-2026-10-06.json, eval-laptop-cpu-standard-2026-10-06.json |
| Label | cpu-transformers | cpu-laptop + eval-laptop-cpu-standard |
| Run started | 2026-09-01 | 2026-10-06T11:51:56Z, 2026-10-06T10:40:37Z |
| Machine | 12-core laptop CPU (model not recorded) (12 cores) | dev-laptop: AMD Ryzen AI 9 HX 370 (12 cores) (12 cores, AVX2) |
| RAM | 64 GB | 64 GB host, Docker VM 31 GiB, LPDDR5, 7500 MT/s |
| Docker memory | — | 30.88 GiB |
| Disk | — | NVMe SSD |
| llama.cpp / runtime | Transformers in-process (no llama.cpp) | b11382 |
| Model | — | qwen3-4b-instruct-2507-Q4_K_M.gguf, qwen3-4b-instruct-2507-Q5_K_M.gguf |
| Model SHA-256 | — | 3605803b982c…, 5bde5e9d8836… |
| Test set | — | 1.0.0 (f6f11ee2fe10…) |
| llama-bench rows shown | — | qwen3-4b-instruct-2507-Q4_K_M.gguf, KV f16/f16, the fastest thread count |

- cpu-transformers is a recorded result (installer/profiles.py (cpu-standard notes), installer/horus_install.py (CPU warning), packaging/RELEASE-NOTES.md (Known limitations)), not a run of the test set.
- eval-laptop-cpu-standard: 100 answers still wait for the two reviewers.
- The two sides come from different machines.

## Section 10 metrics

| Metric | How it's measured | before | after | Change |
|---|---|---|---|---|
| Prompt processing pp512 (t/s) | llama-bench | — | 172.6 t/s (t=12) | — |
| Prompt processing pp2048 (t/s) | llama-bench | — | 141.3 t/s (t=12) | — |
| Generation tg128 (t/s) | llama-bench | — | 24.1 t/s (t=12) | — |
| Prompt processing pp512, depth 4096 (t/s) | llama-bench | — | 86.9 t/s (t=12) | — |
| Prompt processing pp2048, depth 4096 (t/s) | llama-bench | — | 80.1 t/s (t=12) | — |
| Generation tg128, depth 4096 (t/s) | llama-bench | — | 14.2 t/s (t=12) | — |
| Questions | test set items run | 1 | 100 | +99 |
| Time to first token, median (s) | first streamed token | — | 18.8 s (n=86) | — |
| Time to first token, p90 (s) | first streamed token | — | 39.4 s (n=86) | — |
| Total time, median (s) | submit to final answer | 854.0 s (n=1, 14m 14s) | 18.2 s (n=100) | -835.8 s (-98%) |
| Total time, p90 (s) | submit to final answer | — | 81.5 s (n=100) | — |
| Total time, whole run (s) | sum over the questions | 854.0 s (n=1) | 3,588.4 s (n=100) | not comparable: different question counts |
| Prompt reading per question, median (s) | llama-server /metrics | — | 13.2 s (n=100) | — |
| Generation speed in the stack (t/s) | llama-server /metrics | — | 11.4 t/s (n=100) | — |
| Routing decision, median (ms) | MAS /metrics, B-92 router | — | 18 ms (n=100) | — |
| Routing decision without the LLM, p90 (ms) | MAS /metrics, B-92 router | — | 23 ms (n=64) | — |
| Routed by the LLM fallback (%) | MAS /metrics, B-92 router | — | 36.0% (n=100) | — |
| Routing methods | MAS /metrics, B-92 router | — | embedding 58, llm 36, rules 6 | — |
| Submit to dispatch, median (ms) | task events, queue wait included | — | 137 ms (n=100) | — |
| Peak RAM of the stack (ADR-006 P) (GiB) | docker stats total + model pages left out, in one sample | — | 8.34 GiB | — |
| Peak RAM, all containers at once (GiB) | docker stats samples | — | 7.90 GiB | — |
| Model pages docker stats left out (GiB) | llama-server RssFile, memory.stat, in the sample of P | — | 0.44 GiB | — |
| Peak RAM, llm container (GiB) | docker stats | — | — | — |
| Peak RAM, llm, since it started (GiB) | cgroup memory.peak | — | — | — |
| Out-of-memory kills | cgroup memory.events | — | 0 | — |
| Container restarts | docker inspect | — | 0 | — |
| Peak swap used (GiB) | Docker host /proc/meminfo | — | 0.00 GiB | — |
| Swap growth during the questions (GiB) | Docker host /proc/meminfo | — | 0.00 GiB | — |
| Install time without the model (min) | clean VM (not in these files) | — | — | — |
| Peak disk during install (GB) | clean VM (not in these files) | — | — | — |
| Answer correct, two reviewers (%) | manual review | 0.0% (n=1, judged by hand) | — | — |
| Answer correct, automatic (%) | answer patterns | — | 93.0% (n=100) | — |
| Source correct (%) | expected document | — | 96.7% (n=90) | — |
| Canned fallback answers | spiral, timeout, watchdog | 1 (n=1, anti-spiral guard) | 0 (n=100) | -1 |
| KV cache K/V (q8_0 quality check) | llama-server arguments | — | f16/f16 | — |

## llama-bench, every configuration

| Model | Test | Depth | KV K/V | Threads | before (t/s) | after (t/s) | Change |
|---|---|---|---|---|---|---|---|
| qwen3-4b-instruct-2507-Q4_K_M.gguf | pp512 | 0 | f16/f16 | 12 | — | 172.6 t/s (± 5.45) | — |
| qwen3-4b-instruct-2507-Q4_K_M.gguf | pp2048 | 0 | f16/f16 | 12 | — | 141.3 t/s (± 0.22) | — |
| qwen3-4b-instruct-2507-Q4_K_M.gguf | tg128 | 0 | f16/f16 | 12 | — | 24.1 t/s (± 1.23) | — |
| qwen3-4b-instruct-2507-Q4_K_M.gguf | pp512 | 4096 | f16/f16 | 12 | — | 86.9 t/s (± 0.43) | — |
| qwen3-4b-instruct-2507-Q4_K_M.gguf | pp2048 | 4096 | f16/f16 | 12 | — | 80.1 t/s (± 0.3) | — |
| qwen3-4b-instruct-2507-Q4_K_M.gguf | tg128 | 4096 | f16/f16 | 12 | — | 14.2 t/s (± 0.44) | — |
| qwen3-4b-instruct-2507-Q4_K_M.gguf | pp512 | 0 | f16/q8_0 | 12 | — | 111.7 t/s (± 1.3) | — |
| qwen3-4b-instruct-2507-Q4_K_M.gguf | pp2048 | 0 | f16/q8_0 | 12 | — | 52.0 t/s (± 0.06) | — |
| qwen3-4b-instruct-2507-Q4_K_M.gguf | tg128 | 0 | f16/q8_0 | 12 | — | 23.7 t/s (± 0.92) | — |
| qwen3-4b-instruct-2507-Q4_K_M.gguf | pp512 | 4096 | f16/q8_0 | 12 | — | 15.0 t/s (± 0.02) | — |
| qwen3-4b-instruct-2507-Q4_K_M.gguf | pp2048 | 4096 | f16/q8_0 | 12 | — | 12.5 t/s (± 0.04) | — |
| qwen3-4b-instruct-2507-Q4_K_M.gguf | tg128 | 4096 | f16/q8_0 | 12 | — | 8.93 t/s (± 0.16) | — |
| qwen3-4b-instruct-2507-Q4_K_M.gguf | pp512 | 0 | q8_0/f16 | 12 | — | 149.4 t/s (± 2.26) | — |
| qwen3-4b-instruct-2507-Q4_K_M.gguf | pp2048 | 0 | q8_0/f16 | 12 | — | 105.3 t/s (± 1.47) | — |
| qwen3-4b-instruct-2507-Q4_K_M.gguf | tg128 | 0 | q8_0/f16 | 12 | — | 23.4 t/s (± 1.89) | — |
| qwen3-4b-instruct-2507-Q4_K_M.gguf | pp512 | 4096 | q8_0/f16 | 12 | — | 43.5 t/s (± 0.17) | — |
| qwen3-4b-instruct-2507-Q4_K_M.gguf | pp2048 | 4096 | q8_0/f16 | 12 | — | 36.7 t/s (± 0.04) | — |
| qwen3-4b-instruct-2507-Q4_K_M.gguf | tg128 | 4096 | q8_0/f16 | 12 | — | 13.2 t/s (± 0.26) | — |
| qwen3-4b-instruct-2507-Q4_K_M.gguf | pp512 | 0 | q8_0/q8_0 | 12 | — | 109.2 t/s (± 8.5) | — |
| qwen3-4b-instruct-2507-Q4_K_M.gguf | pp2048 | 0 | q8_0/q8_0 | 12 | — | 52.6 t/s (± 0.08) | — |
| qwen3-4b-instruct-2507-Q4_K_M.gguf | tg128 | 0 | q8_0/q8_0 | 12 | — | 23.6 t/s (± 0.49) | — |
| qwen3-4b-instruct-2507-Q4_K_M.gguf | pp512 | 4096 | q8_0/q8_0 | 12 | — | 15.4 t/s (± 0.02) | — |
| qwen3-4b-instruct-2507-Q4_K_M.gguf | pp2048 | 4096 | q8_0/q8_0 | 12 | — | 13.1 t/s (± 0.04) | — |
| qwen3-4b-instruct-2507-Q4_K_M.gguf | tg128 | 4096 | q8_0/q8_0 | 12 | — | 8.52 t/s (± 0.1) | — |
| qwen3-4b-instruct-2507-Q5_K_M.gguf | pp512 | 0 | f16/f16 | 12 | — | 264.5 t/s (± 2.6) | — |
| qwen3-4b-instruct-2507-Q5_K_M.gguf | pp2048 | 0 | f16/f16 | 12 | — | 200.8 t/s (± 2.94) | — |
| qwen3-4b-instruct-2507-Q5_K_M.gguf | tg128 | 0 | f16/f16 | 12 | — | 20.6 t/s (± 0.18) | — |
| qwen3-4b-instruct-2507-Q5_K_M.gguf | pp512 | 4096 | f16/f16 | 12 | — | 110.5 t/s (± 9.13) | — |
| qwen3-4b-instruct-2507-Q5_K_M.gguf | pp2048 | 4096 | f16/f16 | 12 | — | 96.9 t/s (± 0.07) | — |
| qwen3-4b-instruct-2507-Q5_K_M.gguf | tg128 | 4096 | f16/f16 | 12 | — | 13.0 t/s (± 0.13) | — |
| qwen3-4b-instruct-2507-Q5_K_M.gguf | pp512 | 0 | f16/q8_0 | 12 | — | 140.1 t/s (± 5.19) | — |
| qwen3-4b-instruct-2507-Q5_K_M.gguf | pp2048 | 0 | f16/q8_0 | 12 | — | 57.8 t/s (± 0.15) | — |
| qwen3-4b-instruct-2507-Q5_K_M.gguf | tg128 | 0 | f16/q8_0 | 12 | — | 20.3 t/s (± 1.88) | — |
| qwen3-4b-instruct-2507-Q5_K_M.gguf | pp512 | 4096 | f16/q8_0 | 12 | — | 14.9 t/s (± 0.99) | — |
| qwen3-4b-instruct-2507-Q5_K_M.gguf | pp2048 | 4096 | f16/q8_0 | 12 | — | 13.0 t/s (± 0.04) | — |
| qwen3-4b-instruct-2507-Q5_K_M.gguf | tg128 | 4096 | f16/q8_0 | 12 | — | 8.46 t/s (± 0.06) | — |
| qwen3-4b-instruct-2507-Q5_K_M.gguf | pp512 | 0 | q8_0/f16 | 12 | — | 231.3 t/s (± 6.15) | — |
| qwen3-4b-instruct-2507-Q5_K_M.gguf | pp2048 | 0 | q8_0/f16 | 12 | — | 138.3 t/s (± 1.88) | — |
| qwen3-4b-instruct-2507-Q5_K_M.gguf | tg128 | 0 | q8_0/f16 | 12 | — | 20.3 t/s (± 0.67) | — |
| qwen3-4b-instruct-2507-Q5_K_M.gguf | pp512 | 4096 | q8_0/f16 | 12 | — | 47.5 t/s (± 2.06) | — |
| qwen3-4b-instruct-2507-Q5_K_M.gguf | pp2048 | 4096 | q8_0/f16 | 12 | — | 39.6 t/s (± 0.04) | — |
| qwen3-4b-instruct-2507-Q5_K_M.gguf | tg128 | 4096 | q8_0/f16 | 12 | — | 12.4 t/s (± 0.01) | — |
| qwen3-4b-instruct-2507-Q5_K_M.gguf | pp512 | 0 | q8_0/q8_0 | 12 | — | 148.0 t/s (± 2.83) | — |
| qwen3-4b-instruct-2507-Q5_K_M.gguf | pp2048 | 0 | q8_0/q8_0 | 12 | — | 59.7 t/s (± 0.78) | — |
| qwen3-4b-instruct-2507-Q5_K_M.gguf | tg128 | 0 | q8_0/q8_0 | 12 | — | 19.9 t/s (± 0.08) | — |
| qwen3-4b-instruct-2507-Q5_K_M.gguf | pp512 | 4096 | q8_0/q8_0 | 12 | — | 15.3 t/s (± 0.4) | — |
| qwen3-4b-instruct-2507-Q5_K_M.gguf | pp2048 | 4096 | q8_0/q8_0 | 12 | — | 12.4 t/s (± 0.01) | — |
| qwen3-4b-instruct-2507-Q5_K_M.gguf | tg128 | 4096 | q8_0/q8_0 | 12 | — | 5.92 t/s (± 0.06) | — |

## Notes

- cpu-transformers: Retrieval was fine: the right document ranked first and held the figure. Generation failed: the anti-spiral guard replaced the answer.
- cpu-transformers: One question: the time is the solid part, the wrong answer is a single sample.
- cpu-transformers: Measured on a 12-core laptop with 64 GB of RAM, not on the 16 GB reference machine. The same laptop answers in about 4 seconds on its GPU.
- cpu-transformers: The 100-question test set did not exist yet, so this result cannot be compared item by item.
