# ADR-005: What Horus does on machines with less than 16 GB of RAM

**Date:** 2026-10-05
**Status:** Proposed. The thresholds below come from arithmetic, the compose ceilings and estimates. The B-91 measurements confirm or move them with the rule in [Measurement protocol](#measurement-protocol).
**Deciders:** Loup Marquez-Luttringer, Noah Gibelli, Matheus Lopez
**Related:**

- Dev plan B-91 (benchmark and this decision), B-100 (implements it in the installer), B-95 (model manifest), B-96 (embeddings without torch)
- `installer/profiles.py` (`cpu-lean`, `cpu-standard`, `CPU_RAM_SPLIT_GIB`)
- `src/infra/docker-compose.cpu.yml` (the `llm` service)
- `scripts/models/README.md` (model, build and memory of the CPU model server)
- `benchmarks/README.md` (how the numbers below get measured)

---

## Context

Since B-90 the CPU profiles run one llama-server (the `llm` service, build b11382) with Qwen3-4B-Instruct-2507 Q4_K_M for MAS and every agent. The installer picks `cpu-standard` at 15.0 GiB of RAM or more and `cpu-lean` below. Today `cpu-lean` runs exactly what `cpu-standard` runs: nothing has been decided for smaller machines (open decision 1 of the dev plan).

Two facts shape the decision:

1. **The model is no longer most of the memory.** Before B-90 the CPU stack held about 12 GB of models in-process. Now llama-server needs about 5 GiB at most, and the rest of the stack (knowledge store, MAS, agent, databases, broker, web client, observability) needs more than that: about 8 GiB in the planning figures below.
2. **The memory that counts is the memory Docker can use, not the RAM on the box.** On Linux they are the same. On Windows, Docker Desktop runs the containers in the WSL 2 virtual machine, which gets **50% of the Windows RAM by default** (Microsoft's `.wslconfig` documentation). A 16 GB Windows laptop therefore gives the whole stack about 7.8 GiB unless the user raises the WSL memory. The installer reads the host RAM today (`Win32_ComputerSystem.TotalPhysicalMemory`), so it cannot see this.

The baseline to beat, measured on 2026-09-01 with the old CPU profile (1.5B router and 4B worker in bf16, both with Transformers) on a 12-core laptop with 64 GB of RAM: one grounded question took **14 min 14 s** and the answer was wrong (the anti-spiral guard fired). It is recorded in `benchmarks/cpu-transformers-2026-09-01.json`.

## Memory budget of the CPU stack today

Sizes in GiB (1024³ bytes). "Arithmetic" is computed from file sizes and the model configuration; "estimate" comes from the profile notes in `installer/profiles.py`; "allowance" is a planning figure that nothing measures yet. The planning figure takes the top of each estimate.

| Part | Planning figure | Basis | Ceiling (`mem_limit`) |
|---|---:|---|---:|
| llama-server weights, Q4_K_M | 2.33 | arithmetic: 2,497,281,120 bytes, memory-mapped | |
| llama-server KV cache, 8,192 tokens, f16 | 1.13 | arithmetic: 36 layers × 8 KV heads × 128 × 2 (K and V) × 2 bytes × 8,192 | |
| llama-server compute buffers | 0.50 | allowance; llama-server prints `CPU compute buffer size` at start | |
| llama-server prompt cache, `--cache-ram 1024` | 1.00 | the configured cap | |
| **llm container** | **4.96** | | 6g |
| Knowledge store: BGE base, spaCy `en_core_web_trf`, t5-small, distilbart-cnn-6-6 in fp32, torch, Chroma | 3.00 | estimate: 2.1 GB of weights, 2 to 3 GB in use | 6g |
| MAS: Python, torch, MiniLM skill embedder | 1.50 | estimate: 1 to 1.5 GB | 3g |
| Agent: Python, torch, spaCy `en_core_web_sm` | 1.50 | estimate: 1 to 1.5 GB | 4g |
| postgres, redis, rabbitmq, web client, loki, promtail, tempo, prometheus | 2.00 | allowance | none |
| **All containers** | **12.96** | | |
| Kernel, Docker itself, page cache for the memory-mapped model, and on a Linux desktop the session and browser | 2.00 | allowance (headroom) | |
| **Memory Docker must see** | **14.96** | | |

The ceilings add up to 19 GiB: they stop one runaway container, they are not a budget. The 14.96 GiB total matches the 15.0 GiB split the installer already uses.

The model weights are file-backed. When memory runs short the kernel can drop those pages and read them again from disk: answers get slower (bearable on an SSD, not on a hard disk), nothing is killed. The KV cache, the compute buffers and the Python services are anonymous memory: a shortfall there means swap or an out-of-memory kill. The budget counts the weights in full anyway, because an answer that re-reads 2.3 GiB from disk for every token is not usable.

## Options

All three keep one llama-server for MAS and every agent.

| | A. Smaller GGUF | B. The 4B with a 4,096 context and a q8_0 KV cache | C. Not supported |
|---|---|---|---|
| Model | Qwen3-1.7B Q4_K_M (1,107,409,472 bytes, Apache 2.0) or Qwen2.5-1.5B-Instruct Q4_K_M (1,117,320,736 bytes, Apache 2.0) | the same Qwen3-4B-Instruct-2507 Q4_K_M | none |
| llama-server | weights 1.03 or 1.04, KV at 4,096 q8_0 0.23 or 0.06, buffers 0.50, `--cache-ram 256` 0.25: about **2.0** | weights 2.33, KV at 4,096 q8_0 0.30, buffers 0.50, `--cache-ram 256` 0.25: **3.38** | |
| Memory Docker must see | 12.0 (1.5B) to 12.5 (1.7B) | **13.5** (13.38 rounded up) | |
| Answers | a different, weaker model. In the clean-install round of 2026-09-05, the 1.5B router of the old CPU profile produced invalid routing JSON and sent questions to the wrong agent. Qwen3-1.7B is a hybrid thinking model and needs thinking turned off. | the same model as `cpu-standard`. The q8_0 KV cache may cost some quality, which the test set measures. A 4,096-token context holds the 6,000-character retrieval cap of the CPU profiles: both clients size the answer to the room left. | the installer stops before any large download and says why |
| Cost | a second model to host, hash, evaluate (100 questions, two reviewers) and keep working with the B-98 answer contract | configuration only: five values on the `llm` command line and the context size of the clients | a screen and a threshold |

The per-token KV sizes come from the model configurations on Hugging Face: Qwen3-1.7B has 28 layers and 8 KV heads, Qwen2.5-1.5B 28 layers and 2 KV heads, both with 128-wide heads. q8_0 stores 32 values in 34 bytes.

What the numbers say:

- **No option makes an 8 GB machine work.** An 8 GB machine reports about 7.6 to 7.8 GiB. The containers other than llama-server already need 8.0 GiB in the planning figure.
- **A smaller model buys 1.4 to 1.5 GiB over option B,** and that does not move any common RAM size across the line: 12 GB machines report about 11.6 to 11.8 GiB, under option A's 12.0 to 12.5.
- **Option B helps the 16 GB machines that report less than 15.0 GiB**, which is common on laptops that reserve part of the RAM for the integrated GPU, and Windows machines where WSL is given between 13.5 and 15 GiB.

## Decision (proposed)

The thresholds apply to the memory Docker can use, `docker info --format '{{.MemTotal}}'`, in GiB.

| Docker memory | Profile | llama-server |
|---|---|---|
| 15.0 GiB or more | `cpu-standard`, unchanged | Qwen3-4B Q4_K_M, `--ctx-size 8192`, f16 KV cache, `--cache-ram 1024` |
| 13.5 GiB to under 15.0 GiB | `cpu-lean` = option B | the same GGUF, `--ctx-size 4096`, `--cache-type-k q8_0 --cache-type-v q8_0`, `--flash-attn on`, `--cache-ram 256` |
| under 13.5 GiB | **not supported** (option C) | none: the installer stops before pulling images or downloading the model |

Option A is rejected for now: it does not bring a new class of machine into reach and it costs answer quality and a second model to maintain. It is reconsidered only under the trigger in the protocol below.

On Windows the "not supported" screen must say that Docker gets half of the RAM by default and how to change it (WSL Settings → Memory and processor, or `memory=` in `%UserProfile%\.wslconfig`, then `wsl --shutdown`). The installer must not change that setting itself. A 16 GB Windows machine cannot give WSL 13.5 GiB and keep Windows usable, so with these planning figures the realistic Windows floor is 24 GB of RAM with WSL set to 14 GB (lean) or 16 GB (standard). If the measured stack is smaller, the thresholds drop and this changes with them.

### What B-100 implements

1. Read the Docker memory with `docker info` once Docker is reachable, and decide on it, within the first minute. Keep the host RAM in `horus-profile.json` next to it.
2. `docker-compose.cpu.yml`: take the KV cache types and the prompt cache from the environment, for example `--cache-type-k ${LLM_SERVER_CACHE_TYPE_K:-f16}`, `--cache-type-v ${LLM_SERVER_CACHE_TYPE_V:-f16}`, `--flash-attn ${LLM_SERVER_FLASH_ATTN:-auto}` and `--cache-ram ${LLM_SERVER_CACHE_RAM_MIB:-1024}`. `--ctx-size` already follows `LLM_VLLM_MAX_MODEL_LEN`.
3. `installer/profiles.py`: `cpu-lean` sets `LLM_VLLM_MAX_MODEL_LEN=4096`, the two cache types to `q8_0`, flash attention `on` (a quantized V cache needs it), `LLM_SERVER_CACHE_RAM_MIB=256` and `LLM_SERVER_MEM_LIMIT=5g`. Its trigger becomes 13.5 to 15.0 GiB of Docker memory.
4. Under 13.5 GiB: the "not supported" screen with the Docker memory found, the 13.5 GiB needed, and on Windows the WSL advice above. `--profile cpu-lean` or `--profile cpu-standard` still overrides it, with a warning, for people who want to try.
5. The thresholds live in one place in `installer/profiles.py` and quote this ADR.

## Measurement protocol

Reference machine: 16 GB of RAM, CPU only, AVX2 (dev plan §10). Linux gives Docker the whole RAM. If the reference machine runs Windows, set the WSL memory explicitly and put it in the run label. Turn the response cache off for every timed run (`AGENT_RESPONSE_CACHE=0`).

1. **Model speed.** With the stack stopped:
   `python scripts/benchmarks/run-llama-bench.py --models-dir <folder> --fetch`
   writes `benchmarks/cpu16-<date>.json` (the plan's llama-bench matrix, enriched with the build, the GGUF hashes and the machine).
2. **`cpu-standard`, 100 questions.** Install with `--profile cpu-standard`, then
   `python scripts/eval/run-eval.py --label eval-cpu16-standard --reference cpu16 --sample-resources`.
   The report records the llama-server arguments, the build, the model hash, the Docker memory, the peak memory per container from `docker stats`, each container's `memory.peak` and OOM kills, and the swap of the Docker host.
3. **Option B, 100 questions, same machine.** Until B-100 lands, set `LLM_VLLM_MAX_MODEL_LEN=4096` in `src/infra/.env` and add this file to `COMPOSE_FILE`:

   ```yaml
   services:
     llm:
       command: [--model, /models/qwen3-4b-instruct-2507-Q4_K_M.gguf, --alias, qwen3-4b,
                 --host, 0.0.0.0, --port, "8080", --ctx-size, "4096", --parallel, "1",
                 --cache-type-k, q8_0, --cache-type-v, q8_0, --flash-attn, "on",
                 --load-mode, mmap, --cache-ram, "256", --threads, "${LLM_SERVER_THREADS:-4}", --metrics]
   ```

   then `python scripts/eval/run-eval.py --label eval-cpu16-lean --reference cpu16 --sample-resources`.
4. **The threshold itself.** Give Docker exactly the lean threshold the decision rule below computes from step 3 (13.5 GiB if the rule does not move it), with WSL `memory=` or a Linux VM of that size, and repeat step 3 with the label `eval-cpu16-lean-at-threshold`.
5. **Compare.**
   `python scripts/benchmarks/compare-benchmarks.py benchmarks/eval-cpu16-standard-<date>.json benchmarks/eval-cpu16-lean-<date>.json`
   prints the §10 table; the KV cache row marks it as the q8_0 quality check. Compare `cpu-standard` with the 2026-09-01 baseline the same way.

### Decision rule

- `P` = the run's `resources.containers_sum_peak_mem_bytes`, or the sum of the containers' `memory.peak` when that is larger. Threshold = `P` + 2.0 GiB of headroom, rounded **up** to the next 0.5 GiB. This replaces 15.0 for `cpu-standard` (step 2) and 13.5 for `cpu-lean` (step 3).
- Option B stays only if, against the `cpu-standard` run on the same machine and test set version: the two-reviewer answer-correct rate and the source-correct rate are each within 5 points, every question ends with an answer, and the run at the threshold (step 4) has no OOM kill and less than 256 MiB of swap growth. Otherwise `cpu-lean` becomes "not supported" too, and the single threshold is the `cpu-standard` one.
- Option A comes back only if the measured peak of the containers other than `llm` is 3.5 GiB or less, which is plausible after B-96 removes torch from MAS and the knowledge store. Then an 8 GB machine (about 7.6 GiB for Docker) could hold a 2 GiB model server, and the 1.7B model must pass the same quality rule against the 4B.
- When the rule moves a threshold, update this ADR (status Accepted, with the measured numbers and the files in `benchmarks/`) and the constants in `installer/profiles.py` in the same change.

## Consequences

**Pros**

- One model on every CPU profile: the test set, the B-98 answer contract and the reviewers' work cover every CPU user.
- The lean profile is configuration, not a new artefact: nothing more to host or hash.
- Small machines learn they are not supported before a 25 GB download, not after.
- The decision follows the memory Docker really has, which also catches Windows machines whose WSL limit is too low.

**Cons / accepted risks**

- 8 GB machines, 12 GB machines and 16 GB Windows machines with default WSL settings are not supported, unless the measurements show a smaller stack than the planning figures.
- The q8_0 KV cache may lower answer quality; the rule above measures it before anyone relies on it.
- A 4,096-token context leaves less room for the answer and for MAS aggregation of several agents; the clients shrink the answer budget instead of failing.
- The planning figures for the knowledge store, MAS, the agent and the small services are estimates and allowances until the first `--sample-resources` run.

## Alternatives considered

- **Option A, a 1.5B to 1.7B model:** rejected for now, see above.
- **A 4,096 context with an f16 KV cache:** saves 0.56 GiB instead of 0.83 GiB. Kept as the fallback if q8_0 fails the quality rule but the memory rule passes with f16; it needs its own run.
- **Swap as the safety net:** rejected. The containers have `memswap_limit` equal to `mem_limit` on purpose (B-88): a container that swaps makes every answer crawl instead of failing clearly.
- **Dropping loki, promtail, tempo and prometheus on `cpu-lean`:** possible extra saving, not measured. The admin logs, metrics and traces pages would be empty. To weigh once the per-container peaks exist.

## References

- llama.cpp server options (`--cache-type-k`, `--cache-type-v`, `--flash-attn`, `--cache-ram`, `--ctx-size`): https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md
- llama-bench: https://github.com/ggml-org/llama.cpp/blob/master/tools/llama-bench/README.md
- WSL memory default (50% of the Windows RAM) and `.wslconfig`: https://learn.microsoft.com/en-us/windows/wsl/wsl-config
- Model files and sizes: https://huggingface.co/unsloth/Qwen3-4B-Instruct-2507-GGUF, https://huggingface.co/unsloth/Qwen3-1.7B-GGUF, https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF
