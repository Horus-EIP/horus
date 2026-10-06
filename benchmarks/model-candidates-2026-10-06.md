# Model candidates, 2026-10-06

Catalog `scripts/benchmarks/model-candidates.yaml` version 1.0.0, llama.cpp b11382, reasoning `off`, steps fetch, probe, eval. Machine: dev-laptop, AMD Ryzen AI 9 HX 370 (12 cores), 64 GB host, Docker VM 31 GiB. Run completed.

## Reliability and answers

JSON valid: replies to the B-98 request that parse and validate against the schema sent. Probe columns come from the direct contract probe, chat columns from the 20-question evaluation.

| Model | GGUF | Licence | JSON valid | Thought first | Status correct | Answer correct (probe) | Source correct (probe) | Answer correct (chat, auto) | Answer correct (reviewed) | Source correct (chat) |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Qwen3-4B-Instruct-2507 (baseline) | Q4_K_M, community | Apache-2.0 | 20/20 (100.0%) | 0 | 20/20 (100.0%) | 19/20 (95.0%) | 20/20 (100.0%) | 19/20 (95.0%) | – | 20/20 (100.0%) |
| Qwen3-4B-Instruct-2507 (baseline) | Q5_K_M, community | Apache-2.0 | 20/20 (100.0%) | 0 | 20/20 (100.0%) | 19/20 (95.0%) | 20/20 (100.0%) | 19/20 (95.0%) | – | 20/20 (100.0%) |
| Spark-X2.5-4B | Q4_K_M, model author | Apache-2.0 | 20/20 (100.0%) | 0 | 20/20 (100.0%) | 18/20 (90.0%) | 20/20 (100.0%) | 18/20 (90.0%) | – | 20/20 (100.0%) |
| NeoHorse-1-4B | Q4_K_M, model author | Apache-2.0 | 20/20 (100.0%) | 0 | 20/20 (100.0%) | 19/20 (95.0%) | 20/20 (100.0%) | 19/20 (95.0%) | – | 20/20 (100.0%) |
| Agents-A1-4B | Q4_K_M, model author | Apache-2.0 | 20/20 (100.0%) | 0 | 20/20 (100.0%) | 19/20 (95.0%) | 20/20 (100.0%) | 19/20 (95.0%) | – | 20/20 (100.0%) |
| Ling-3.0-tiny | Q4_K_M, model author | MIT | 20/20 (100.0%) | 0 | 20/20 (100.0%) | 19/20 (95.0%) | 20/20 (100.0%) | 19/20 (95.0%) | – | 20/20 (100.0%) |
| gemma-4-E4B | Q4_0 (QAT), model author | Apache-2.0 | 20/20 (100.0%) | 0 | 20/20 (100.0%) | 19/20 (95.0%) | 20/20 (100.0%) | 19/20 (95.0%) | – | 20/20 (100.0%) |

## Speed and memory

llama-bench tokens per second with an f16 KV cache, best thread count, depth 0 unless named. Medians in seconds. llm VmHWM and cgroup peak: the candidate llama-server; stack peak: the evaluation's `stack_peak_mem_bytes`, the ADR-005 `P`: the peak memory of the whole stack, model pages included.

| Model | GGUF | File | pp512 | pp2048 | tg128 | tg128 @ 4096 | Probe reply | Chat answer | Chat first token | llm VmHWM | llm cgroup peak | Stack peak | OOM kills |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Qwen3-4B-Instruct-2507 (baseline) | Q4_K_M, community | 2.33 GiB | – | – | – | – | 12.8 | 11.4 | 11.6 | 5.99 GiB | 6.00 GiB | 8.00 GiB | 0 |
| Qwen3-4B-Instruct-2507 (baseline) | Q5_K_M, community | 2.69 GiB | – | – | – | – | 7.9 | 9.1 | 9.4 | 4.98 GiB | 4.99 GiB | 7.16 GiB | 0 |
| Spark-X2.5-4B | Q4_K_M, model author | 2.42 GiB | – | – | – | – | 12.5 | 14.9 | 14.4 | 5.67 GiB | 5.69 GiB | 7.45 GiB | 0 |
| NeoHorse-1-4B | Q4_K_M, model author | 2.52 GiB | – | – | – | – | 12.8 | 14.3 | 14.0 | 5.74 GiB | 5.76 GiB | 7.52 GiB | 0 |
| Agents-A1-4B | Q4_K_M, model author | 2.52 GiB | – | – | – | – | 12.9 | 14.7 | 14.8 | 5.71 GiB | 5.72 GiB | 7.90 GiB | 0 |
| Ling-3.0-tiny | Q4_K_M, model author | 4.49 GiB | – | – | – | – | 6.1 | 6.7 | 7.0 | 5.99 GiB | 6.00 GiB | 7.81 GiB | 0 |
| gemma-4-E4B | Q4_0 (QAT), model author | 4.80 GiB | – | – | – | – | 14.6 | 15.3 | 15.3 | 5.99 GiB | 6.00 GiB | 8.16 GiB | 0 |

## Licence flags

- Agents-A1-4B: The licence is only in the card metadata: no LICENSE file and no licence text in the repository. Ask InternScience or check before shipping.
- Agents-A1-4B: No base model is declared; the GGUF architecture is qwen35, the Qwen3.5 family (Apache 2.0).
- Ling-3.0-tiny: The licence is only in the card metadata: no LICENSE file in the repository. Check before shipping.
- gemma-4-E4B: Google's Gemma documentation, where the licence page lives, also links a prohibited use policy. Confirm it is not part of the terms before shipping.
