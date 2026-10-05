# Benchmarks

Measured results for the reference machines in the dev plan (§10), committed as JSON so before/after pairs can be compared in review.

| Reference | Machine |
|---|---|
| `cpu16` | 16 GB RAM, CPU only, AVX2. The tools record the CPU model, RAM size, type and speed, the disk type and the memory Docker can use. |
| `gpu8` | NVIDIA GPU with 8 GB of VRAM. |

Five kinds of file live here, told apart by their `kind`:

| `kind` | Written by | What it holds |
|---|---|---|
| `horus-llama-bench` | `scripts/benchmarks/run-llama-bench.py` | The plan's `llama-bench` run, with the llama.cpp build, the SHA-256 of every GGUF and the machine. The rows llama-bench printed are kept unchanged under `results`. |
| `horus-eval` | `scripts/eval/run-eval.py` | The 100-question test set of `tests/eval/testset.yaml` run against a live stack. |
| `horus-recorded` | by hand, once | A result measured before these tools existed, copied with its sources. The only one is `cpu-transformers-2026-09-01.json`, the CPU baseline B-91 compares against. |
| `horus-model-candidates` | `scripts/benchmarks/run-model-candidates.py` | The B-102 comparison of the model candidates with the Qwen3-4B baseline, one entry per GGUF, pointing at the three reports below. See [Model candidates](#model-candidates-b-102). |
| `horus-contract-probe` | `scripts/benchmarks/run-model-candidates.py` | The raw replies of one model to the B-98 answer request, each checked against the JSON schema it was sent with. |

`scripts/benchmarks/compare-benchmarks.py` reads all three, and also a bare llama-bench JSON array, and prints the §10 metrics table.

Never edit a measured number by hand. Re-run instead.

## File names

`<label>-<YYYY-MM-DD>.json`, where the date is the UTC date the run started. A second run with the same label on the same day gets `-2`, `-3`, ... and never overwrites the first.

- llama-bench: the label defaults to the reference machine, so the plan's file is `cpu16-<date>.json`. Give `--label` for a variant, e.g. `cpu16-b11500`.
- Evaluations: start with `eval-`, then the machine and what changed, e.g. `eval-cpu16-standard`, `eval-cpu16-lean`, `eval-gpu8-vllm`.

## The CPU baseline

`cpu-transformers-2026-09-01.json` records the measurement behind the "14 minutes" in the installer and the release notes: on 2026-09-01, with the CPU profile of that time (Qwen2.5-1.5B router in MAS and Qwen3-4B in bf16 in the agent, both in-process with Transformers), one grounded question took 14 min 14 s end to end and came back wrong (the anti-spiral guard replaced the answer). It ran on a 12-core laptop with 64 GB of RAM, not on `cpu16`, and the test set did not exist yet, so compare it as one data point:

```bash
python scripts/benchmarks/compare-benchmarks.py benchmarks/cpu-transformers-2026-09-01.json benchmarks/eval-cpu16-standard-<date>.json
```

## Running llama-bench

Runs the plan's command in the pinned llama.cpp image, `ghcr.io/ggml-org/llama.cpp:full-b11382` (the full image of the `server-b11382` build the CPU stack serves with):

```bash
llama-bench -m qwen3-4b-instruct-2507-Q4_K_M.gguf -m qwen3-4b-instruct-2507-Q5_K_M.gguf \
  -p 512,2048 -n 128 -d 0,4096 -ctk f16,q8_0 -ctv f16,q8_0 -t 4,8 -r 5 -o json --progress
```

Stop the Horus stack first (`cd src/infra && docker compose stop`): it competes for the same cores and memory. The script warns when `llm`, `mas`, `agent`, `knowledge_store` or `vllm` is running.

```bash
python scripts/benchmarks/run-llama-bench.py --models-dir ~/horus-bench-models --fetch
```

Only the Python standard library and Docker are needed. `--fetch` downloads the GGUFs that are missing with `src/infra/llm/fetch-model.sh` in the server image: resumable, size and SHA-256 checked before the file is renamed into place. Where Horus is installed with a CPU profile, the Q4_K_M is already in the stack's model folder (`models/` at the top of the Horus folder, or the installer's `--models-dir`, see `scripts/models/README.md`): `--models-dir models --fetch` uses it and adds the Q5_K_M next to it.

| GGUF | Source | Size (bytes) | SHA-256 |
|---|---|---:|---|
| `qwen3-4b-instruct-2507-Q4_K_M.gguf` | `unsloth/Qwen3-4B-Instruct-2507-GGUF` @ `a06e946bb6b655725eafa393f4a9745d460374c9`, `Qwen3-4B-Instruct-2507-Q4_K_M.gguf` | 2497281120 | `3605803b982cb64aead44f6c1b2ae36e3acdb41d8e46c8a94c6533bc4c67e597` |
| `qwen3-4b-instruct-2507-Q5_K_M.gguf` | same repository and revision, `Qwen3-4B-Instruct-2507-Q5_K_M.gguf` | 2889514080 | `5bde5e9d883622acb02bf77fe7dcbc56a8b9a9ad4be78a72ca23a532658b4ecb` |

The sizes and hashes come from the Hugging Face API (`/api/models/unsloth/Qwen3-4B-Instruct-2507-GGUF/tree/<revision>`). The Q4_K_M row is the file the CPU stack downloads.

The defaults run 96 tests (2 models × pp512, pp2048 and tg128 × depth 0 and 4,096 × 2 K cache types × 2 V cache types × 2 thread counts), each repeated 5 times, and the depth-4,096 tests fill 4,096 tokens of context before every timed repetition: it is a long run on a CPU. Narrow it with the options below.

