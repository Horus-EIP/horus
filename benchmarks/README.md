# Benchmarks

Measured results for the reference machines in the dev plan (§10), committed as JSON so before/after pairs can be compared in review.

| Reference | Machine |
|---|---|
| `cpu16` | 16 GB RAM, CPU only, AVX2. Record the CPU model, RAM speed and disk type. |
| `gpu8` | NVIDIA GPU with 8 GB of VRAM. |

Two kinds of file live here:

- **Evaluation runs** (`"kind": "horus-eval"`), written by `scripts/eval/run-eval.py` from the 100-question test set in `tests/eval/testset.yaml`.
- **llama-bench output** (`llama-bench ... -o json`), saved unchanged. llama-bench writes `build_commit` and `build_number` into every row itself.

Never edit a measured number by hand. Re-run instead.

## File names

`<label>-<YYYY-MM-DD>.json`, where the date is the UTC date the run started. A second run with the same label on the same day gets `-2`, `-3`, ... and never overwrites the first.

Put the reference machine and what changed into the label, e.g. `eval-cpu16-q4km-baseline`, `eval-cpu16-q4km-kv-q8`, `eval-gpu8-vllm`. Start llama-bench files with `llama-bench-` so the two kinds stay apart.

## Running an evaluation

The stack must be up, and the five files of `demo_assets/` must each be in the knowledge store exactly once. The runner checks this first and stops otherwise. Pass `--corpus-token` (the `CORPUS_SCAN_TOKEN` of `src/infra/.env`) to let it run `POST /corpus/scan` on the default `demo_assets` mount.

```bash
pip install httpx websockets pyyaml

python scripts/eval/run-eval.py --label eval-cpu16-q4km-baseline \
  --reference cpu16 --cpu-model "<cpu model>" --ram "<size>" --ram-speed "<speed>" --disk-type "<disk>" \
  --llama-cpp-build "<build number>" \
  --model-name qwen3-4b-instruct-2507-Q4_K_M --model-file qwen3-4b-instruct-2507-Q4_K_M.gguf \
  --model-sha256 "$(sha256sum qwen3-4b-instruct-2507-Q4_K_M.gguf | cut -d' ' -f1)" \
  --sample-resources
```

On the CPU stack the GGUF lives in the `llm_models` volume, not on the host. Its verified hash is in the volume next to it: from `src/infra`, `docker compose exec llm cat /models/qwen3-4b-instruct-2507-Q4_K_M.gguf.sha256`. The llama.cpp build number of the `llm` image is in `scripts/models/README.md`.

