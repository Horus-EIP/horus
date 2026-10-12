# Benchmark comparison

|  | before | after |
|---|---|---|
| Files | eval-laptop-cpu-lean-2026-10-06.json | eval-laptop-cpu-standard-2026-10-06.json |
| Label | eval-laptop-cpu-lean | eval-laptop-cpu-standard |
| Run started | 2026-10-06T13:19:31Z | 2026-10-06T10:40:37Z |
| Machine | dev-laptop: AMD Ryzen AI 9 HX 370 (12 cores) (12 cores, AVX2) | dev-laptop: AMD Ryzen AI 9 HX 370 (12 cores) (12 cores, AVX2) |
| RAM | 64 GB host, Docker VM 31 GiB, LPDDR5, 7500 MT/s | 64 GB host, Docker VM 31 GiB, LPDDR5, 7500 MT/s |
| Docker memory | 30.88 GiB | 30.88 GiB |
| Disk | NVMe SSD | NVMe SSD |
| llama.cpp / runtime | b11382 | b11382 |
| Model | qwen3-4b-instruct-2507-Q4_K_M.gguf | qwen3-4b-instruct-2507-Q4_K_M.gguf |
| Model SHA-256 | 3605803b982c… | 3605803b982c… |
| Test set | 1.0.0 (f6f11ee2fe10…) | 1.0.0 (f6f11ee2fe10…) |
| llama-bench rows shown | — | — |

- eval-laptop-cpu-lean: 30 answers still wait for the two reviewers.
- eval-laptop-cpu-standard: 100 answers still wait for the two reviewers.
- The KV cache differs (q8_0/q8_0 before, f16/f16 after): the answer and source rows measure its quality cost.

## Section 10 metrics

| Metric | How it's measured | before | after | Change |
|---|---|---|---|---|
| Prompt processing pp512 (t/s) | llama-bench | — | — | — |
| Prompt processing pp2048 (t/s) | llama-bench | — | — | — |
| Generation tg128 (t/s) | llama-bench | — | — | — |
| Prompt processing pp512, depth 4096 (t/s) | llama-bench | — | — | — |
| Prompt processing pp2048, depth 4096 (t/s) | llama-bench | — | — | — |
| Generation tg128, depth 4096 (t/s) | llama-bench | — | — | — |
| Questions | test set items run | 30 | 100 | +70 |
| Time to first token, median (s) | first streamed token | 32.7 s (n=28) | 18.8 s (n=86) | -13.8 s (-42%) |
| Time to first token, p90 (s) | first streamed token | 42.1 s (n=28) | 39.4 s (n=86) | -2.68 s (-6%) |
| Total time, median (s) | submit to final answer | 33.2 s (n=30) | 18.2 s (n=100) | -15.0 s (-45%) |
| Total time, p90 (s) | submit to final answer | 43.8 s (n=30) | 81.5 s (n=100) | +37.7 s (+86%) |
| Total time, whole run (s) | sum over the questions | 1,021.5 s (n=30) | 3,588.4 s (n=100) | not comparable: different question counts |
| Prompt reading per question, median (s) | llama-server /metrics | 27.3 s (n=30) | 13.2 s (n=100) | -14.0 s (-52%) |
| Generation speed in the stack (t/s) | llama-server /metrics | 9.01 t/s (n=30) | 11.4 t/s (n=100) | +2.35 t/s (+26%) |
| Routing decision, median (ms) | MAS /metrics, B-92 router | 13 ms (n=30) | 18 ms (n=100) | +5 ms (+38%) |
| Routing decision without the LLM, p90 (ms) | MAS /metrics, B-92 router | 17 ms (n=19) | 23 ms (n=64) | +6 ms (+35%) |
| Routed by the LLM fallback (%) | MAS /metrics, B-92 router | 36.7% (n=30) | 36.0% (n=100) | -0.7 pts |
| Routing methods | MAS /metrics, B-92 router | embedding 19, llm 11 | embedding 58, llm 36, rules 6 | changed |
| Submit to dispatch, median (ms) | task events, queue wait included | 130 ms (n=30) | 137 ms (n=100) | +7 ms (+5%) |
| Peak RAM of the stack (ADR-006 P) (GiB) | docker stats total + model pages left out, in one sample | 6.21 GiB | 8.34 GiB | +2.13 GiB (+34%) |
| Peak RAM, all containers at once (GiB) | docker stats samples | 3.91 GiB | 7.90 GiB | +3.99 GiB (+102%) |
| Model pages docker stats left out (GiB) | llama-server RssFile, memory.stat, in the sample of P | 2.30 GiB | 0.44 GiB | -1.86 GiB (-81%) |
| Peak RAM, llm container (GiB) | docker stats | — | — | — |
| Peak RAM, llm, since it started (GiB) | cgroup memory.peak | — | — | — |
| Out-of-memory kills | cgroup memory.events | 0 | 0 | +0 |
| Container restarts | docker inspect | 0 | 0 | +0 |
| Peak swap used (GiB) | Docker host /proc/meminfo | 0.00 GiB | 0.00 GiB | +0.00 GiB |
| Swap growth during the questions (GiB) | Docker host /proc/meminfo | 0.00 GiB | 0.00 GiB | +0.00 GiB |
| Install time without the model (min) | clean VM (not in these files) | — | — | — |
| Peak disk during install (GB) | clean VM (not in these files) | — | — | — |
| Answer correct, two reviewers (%) | manual review | — | — | — |
| Answer correct, automatic (%) | answer patterns | 96.7% (n=30) | 93.0% (n=100) | -3.7 pts |
| Source correct (%) | expected document | 93.3% (n=30) | 96.7% (n=90) | +3.4 pts |
| Canned fallback answers | spiral, timeout, watchdog | 0 (n=30) | 0 (n=100) | +0 |
| KV cache K/V (q8_0 quality check) | llama-server arguments | q8_0/q8_0 | f16/f16 | changed |