| Option | Meaning |
|---|---|
| `--models-dir DIR` or `--models-volume NAME` | Where the GGUFs are: a host folder, or a Docker volume. Mounted read-only at `/models`; `--fetch` mounts it writable to download. |
| `--model FILE` | A GGUF file name in that folder; repeat it. Default: the two files above. |
| `--fetch` | Download the missing files of the table above first. |
| `--prompts`, `--generations`, `--depths`, `--cache-types-k`, `--cache-types-v`, `--threads`, `--repetitions` | The llama-bench matrix. Defaults: `512,2048`, `128`, `0,4096`, `f16,q8_0`, `f16,q8_0`, `4,8`, `5`. A quantized V cache needs flash attention, which llama-bench's default `-fa auto` turns on. |
| `--reference`, `--label` | `machine.reference` and the file label. Both default to `cpu16`. |
| `--cpu-model`, `--ram`, `--ram-speed`, `--disk-type` | Override what the script detects. It says which values it could not detect. On Linux the RAM type and speed come from `dmidecode`, which needs root: run with `sudo` or pass `--ram-speed`. |
| `--image`, `--fetch-image` | Default `ghcr.io/ggml-org/llama.cpp:full-b11382` and `:server-b11382`. Keep them on the build the stack serves. |
| `--from-json RAW` | Enrich a llama-bench JSON array saved by hand instead of running it. Give `--models-dir` or `--models-volume` as well, or the hashes stay empty. |
| `--dry-run` | Print the Docker commands and stop. |
| `--out-dir` | Default `benchmarks/`. |

If llama-bench fails or prints something that is not its JSON, nothing is written to `benchmarks/` and its standard output is saved in the temporary folder for diagnosis.

### llama-bench report format

```json
{
  "kind": "horus-llama-bench",
  "schema_version": 1,
  "label": "cpu16",
  "run": {},
  "llama_cpp": {},
  "models": [],
  "machine": {},
  "summary": [],
  "results": []
}
```

