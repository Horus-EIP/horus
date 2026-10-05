# Benchmarks

Measured results for the reference machines in the dev plan (§10), committed as JSON so before/after pairs can be compared in review.

| Reference | Machine |
|---|---|
| `cpu16` | 16 GB RAM, CPU only, AVX2. The tools record the CPU model, RAM size, type and speed, the disk type and the memory Docker can use. |
| `gpu8` | NVIDIA GPU with 8 GB of VRAM. |

Three kinds of file live here, told apart by their `kind`:

| `kind` | Written by | What it holds |
|---|---|---|
| `horus-llama-bench` | `scripts/benchmarks/run-llama-bench.py` | The plan's `llama-bench` run, with the llama.cpp build, the SHA-256 of every GGUF and the machine. The rows llama-bench printed are kept unchanged under `results`. |
| `horus-eval` | `scripts/eval/run-eval.py` | The 100-question test set of `tests/eval/testset.yaml` run against a live stack. |
| `horus-recorded` | by hand, once | A result measured before these tools existed, copied with its sources. The only one is `cpu-transformers-2026-09-01.json`, the CPU baseline B-91 compares against. |

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

Only the Python standard library and Docker are needed. `--fetch` downloads the GGUFs that are missing with `src/infra/llm/fetch-model.sh` in the server image: resumable, size and SHA-256 checked before the file is renamed into place.

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

The stack must be up, and the five files of `demo_assets/` must each be in the knowledge store exactly once. The runner checks this first and stops otherwise. Pass `--corpus-token` (the `CORPUS_SCAN_TOKEN` of `src/infra/.env`) to let it run `POST /corpus/scan` on the default `demo_assets` mount. Set `AGENT_RESPONSE_CACHE=0` for timing runs.

```bash
pip install httpx websockets pyyaml

python scripts/eval/run-eval.py --label eval-cpu16-standard --reference cpu16 --sample-resources
```

On the CPU stack the runner reads the llama-server facts from the running `llm` container (`docker inspect`, `GET /props` and the `.sha256` file `llm-model` writes next to the GGUF once it has verified it): the llama.cpp build, the model file and its SHA-256, and the server arguments, so the report says which context size and KV cache type ran. `--llama-cpp-build` and `--model-*` override them; on the GPU path, where there is no `llm` container, they are the only source.

| Option | Meaning |
|---|---|
| `--mode chat` (default) | Every question goes through `POST /tasks/new_task/` in `auto` mode, one new conversation per question, and the answer is read from the chat WebSocket. If the socket drops, the runner polls `GET /tasks/{id}` until the task ends. |
| `--mode retrieval` | Only queries the knowledge store (`GET /?query=...&n_results=--top-k`) for the 84 in-corpus questions and scores the source by rank (see [Source checking](#source-checking)). No LLM, takes seconds. `--top-k` counts passages, not documents: the knowledge store returns chunks of at most 1,000 characters, and the five `demo_assets/` files make 22 of them. The passages are mapped to their documents, each ranked by its best passage. Keep `--top-k` (default 50) at least the number of stored passages so `source_ranks` shows where a missed document landed. |
| `--ids`, `--category`, `--limit` | Run part of the set (comma-separated). |
| `--event-timeout` | Seconds to wait for each final answer (default 1800). |
| `--submit-timeout` | Seconds for the `new_task` request itself (default 900). Since B-93 MAS answers `202` with the queued task at once and routes in the background; servers older than B-93 kept the request open during routing. |
| `--no-warmup` | Skip the unscored warmup question that loads the model. The warmup question is fixed and not in the test set, so a response or prompt cache cannot make a scored answer faster. |
| `--sample-resources` | Every `--sample-interval` seconds (default 10), sample `docker stats` and the swap in use, and keep the peaks for the run and for each question. At the end, read each container's cgroup `memory.peak` and OOM kills. |
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

It prints Markdown, ready for a pull request: the machines, builds, models and test sets of both sides, warnings (different test sets, different machines, KV cache changed, unfinished runs, answers still waiting for review, recorded results), then the §10 table with a change column, then every llama-bench configuration side by side. Each side takes at most one llama-bench file and one evaluation or recorded file. One file alone prints its own table.

The llama-bench rows of the §10 table show one model (`--model`, a part of its file name; default the first in the file), one KV cache type for K and V (`--kv`, default `f16`) and the fastest thread count (`--threads` to fix one). Install time and peak disk are measured on a clean VM and are not in these files, so their rows stay empty.

| §10 metric | Read from |
|---|---|
| Prompt processing and generation (tokens/s) | llama-bench `summary`: pp512, pp2048, tg128, at depth 0 and 4,096 |
| Time to first token, total time (s) | evaluation `summary.ttft_s`, `summary.total_s` |
| Prompt reading per question, generation speed in the stack | evaluation `summary.llm` (llama-server `/metrics`) |
| Routing time (ms) | evaluation `summary.routing_s`; the method is in the router logs |
| Peak RAM (GiB) and swap | evaluation `resources` |
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

Schema version 2 added `llama_cpp.server`, `model.sha256_source`, the detected `machine` fields, the per-question `routing_s`, `llm` and `resources`, the cgroup and Docker-host swap fields of `resources`, and `summary.routing_s` and `summary.llm`. Version 1 files still compare.

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
| `container_peak_mem_bytes`, `containers_sum_peak_mem_bytes` | Peak per container from `docker stats`, and peak of the per-sample total. |
| `container_lifetime_peak_mem_bytes` | Each container's cgroup `memory.peak` at the end: the true peak since the container started, between samples included (cgroup v2, Linux 5.19 or later). |
| `container_oom_kills` | `oom_kill` of each container's cgroup `memory.events`. Anything above 0 means a container hit its `mem_limit`. |
| `docker_host_swap_peak_used_bytes` | Peak swap in use on the machine Docker runs on, read inside `--swap-container`. |
| `swap_peak_used_bytes` | Peak swap in use on the machine running the script. With Docker Desktop this is not the VM's swap; read the field above. |

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
| `routing_s` | Time from submitting to the first event whose `stage` is past `queued` and `routing` (the dispatch to an agent), or to the final answer when MAS answered during routing. It includes the wait in the queue. `null` when the events carry no `stage` (servers older than B-93). |
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
| `total_s`, `ttft_s`, `routing_s` | `{"n", "mean", "median", "p90", "min", "max", "sum"}` over the questions that have the value. |
| `llm` | `null` without server metrics. Otherwise `questions`, `server_restarts`, the same statistics of `prompt_s`, `prompt_tokens`, `generation_s` and `generated_tokens`, and `prompt_tps` and `generation_tps` over the whole run (total tokens over total seconds). |
| `fallbacks` | Count per fallback kind. |
| `source_rank` | `stats` of every expected document's `source_ranks` entry that is not `null`, plus `first` (how many were ranked first) and `not_retrieved` (how many were never retrieved). |
| `source_basis` | Count per `source_basis` over the in-corpus and direct questions (`not_observable` for `null`). |
| `manual_review` | `reviewed` (both reviewers gave a verdict), `pending`, `agreed_correct` (both said correct), `disagreements` (ids to discuss), `answer_correct_pct` = `agreed_correct / reviewed`. |
| `by_category` | The same rates, `source_rank` and `total_s` per category. |

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