| Option | Meaning |
|---|---|
| `--mode chat` (default) | Every question goes through `POST /tasks/new_task/` in `auto` mode, one new conversation per question, and the answer is read from the chat WebSocket. If the socket drops, the runner polls `GET /tasks/{id}` until the task ends. |
| `--mode retrieval` | Only queries the knowledge store (`GET /?query=...&n_results=--top-k`) for the 84 in-corpus questions and scores the source by rank (see [Source checking](#source-checking)). No LLM, takes seconds. `--top-k` counts passages, not documents: the knowledge store returns chunks of at most 1,000 characters, and the five `demo_assets/` files make 22 of them. The passages are mapped to their documents, each ranked by its best passage. Keep `--top-k` (default 50) at least the number of stored passages so `source_ranks` shows where a missed document landed. |
| `--ids`, `--category`, `--limit` | Run part of the set (comma-separated). |
| `--event-timeout` | Seconds to wait for each final answer (default 1800). |
| `--submit-timeout` | Seconds for the `new_task` request itself, which stays open during routing (default 900). |
| `--no-warmup` | Skip the unscored warmup question that loads the model. The warmup question is fixed and not in the test set, so a response or prompt cache cannot make a scored answer faster. |
| `--sample-resources` | Sample `docker stats` and swap every `--sample-interval` seconds (default 10) and keep the peaks. |
| `--llama-cpp-build`, `--model-*` | Copied into the report as given. `--model-sha256` must be 64 hex characters. |
| `--reference`, `--cpu-model`, `--ram`, `--ram-speed`, `--disk-type` | Copied into `machine`. |
| `--resummarize FILE` | Recompute `summary` of an existing report after the reviewers filled in their verdicts. |

The report is rewritten after every question, so an interrupted run keeps what it measured (`run.completed` stays `false`).

## Evaluation report format

```json
{
  "kind": "horus-eval",
  "schema_version": 1,
  "label": "eval-cpu16-q4km-baseline",
  "run": {},
  "testset": {},
  "llama_cpp": {"build": "<build number>"},
  "model": {"name": "...", "file": "...gguf", "sha256": "64 hex characters"},
  "machine": {},
  "resources": {},
  "summary": {},
  "questions": []
}
```

`llama_cpp.build` and every `model` field are `null` when the option was not given (for example on the vLLM GPU path).

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

### `machine`

`reference`, `cpu_model` (defaults to what Python reports), `ram`, `ram_speed`, `disk_type`, `os`, `logical_cpus`, and `gpu` (`name`, `driver`, `memory_total` from `nvidia-smi`, or `null`).

### `resources`

`null` without `--sample-resources`. Otherwise `samples`, `container_peak_mem_bytes` (peak per container from `docker stats`), `containers_sum_peak_mem_bytes` (peak of the per-sample total) and `swap_peak_used_bytes` of the machine running the script (`null` when unknown). On Windows with Docker in WSL2, host swap is not the WSL VM's swap: read swap inside the VM instead.

### `questions[]`

One entry per question, in test set order.

| Field | Meaning |
|---|---|
| `id`, `category`, `difficulty`, `question`, `expected_answer` | Copied from the test set. |
| `expected_source` | List of document file names, or `null` for greetings, arithmetic and questions the corpus cannot answer. |
| `expected_route`, `observed_route` | `DIRECT_ANSWER` (MAS answered in the HTTP response), `AGENT` (a task was dispatched) or `NONE` (MAS replied with a message and no task). |
| `status` | `ok`, `error` or `timeout`. `error` holds the reason. `timeout` also covers a task stopped by the MAS `TASK_TIMEOUT` watchdog: its notice arrives as the answer over the WebSocket, or polling finds the task `canceled`. |
| `conversation_id`, `task_id`, `answered_by` | Where to look the run up in the UI or the database. |
| `timing_source` | `websocket`, `poll` (the socket dropped and the result came from `GET /tasks/{id}`, so `total_s` is accurate to `--poll-interval`) or `http`. |
| `submit_http_s` | Time until `POST /tasks/new_task/` returned (includes routing today). |
| `first_event_s`, `retrieval_s`, `reasoning_start_s` | Time to the first WebSocket event, the first `retrieval.results` step, the first `reasoning.start` step. |
| `ttft_s` | Time to the first `reasoning.delta` step, i.e. the first streamed token. `null` when token streaming is off (`AGENT_STREAM_TOKENS`) or the backend does not stream. |
| `total_s` | Time from submitting the question to the final answer. |
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
| `total_s`, `ttft_s` | `{"n", "mean", "median", "p90", "min", "max", "sum"}` over the questions that have the value. |
| `fallbacks` | Count per fallback kind. |
| `source_rank` | `stats` of every expected document's `source_ranks` entry that is not `null`, plus `first` (how many were ranked first) and `not_retrieved` (how many were never retrieved). |
| `source_basis` | Count per `source_basis` over the in-corpus and direct questions (`not_observable` for `null`). |
| `manual_review` | `reviewed` (both reviewers gave a verdict), `pending`, `agreed_correct` (both said correct), `disagreements` (ids to discuss), `answer_correct_pct` = `agreed_correct / reviewed`. |
| `by_category` | The same rates, `source_rank` and `total_s` per category. |

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