| Field | Meaning |
|---|---|
| `run` | `started_at`, `finished_at`, `duration_s`, `git_commit`, `from_json` (the raw file, or `null`), `models_location` (`dir` or `volume`), `command` (the exact `docker run`), `matrix`. |
| `llama_cpp` | `image`, `image_digest` (from `docker image inspect`), `build` (`b` + the `build_number` llama-bench wrote into its rows), `build_number`, `build_commit`, `image_tag_matches` (the image tag names the same build). |
| `models[]` | `file`, `size_bytes`, `sha256` (computed in the container with `sha256sum`), `known_source`, `matches_known_sha256` (`false` for a file of our own, such as the one `scripts/models/convert-qwen3-4b-gguf.sh` builds). |
| `machine` | See [Machine](#machine). |
| `summary[]` | One row per result: `model`, `model_type`, `test` (`pp512`, `pp2048`, `tg128`), `n_depth`, `type_k`, `type_v`, `n_threads`, `flash_attn`, `avg_ts` and `stddev_ts` in tokens per second. |
| `results[]` | llama-bench's rows, unchanged. |

## Machine

Both kinds of run collect the same `machine` block on the host that runs the script:

| Field | Linux | Windows | macOS |
|---|---|---|---|
| `cpu_model`, `physical_cores`, `avx2` | `/proc/cpuinfo` | `Win32_Processor`, `IsProcessorFeaturePresent` | `sysctl` |
| `ram_total_bytes` (what the OS can use), `ram` | `/proc/meminfo` | `Win32_ComputerSystem` | `sysctl hw.memsize` |
| `ram_installed_bytes`, `ram_modules`, `ram_type`, `ram_speed` | `dmidecode -t memory` (root) | `Win32_PhysicalMemory` | `system_profiler` |
| `disk_type`, `disk_model` | `findmnt` and `lsblk` for the disk holding the models folder, or Docker's data root | `Get-PhysicalDisk` for that drive (Docker Desktop keeps its disk under `%LOCALAPPDATA%`) | `diskutil` |
| `docker` | `docker info`: `mem_total_bytes` (the memory Docker can use), `cpus`, `operating_system`, `kernel`, `server_version`, `cgroup_version`, `root_dir` | same; with WSL 2 this is the WSL VM, which gets half the RAM by default | same |

`os` and `logical_cpus` come from Python, and `sources` says where each value came from (`given` for an option). The evaluation adds `gpu` (`nvidia-smi`).

## Running an evaluation

The stack must be up, and the five files of `demo_assets/` must each be in the knowledge store exactly once. The runner checks this first and stops otherwise. Pass `--corpus-token` (the `CORPUS_SCAN_TOKEN` of `src/infra/.env`) to let it run `POST /corpus/scan` on the default `demo_assets` mount. Set `AGENT_RESPONSE_CACHE=0` for timing runs, and whenever the GGUF changes between runs: the cache key does not hold the model file, so a run could score answers cached for another model.

```bash
pip install httpx websockets pyyaml

python scripts/eval/run-eval.py --label eval-cpu16-standard --reference cpu16 --sample-resources
```

On the CPU stack the runner reads the llama-server facts from the running `llm` container (`docker inspect`, `GET /props` and the `.sha256` file written next to the GGUF once its hash was verified): the llama.cpp build, the model file and its SHA-256, and the server arguments, so the report says which context size and KV cache type ran. `--llama-cpp-build` and `--model-*` override them; on the GPU path, where there is no `llm` container, they are the only source.

In chat mode the runner also reads `GET /metrics` of MAS (`--mas-url`) before and after each question. The B-92 router's `mas_routing_decision_seconds` histogram then gives the router's own time and method for that question (`routing_decision`). MAS servers older than B-92 do not have it, and the field stays `null`.

| Option | Meaning |
|---|---|
| `--mode chat` (default) | Every question goes through `POST /tasks/new_task/` in `auto` mode, one new conversation per question, and the answer is read from the chat WebSocket. If the socket drops, the runner polls `GET /tasks/{id}` until the task ends. |
| `--mode retrieval` | Only queries the knowledge store (`GET /?query=...&n_results=--top-k`) for the 84 in-corpus questions and scores the source by rank (see [Source checking](#source-checking)). No LLM, takes seconds. `--top-k` counts passages, not documents: the knowledge store returns chunks of at most 1,000 characters, and the five `demo_assets/` files make 22 of them. The passages are mapped to their documents, each ranked by its best passage. Keep `--top-k` (default 50) at least the number of stored passages so `source_ranks` shows where a missed document landed. |
| `--ids`, `--category`, `--limit` | Run part of the set (comma-separated). |
| `--event-timeout` | Seconds to wait for each final answer (default 1800). |
| `--submit-timeout` | Seconds for the `new_task` request itself (default 900). Since B-93 MAS answers `202` with the queued task at once and routes in the background; servers older than B-93 kept the request open during routing. |
| `--no-warmup` | Skip the unscored warmup question that loads the model. The warmup question is fixed and not in the test set, so a response or prompt cache cannot make a scored answer faster. |
| `--sample-resources` | Every `--sample-interval` seconds (default 10), sample `docker stats` and the swap in use, and keep the peaks for the run, for each question and from the first scored question on. With every sample in which `--llm-container` runs, also read llama-server's `/proc/1/status` and that container's `memory.stat`, for `stack_peak_mem_bytes`. Just before the first scored question and again at the end, read each container's cgroup `memory.peak`, `memory.stat` and OOM kills, and llama-server's `/proc/1/status`; at the end, also each container's restart count. Needs cgroup v2. |
| `--llm-container` | The llama-server container (default `llm`). Its facts are recorded, and its `/metrics` counters are read before and after each question. `""` turns this off. |
| `--swap-container` | A running container whose `/proc/meminfo` gives the swap of the machine Docker runs on (default `mas`). On Linux that is the host; with Docker Desktop it is its VM, whose swap the host does not see. `""` turns it off. |
| `--llama-cpp-build`, `--model-*` | Override the llama-server facts. `--model-sha256` must be 64 hex characters. |
| `--reference`, `--cpu-model`, `--ram`, `--ram-speed`, `--disk-type` | `machine.reference`, and overrides of what is detected (see [Machine](#machine)). |
| `--resummarize FILE` | Recompute `summary` of an existing report after the reviewers filled in their verdicts. |

The report is rewritten after every question, so an interrupted run keeps what it measured (`run.completed` stays `false`).

## Comparing runs

```bash
python scripts/benchmarks/compare-benchmarks.py BEFORE.json AFTER.json
python scripts/benchmarks/compare-benchmarks.py --before cpu16-2026-10-06.json eval-cpu16-standard-2026-10-06.json \
  --after cpu16-2026-10-20.json eval-cpu16-lean-2026-10-20.json --out compare.md
python scripts/benchmarks/compare-benchmarks.py eval-cpu16-standard-2026-10-06.json
```

It prints Markdown, ready for a pull request: the machines, builds, models and test sets of both sides, warnings (different test sets, different machines, KV cache changed, unfinished runs, answers still waiting for review, recorded results, a memory peak the samples missed by more than 0.5 GiB or could not check, samples whose llama-server mapped pages could not be read, OOM kills or restart counts that could not be read), then the §10 table with a change column, then every llama-bench configuration side by side. Each side takes at most one llama-bench file and one evaluation or recorded file. One file alone prints its own table.

The llama-bench rows of the §10 table show one model (`--model`, a part of its file name; default the first in the file), one KV cache type for K and V (`--kv`, default `f16`) and the fastest thread count (`--threads` to fix one). Install time and peak disk are measured on a clean VM and are not in these files, so their rows stay empty.

| §10 metric | Read from |
|---|---|
| Prompt processing and generation (tokens/s) | llama-bench `summary`: pp512, pp2048, tg128, at depth 0 and 4,096 |
| Time to first token, total time (s) | evaluation `summary.ttft_s`, `summary.total_s` |
| Prompt reading per question, generation speed in the stack | evaluation `summary.llm` (llama-server `/metrics`) |
| Routing time (ms) and method | evaluation `summary.routing` (the router's own time and method, from MAS `/metrics`); the separate "submit to dispatch" row is `summary.dispatch_s`, which includes the queue |
| Peak RAM (GiB) and swap | evaluation `resources`: `stack_peak_mem_bytes` (the `P` of ADR-005: the largest `docker stats` total of one sample plus the model pages it left out in that sample), `containers_sum_peak_mem_bytes` (all containers at once) and `llm_mapped_outside_docker_stats_bytes`; the `llm` peaks, OOM kills, restarts, swap peak and swap growth during the questions |
| Answer correct (%) | `summary.manual_review.answer_correct_pct` (two reviewers) and `summary.answer_correct_auto` |
| Source correct (%) | `summary.source_correct_auto` |
| Quality with a q8_0 KV cache | two evaluations whose `llama_cpp.server.settings` differ in KV cache type: the table marks the KV row as changed |

## Evaluation report format

```json
{
  "kind": "horus-eval",
  "schema_version": 2,
  "label": "eval-cpu16-standard",
  "run": {},
  "testset": {},
  "llama_cpp": {"build": "b11382", "server": {}},
  "model": {"name": "qwen3-4b", "file": "...gguf", "sha256": "64 hex characters", "sha256_source": "..."},
  "machine": {},
  "resources": {},
  "summary": {},
  "questions": []
}
```

Schema version 2 added `llama_cpp.server`, `model.sha256_source`, the detected `machine` fields, the per-question `dispatch_s`, `routing_decision`, `llm` and `resources`, the cgroup, page cache, llama-server, restart, start-of-questions, ADR-005 `P` and Docker-host swap fields of `resources`, and `summary.dispatch_s`, `summary.routing` and `summary.llm`. Version 1 files still compare.

`llama_cpp.build` and every `model` field are `null` when neither the options nor a running `llm` container gave them (for example on the vLLM GPU path).

### `run`

| Field | Meaning |
|---|---|
| `mode` | `chat` or `retrieval`. |
| `started_at`, `finished_at` | UTC, ISO 8601. `finished_at` is `null` until the run ends. |
| `completed` | `false` while running or if the run was interrupted. |
| `git_commit` | Short commit of the checkout that ran the script. |
| `mas_url`, `ks_url`, `event_timeout_s`, `submit_timeout_s`, `top_k` | Run settings. |
| `warmup` | The warmup question that was asked before the scored ones, or `null`. |
| `server_settings` | `LLM_BACKEND`, `LLM_VLLM_URL` (`http://llm:8080/v1` is llama-server, `http://vllm:8000/v1` is vLLM), `LLM_VLLM_MODEL`, `KNOWLEDGE_STORE_N_RESULTS`, `AGENT_MAX_NEW_TOKENS`, `AGENT_MAX_CONTEXT_CHARS`, `AGENT_STREAM_TOKENS`, `AGENT_RESPONSE_CACHE`, `LLM_SERVER_THREADS`, `LLM_TORCH_INTRAOP_THREADS`, `AGENT_TORCH_INTRAOP_THREADS`, each labelled with where the value came from (the runner's environment, or `src/infra/.env` of this checkout). Turn the response cache off for timing runs. |
| `observed_models`, `observed_devices` | What the agent reported in its `reasoning.start` steps. |

### `testset`

`path`, `version` and `sha256` (line endings normalised to LF) of the test set file, the `corpus` file hashes it was written against, `items_total`, `items_run`, and the `filters` used.

### `llama_cpp.server`

`null` without an `llm` container. Otherwise `container`, `image`, `args` (the llama-server command line), `settings` (parsed from it: `model`, `alias`, `port`, `ctx_size`, `parallel`, `threads`, `load_mode`, `cache_ram_mib`, `flash_attn` when given, and `cache_type_k` and `cache_type_v`, `f16` when not given), `port`, `build_info` and `n_ctx` from `GET /props`, `build`, `model_path` and `model_sha256`.

### `resources`

`null` without `--sample-resources`. Otherwise:

| Field | Meaning |
|---|---|
| `samples` | Number of samples taken. |
| `container_peak_mem_bytes` | Peak per container from `docker stats`, which reports the cgroup's memory minus its inactive page cache (`inactive_file`): files read once (model files at start, database files) do not count, and the GGUF pages llama-server maps may not either (see `llm_mapped_outside_docker_stats_bytes`). |
| `containers_sum_peak_mem_bytes` | The largest total of one sample: memory in use by all containers at the same moment. |
| `llm_mapped_outside_docker_stats_bytes` | The model pages llama-server maps that `docker stats` can have left out, in the sample that gave `stack_peak_mem_bytes`: its `RssFile` minus the smaller of the `llm` cgroup's `file_mapped` and `active_file`. Mapped pages often stay on the inactive list while memory is plentiful, and on the first start after an install they are charged to the `llm-model` container that downloaded and hashed the GGUF. Reclaim can move them to the active list during the run, which is why every sample reads them. `null` when `stack_peak_mem_bytes` is. |
| `stack_peak_mem_bytes` | The largest total, over the samples taken while `--llm-container` ran, of the `docker stats` total of all containers and the model pages it left out in the same sample: the `P` ADR-005 sets its thresholds from. It can come from another sample than `containers_sum_peak_mem_bytes`. `null` without `--llm-container`, or when the status or `memory.stat` could not be read in any sample, or PID 1 of that container is not `llama-server`. |
| `samples_without_llm_pages` | Samples taken while `--llm-container` ran whose status or `memory.stat` could not be read. `stack_peak_mem_bytes` leaves them out; the comparison warns above 0. |
| `container_lifetime_peak_mem_bytes` | Each container's cgroup `memory.peak` at the end (cgroup v2, Linux 5.19 or later): the peak since the container started, its start-up included, all page cache included, between samples included. The peaks of different containers happen at different moments, so do not add them up. `null` for a container whose file could not be read. |
| `container_memory_stat` | Each container's `anon`, `file`, `active_file`, `inactive_file` and `file_mapped` from its cgroup `memory.stat` at the end, or `null` when it could not be read. |
| `llm_process` | `name` and `rss_file_bytes` (`RssFile`: resident pages mapped from files, the GGUF included) from `/proc/1/status` in `--llm-container` at the end, or `null`. |
| `container_oom_kills` | `oom_kill` of each container's cgroup `memory.events`, since the container last started. Anything above 0 means the kernel killed a process in that container. `null` for a container whose file could not be read: the comparison then leaves the row empty. |
| `container_restarts` | Each container's `RestartCount` (one `docker inspect` per container). A container restarted after an out-of-memory kill starts a new cgroup, whose `memory.events` count from 0 again, so read both fields. `null` for a container that could not be inspected. |
| `at_questions_start` | Read just before the first scored question, for every container `docker stats` has shown so far: `container_lifetime_peak_mem_bytes`, `container_oom_kills`, `container_memory_stat`, `llm_process` and `docker_host_swap_used_bytes`. `null` when the run stopped before its first question. |
| `unsampled_peak_excess_bytes` | For each container whose `memory.peak` rose during the questions: how far that `memory.peak`, less the container's `inactive_file` at the end, went above its `docker stats` peak. Page cache that stays put cancels out, so what is left is a spike between two samples, or page cache the kernel dropped after the peak (compare `inactive_file` in `at_questions_start`). Above 0.5 GiB, repeat with `--sample-interval 2`. `null` for a container whose check was not made: its `memory.peak` at the first question or at the end, or its `memory.stat`, could not be read. |
| `docker_host_swap_peak_used_bytes` | Peak swap in use on the machine Docker runs on, read inside `--swap-container`, over the whole run. |
| `docker_host_swap_growth_bytes` | The peak of the samples from `at_questions_start` on (the warmup and the corpus check left out), minus the swap in use at `at_questions_start` (0 if it shrank). |
| `swap_peak_used_bytes` | Peak swap in use on the machine running the script. With Docker Desktop this is not the VM's swap; read the Docker host fields. |

### `questions[]`

One entry per question, in test set order.

| Field | Meaning |
|---|---|
| `id`, `category`, `difficulty`, `question`, `expected_answer` | Copied from the test set. |
| `expected_source` | List of document file names, or `null` for greetings, arithmetic and questions the corpus cannot answer. |
| `expected_route`, `observed_route` | `DIRECT_ANSWER` (MAS answered without an agent), `AGENT` (a task was dispatched) or `NONE` (MAS could not route the question and replied with a message). Read from the `route` of the final WebSocket event; servers older than B-93 gave it in the HTTP response. |
| `status` | `ok`, `error` or `timeout`. `error` holds the reason. `timeout` also covers a task stopped by the MAS `TASK_TIMEOUT` watchdog: its notice arrives as the answer over the WebSocket, or polling finds the task `canceled`. |
| `conversation_id`, `task_id`, `answered_by` | Where to look the run up in the UI or the database. |
| `timing_source` | `websocket`, `poll` (the socket dropped and the result came from `GET /tasks/{id}`, so `total_s` is accurate to `--poll-interval`) or `http`. |
| `submit_http_s` | Time until `POST /tasks/new_task/` returned. Since B-93 this is only the time to queue the task; routing time is part of `first_event_s` and `total_s`. |
| `first_event_s`, `retrieval_s`, `reasoning_start_s` | Time to the first WebSocket event (heartbeats and `task_status` frames are not counted), the first `retrieval.results` step, the first `reasoning.start` step. |
| `dispatch_s` | Time from submitting to the first event whose `stage` is past `queued` and `routing` (the dispatch to an agent), or to the final answer when MAS answered during routing. It includes the HTTP submit and the wait in the queue, so it is not the router's time. `null` when the events carry no `stage` (servers older than B-93). |
| `routing_decision` | The router's own work for the question, from the change in MAS's `mas_routing_decision_seconds` histogram: `decisions` (1 normally; 0 when the task named its agent and the router did not run), `methods` (`rules`, `embedding`, `llm` or `none`, with counts) and `seconds`. `{"restarted": true}` when MAS restarted during the question. `null` in retrieval mode or without the B-92 histogram. Run one evaluation at a time against a stack: the counters are global. |
| `ttft_s` | Time to the first `reasoning.delta` step, i.e. the first streamed token. `null` when token streaming is off (`AGENT_STREAM_TOKENS`) or the backend does not stream. The agent holds back the first 500 characters to check them for a spiral, so this is the first token the user sees. |
| `total_s` | Time from submitting the question to the final answer. |
| `llm` | What llama-server did during the question, from its `/metrics` counters: `prompt_tokens`, `prompt_s` (time spent reading prompts, the server side of the time to first token, summed over every call MAS and the agent made), `generated_tokens`, `generation_s`, `decode_calls`, `prompt_tps`, `generation_tps`. `{"restarted": true}` when the counters went down, i.e. llama-server restarted during the question. `null` without an `llm` container or in retrieval mode. |
| `resources` | The peaks of the samples taken during the question: `samples`, `containers_sum_peak_mem_bytes`, `docker_host_swap_peak_used_bytes`, `swap_peak_used_bytes`. `null` without `--sample-resources` or when no sample fell inside the question. |
| `answer` | The final answer as received. |
| `retrieval_steps` | Number of `retrieval.results` steps the agent sent. `null` in retrieval mode. |
| `retrieved_sources` | One list per retrieval (each `retrieval.results` step, or the single knowledge-store query in retrieval mode): the distinct document titles in rank order, a document ranked by its best passage. `null` when a retrieval returned content without saying which documents it came from, which the agent still does when it reads a file named in the question or falls back to the document list. |
| `cited_sources` | Titles in the `sources` of the final answer event, or `null` when the answer carries no `sources` list (today's answers never do). |
| `source_basis` | What `source_correct_auto` was decided from: `cited`, `retrieval`, or `null` when it could not be decided. |
| `source_ranks` | For each expected document, its best rank over `retrieved_sources` (1 = first), `null` when it was never retrieved. |
| `models`, `devices` | Model and device of every generation for this question. |
| `fallback` | `spiral` or `timeout` when the answer is the agent's canned fallback text, `task_timeout` when it is the MAS watchdog's notice, else `null`. A fallback is never counted as correct. |
| `answer_correct_auto` | Every regex in the item's `answer_patterns` matches the answer (case-insensitive, after NFKC normalisation and removing Markdown emphasis). For questions outside the corpus the patterns detect a "the documents do not contain this" reply. `null` in retrieval mode. |
| `missing_patterns` | The patterns that did not match. |
| `source_correct_auto` | See [Source checking](#source-checking). `null` when it cannot be decided and for questions outside the corpus. |
| `route_correct` | `observed_route` equals `expected_route`. `null` in retrieval mode or when nothing was observed. |
| `review` | Two reviewer slots, `{"reviewer": null, "answer_correct": null, "comment": null}`, filled in by hand. `null` in retrieval mode. |

### `summary`

| Field | Meaning |
|---|---|
| `questions`, `status` | Number of questions and count per status. |
| `answer_correct_auto`, `source_correct_auto`, `route_correct` | `{"n", "correct", "pct"}` over the questions where the flag is not `null`. Failed and timed-out questions count as wrong answers; their source is only scored when the events seen before the failure already decide it. |
| `total_s`, `ttft_s`, `dispatch_s` | `{"n", "mean", "median", "p90", "min", "max", "sum"}` over the questions that have the value. |
| `routing` | `null` without router metrics. Otherwise `questions`, `mas_restarts`, `decided_once` (questions with exactly one decision), `without_decision`, `several_decisions`, `methods` (count per method over `decided_once`), `llm_pct` (share of `decided_once` routed by the LLM fallback), and the statistics of `decision_s` and `decision_s_without_llm`. |
| `llm` | `null` without server metrics. Otherwise `questions`, `server_restarts`, the same statistics of `prompt_s`, `prompt_tokens`, `generation_s` and `generated_tokens`, and `prompt_tps` and `generation_tps` over the whole run (total tokens over total seconds). |
| `fallbacks` | Count per fallback kind. |
| `source_rank` | `stats` of every expected document's `source_ranks` entry that is not `null`, plus `first` (how many were ranked first) and `not_retrieved` (how many were never retrieved). |
| `source_basis` | Count per `source_basis` over the in-corpus and direct questions (`not_observable` for `null`). |
| `manual_review` | `reviewed` (both reviewers gave a verdict), `pending`, `agreed_correct` (both said correct), `disagreements` (ids to discuss), `answer_correct_pct` = `agreed_correct / reviewed`. |
| `by_category` | The same rates, `source_rank` and `total_s` per category. |

## Model candidates (B-102)

Compares the five models of the dev plan with the Qwen3-4B-Instruct-2507 baseline, on the same test set, for B-98 JSON reliability, answers, speed and memory. On the CPU profiles one llama-server answers MAS and every agent, so each model is tried as that one server; a model per role only makes sense on the GPU profiles and is not covered here.

The facts come from `scripts/benchmarks/model-candidates.yaml` (versioned; looked up on Hugging Face and in the llama.cpp history on 2026-10-05). Every GGUF is pinned to a repository revision, and its size and SHA-256 are the ones Hugging Face serves for that revision. The defaults are both baseline quantisations and one file per candidate from its own publisher:

| Model | Repository | Licence (as the card states it) | Default GGUF | Size | Architecture, in llama.cpp since | Thinks by default |
|---|---|---|---|---:|---|---|
| Qwen3-4B-Instruct-2507 (baseline) | `Qwen/Qwen3-4B-Instruct-2507` | Apache-2.0 | `unsloth/Qwen3-4B-Instruct-2507-GGUF` Q4_K_M and Q5_K_M | 2.33 and 2.69 GiB | `qwen3`, served by the stack on b11382 | no |
| Spark-X2.5-4B | `XHToken/Spark-X2.5-4B` | Apache-2.0 | `XHToken/Spark-X2.5-4B-GGUF` Q4_K_M | 2.42 GiB | `spark2_5`, b10828 (#27868) | yes |
| NeoHorse-1-4B | `TokenRhythm/NeoHorse-1-4B` | Apache-2.0 | `TokenRhythm/NeoHorse-1-4B-GGUF` Q4_K_M | 2.52 GiB | `qwen35`, b7973 (#19435) | yes |
| Agents-A1-4B | `InternScience/Agents-A1-4B` | Apache-2.0, card metadata only | `InternScience/Agents-A1-4B-Q4_K_M-GGUF` Q4_K_M | 2.52 GiB | `qwen35`, b7973 (#19435) | yes |
| Ling-3.0-tiny | `inclusionAI/Ling-3.0-tiny` | MIT, card metadata only | `inclusionAI/Ling-3.0-tiny-GGUF` Q4_K_M | 4.49 GiB | `bailingmoe3`, b10460 (#26608) | yes |
| gemma-4-E4B | `google/gemma-4-E4B-it` | Apache-2.0 | `google/gemma-4-E4B-it-qat-q4_0-gguf` Q4_0 (quantisation-aware) | 4.80 GiB | `gemma4`, b8637 (#21309) | no |

All of them run on the pinned b11382. The catalog also lists optional files (`--all-quants`): the Q5_K_M of NeoHorse and Ling from their publishers, community Q5_K_M files of Spark and Agents-A1, ggml-org's Q4_0 and unsloth's Q4_K_M and Q5_K_M of Gemma. What to check before shipping any of them (`licence_flags` in the catalog, repeated in the summary):

- **Agents-A1-4B**: the licence is only in the card metadata, the repository has no LICENSE file, and no base model is declared (its GGUF architecture is the Qwen3.5 family's).
- **Ling-3.0-tiny**: MIT only in the card metadata, no LICENSE file. Its Q4_K_M is about twice the baseline and is mapped whole: watch the `llm` memory limit (6 GB by default).
- **gemma-4-E4B**: the card links Google's licence page, which reproduces the Apache License 2.0, and the same documentation links a prohibited use policy; confirm it is not part of the terms. The plan's `gemma-4-E4B` is the pretrained base model; the instruction-tuned `-it` is the one that can answer.

### Running it

Needs Docker, the Python packages of the evaluation (`pip install httpx websockets pyyaml`) and, for the serving steps, the CPU stack up with the five `demo_assets/` files in the knowledge store. Run it in two passes so that llama-bench does not compete with the stack:

```bash
cd src/infra && docker compose stop && cd ../..
python scripts/benchmarks/run-model-candidates.py --reference cpu16 --steps fetch,bench

cd src/infra && docker compose start && cd ../..
python scripts/benchmarks/run-model-candidates.py --resume benchmarks/model-candidates-<date>.json --steps probe,eval
```

The agent's response cache must be off for the `eval` step. Its key is made of the question, the retrieved passages, the corpus version and the agent's own settings (`LLM_BACKEND`, `LLM_VLLM_MODEL`, ...), and none of them change when the runner swaps the model behind the alias `llm`. With the cache on, a candidate would be handed the answers the model before it gave, for up to `AGENT_RESPONSE_CACHE_TTL` (an hour by default), and its answers, sources and timings would not be its own. Before it stops `llm`, the runner reads `AGENT_RESPONSE_CACHE` from the `agent` container (`docker inspect`). When it is on, or cannot be read, the runner refuses the serving steps (a `not served:` problem on every model) and leaves the stack as it is: set `AGENT_RESPONSE_CACHE=0` in `src/infra/.env`, recreate the agent with `cd src/infra && docker compose up -d agent` (`docker compose start` keeps the old environment) and run the second pass again. `--allow-response-cache` runs anyway and records the reason as a problem of every model. The `probe` step alone does not go through the cache.

| Step | What it does |
|---|---|
| `fetch` | Downloads each GGUF into `--models-dir` (default `models/`, where the stack reads its model) with the installer's B-95 downloader (`installer/model_manager.py`): resumable `.part` file, retries, SHA-256 check, then the `.sha256` marker the stack and `run-eval.py` read. When the installer cannot be imported it uses `src/infra/llm/fetch-model.sh` in the server image instead. |
| `bench` | `run-llama-bench.py` for that one file with the catalog's matrix: pp512, pp2048 and tg128 at depth 0 and 4,096, an f16 KV cache, 4 and 8 threads, 5 repetitions. The KV cache comparison stays B-91's. |
| `probe` | The B-98 request, sent straight to llama-server for the 94 questions that are not greetings or arithmetic. `scripts/eval/agent-contract-probe.py` is copied into the `agent` container and run with the agent's own code and settings: its knowledge-store retrieval, `SourceCatalog`, `answer_prompt`, `answer_response_format` and `_fit_vllm_prompt` build the request the agent sends (one call, temperature 0, `response_format` `json_schema`, not streamed). The raw reply is kept and checked on the host. One unscored warmup question goes first. It asks as the General-Assistant identity: the persona the agent puts before the system prompt of Finance-Analyst, Compliance-Officer and HR-Assistant is left out, and the `eval` step covers the routed identities. |
| `eval` | `run-eval.py` with `--llm-container llm-candidate --sample-resources`: the 100 questions through MAS and the agents, as a user asks them. |

For `probe` and `eval` the runner stops the stack's `llm` container, checks that it stopped (otherwise two models would answer under the alias `llm`, and it gives up), and starts `llm-candidate` in its place: the same image (the catalog's pinned `server-b11382`), the same arguments with `--model` replaced and `--reasoning off` added, the same memory limit, on the same Docker network under the alias `llm`, so MAS and the agents reach the candidate at `http://llm:8080` unchanged. It waits for `/health` (up to `--start-timeout`, 900 s), runs the steps, reads llama-server's `/proc/1/status` and the container's cgroup `memory.peak` and `memory.events` after each step, removes the container and goes to the next model. At the end, even after an error or Ctrl-C, it starts `llm` again, and says so when that fails. A model whose architecture llama-server does not know stops while loading; the summary keeps the last lines of its log.

`--reasoning off` is the default because Spark-X2.5, NeoHorse, Agents-A1 and Ling open a thinking block unless told not to, and the stack's `llm` service passes no reasoning flag (llama-server's default is `auto`). Run once more with `--reasoning auto` to measure them as the stack is configured today; every run records which it used.

| Option | Meaning |
|---|---|
| `--steps` | Among `fetch,bench,probe,eval` (default all four). |
| `--only` | Candidate ids (their default files) or GGUF ids from the catalog, comma-separated. `--all-quants` adds the optional files. |
| `--resume FILE` | Run more steps into an earlier summary: the models it holds (or `--only`), the reports it points at, its downloads and problems are kept, and `run.sessions` lists each pass. Also how to finish an interrupted run: with `--steps fetch` it tries a failed download again, and a pass that serves a model drops the `not served:` problems an earlier pass left on it. |
| `--reasoning` | `off` (default), `on` or `auto`, passed to the candidate llama-server. |
| `--llm-mem-limit` | Memory limit of `llm-candidate`, e.g. `8g`. Default: the stack `llm` container's. |
| `--allow-response-cache` | Run the `eval` step although the agent's response cache is on or could not be checked. Every model gets a problem saying so. |
| `--ids`, `--category`, `--limit` | Run part of the test set, for the probe and the evaluation alike. |
| `--bench-arg`, `--eval-arg` | One more argument for `run-llama-bench.py` or `run-eval.py`; repeat it, e.g. `--eval-arg=--no-warmup`. |
| `--models-dir`, `--out-dir`, `--catalog`, `--testset`, `--server-image`, `--stack-llm-container`, `--agent-container`, `--start-timeout` | Locations and names; the defaults fit a CPU install from this repository. |
| `--reference`, `--cpu-model`, `--ram`, `--ram-speed`, `--disk-type` | The machine block, as in the other tools, and passed to them. |
| `--dry-run` | Print what each step would run and stop. |
| `--resummarize FILE` | Rebuild a summary and its Markdown from its reports, e.g. after the reviewers filled in an evaluation. |

### Model candidates output

`model-candidates-<date>.json` and `model-candidates-<date>.md` (the tables, the licence flags and every problem), and next to them the folder `model-candidates-<date>/` with, for each model, `<gguf id>-llama-bench-<date>.json`, `<gguf id>-contract-<date>.json` and `<gguf id>-eval-<date>.json`. The summary is rewritten after every model, so an interrupted run keeps what it measured.

| Field of the summary | Meaning |
|---|---|
| `catalog` | `path`, `version`, `sha256`, `looked_up` and `pinned_build` of the catalog used. |
| `run` | `started_at` (first pass), `finished_at`, `completed`, `git_commit`, `steps` (every pass together), `reasoning`, `stack_llm` (the `llm` container whose arguments were reused: image, arguments, networks, memory limit), `testset`, and `sessions`: each pass with its steps, options, models folder, server image and memory limit. |
| `machine` | See [Machine](#machine). |
| `variants[]` | One per GGUF: the catalog facts (`candidate`, `name`, `licence`, `licence_flags`, `gguf_architecture`, `thinking_default`, `quant`, `file`, `gguf_repo`, `revision`, `publisher`, `size_bytes`, `sha256`), `fetch` (`status`, `method`), `reports` (paths of the three reports, relative to the summary), `llama_bench` (`build`, `speeds`: the fastest thread count of each test and depth, `model_sha256` and whether it matches the catalog), `contract` and `eval` (the headline figures of those reports), `server` (the `docker run` command, the build from `/props`, `n_ctx`, the memory limit and reasoning mode), `memory` (`after_probe` and `after_eval`: llama-server's `VmHWM`, `VmRSS`, `RssAnon` and `RssFile`, the container's `memory.peak` and OOM kills) and `problems`. |

The contract report (`horus-contract-probe`) holds `run`, `model`, `llama_server`, `summary` and `replies`, one per question:

| Field of a reply | Meaning |
|---|---|
| `json_valid` | The reply parses with a strict `json.loads` (how the agent reads llama-server) into an object that validates against the exact schema of that request: `status` `ok` or `not_found`, an `answer` string, and, when passages were shown, `sources` from their labels only, nothing else. `null` when the retrieval failed, which is not the model's doing. |
| `failure`, `violations` | Why not: `request_error`, `empty`, `truncated` (`finish_reason` `length`), `not_json` (text, a code fence or a `<think>` block around the object), `not_object`, `schema` (with each violation), `retrieval_error`. |
| `thought_first`, `reasoning_chars` | The model reasoned first (`reasoning_content`, or a `<think>` block in the reply). |
| `status`, `status_correct` | `ok` is expected for in-corpus questions, `not_found` for those the documents do not answer. |
| `answer_correct_auto`, `cited_sources`, `source_correct_auto` | The test set's patterns on the `answer` field; the documents of the cited labels; every expected document cited. An invalid reply counts as wrong. |
| `wall_s`, `prompt_tokens`, `completion_tokens`, `cached_tokens`, `prompt_tps`, `generation_tps` | From the reply's `usage` and llama-server's `timings`. |
| `content`, `labels`, `retrieved_titles` | The raw reply, the labels shown and the documents retrieved. |

`summary` gives `json_valid` (the JSON reliability), `status_correct`, `answer_correct_auto` and `source_correct_auto` as `{"n", "correct", "pct"}`, counts per failure, `thought_first`, `truncated`, `blank_answers`, the statistics of `wall_s`, `prompt_tokens` and `completion_tokens`, `prompt_tps` and `generation_tps` over the run, and the rates per category.

Nothing has been measured with it yet: the reference machines were not reachable when it was written.

## Recorded result format

`horus-recorded` files hold `label`, `recorded` (`date`, `runtime`, `how`, `sources`), `setup`, `machine`, `notes`, and `metrics`: a map from a row of the comparison table (`total_median_s`, `answer_correct_reviewed_pct`, `fallbacks`, ...) to `{"value", "n", "note"}`. Only what was measured is filled in.

## Source checking

Documents are compared by file name without extension. In order:

1. **Questions outside the corpus** are not scored (`null`).
2. **Greetings and arithmetic** are correct when no retrieval happened (`retrieval_steps` is 0) and the answer cites nothing. A greeting the router sent to an agent that queried the knowledge store is wrong.
3. **Cited sources.** When the final answer carries `sources`, the question is correct when every expected document is cited.
4. **Retrieved sources.** Otherwise the question is correct when every expected document is among the first N distinct documents of a retrieval, N being the number of expected documents (rank 1 for a one-document question, ranks 1 and 2 for a two-document one). Being returned somewhere is not enough: a deep enough retrieval returns every document. Several passages of one document count as that document once, at the rank of its first passage.
5. When the WebSocket dropped before the answer (`timing_source` is `poll`) or the question failed, events may be missing, so only what was seen decides: a retrieval that ranks the right documents first is still correct and a retrieval for a greeting is still wrong. Anything else is `null` rather than a guess.

Since B-97 the knowledge-store client keeps each passage's document, so the agent's `retrieval.results` steps carry the number of passages in `chunk_count` and the distinct document titles in rank order in `chunks`, and chat mode scores in-corpus sources from them. Answers still carry no sources until B-98. A question whose retrieval returned no passages (the agent read a file named in the question, or fell back to the document list) gets `source_basis: null` and `source_correct_auto: null`.

## Manual review

The automatic answer check is a regex heuristic. The plan's "answer correct (%)" is the two-reviewer verdict:

1. Each reviewer opens the report, reads every `answer` against `expected_answer` and the source document, and fills their slot in `review` with their name, `true` or `false`, and a comment when it is not obvious. A partially right answer is `false`, with the comment saying what was missing.
2. Discuss the ids in `summary.manual_review.disagreements` and settle them.
3. Run `python scripts/eval/run-eval.py --resummarize benchmarks/<file>.json` and commit the file.
