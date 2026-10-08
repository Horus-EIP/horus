# File formats

This is the reference for every file that horus-bench-kit reads or writes. The README shows how to use the tools; this page says what each key means.

- [Conventions](#conventions)
- [Test set](#test-set)
- [Context files](#context-files)
- [Evaluation report](#evaluation-report): `horus-bench-kit-eval`, schema version 1
- [Scoring rules](#scoring-rules)
- [Extending the evaluation report](#extending-the-evaluation-report)
- [Checking JSON replies](#checking-json-replies)
- [Benchmark formats](#benchmark-formats): `horus-llama-bench`, `horus-model-candidates` and `horus-contract-probe`, schema version 1
- [Comparing benchmark files](#comparing-benchmark-files), and how a product registers its own kinds
- [Probe protocol v1](#probe-protocol-v1)
- [Report written](#report-written)

## Conventions

- **Kind and version.** Every report is a JSON object whose first two keys are `kind`, a string that names the format, and `schema_version`, an integer.
- **Compatibility.** A reader checks `kind`, refuses a `schema_version` higher than the one it knows, and reads every lower one. Adding a key does not change the version. Removing or renaming a key, or changing what it means, raises it.
- **Writing.** Reports are UTF-8 JSON, indented by two spaces, with non-ASCII characters kept as they are, keys in the order given on this page and a final newline. A report is first written to `<name>.json.part` and then renamed, so a reader never sees half a file. Line endings follow the platform: LF on Linux and macOS, CRLF on Windows.
- **File names.** `<label>-<YYYY-MM-DD>.json`. In the label, every run of characters other than `A-Z`, `a-z`, `0-9`, `.`, `_` and `-` becomes `-`. The date is the UTC date of the start of the run. An existing file is never overwritten: the next free name among `-2`, `-3` and so on is used.
- **Report written.** A tool that writes a report prints `[done] wrote <path>` when it succeeds, so a script that starts it can find the file. See [Report written](#report-written).
- **Units.** Durations are seconds, as numbers rounded to 3 decimals, unless the key ends in `_ms`. One exception: `run.duration_s` of a [`horus-llama-bench`](#horus-llama-bench) report is rounded to 1 decimal. Timestamps are UTC, `YYYY-MM-DDTHH:MM:SSZ`.
- **Digests.** SHA-256, 64 lowercase hexadecimal characters. Text files are hashed after replacing CRLF with LF, so a file has the same digest on Windows and Linux.

## Test set

A test set is one file: JSON when its name ends in `.json`, YAML otherwise (YAML needs the optional PyYAML). The examples in `examples/testset.json` and `examples/testset.yaml` are the same test set.

### Top level

| Key | Required | Meaning |
|---|---|---|
| `version` | yes | Version of the test set, such as `"1.0.0"`. Raise it whenever a question, a pattern or a document changes, so that reports of different versions are not compared by mistake. |
| `corpus_dir` | yes | Folder of the documents, relative to the test-set file. |
| `corpus` | yes | Object mapping each document file name to its SHA-256. |
| `items` | yes | List of questions, described below. |
| `non_answers` | no | Replies that must never count as a correct answer. Default: `"I don't know."` and `"I could not find that in the documents."`. |

Other top-level keys are ignored. A YAML test set can, for example, define a shared `refusal_patterns` list once with an anchor (`&refusal_patterns`) and reuse it in several items (`*refusal_patterns`). JSON has no anchors, so a JSON test set repeats the list.

### Items

| Key | Required | Meaning |
|---|---|---|
| `id` | yes | Unique id, a non-empty string. It also names the item's context file. |
| `question` | yes | The question, sent as it is. |
| `expected_answer` | yes | The right answer, for the reviewers. It must match its own `answer_patterns`. |
| `answer_patterns` | yes | Non-empty list of regular expressions in Python `re` syntax. An answer is correct when every one of them matches it. |
| `expected_source` | yes | File name of the document that holds the answer, a list of names when the answer needs several documents, or `null` for `not_in_corpus` and `direct` items. |
| `category` | yes | One of the categories below. |
| `difficulty` | yes | `easy`, `medium` or `hard`. |
| `evidence_patterns` | no | For `numeric` and `multi_hop` items whose answer is computed, so that it is not written in the documents: regular expressions that must be found in the expected documents instead of the answer patterns. |
| `absent_terms` | for `not_in_corpus` | Words that the question asks about and that no document contains. |
| `context_file` | no | Text file, relative to the test-set file, sent with the question. See [Context files](#context-files). |

### Categories

The order of this table is also the order of `by_category` in reports.

| Category | The answer... | `expected_source` | Expected route |
|---|---|---|---|
| `lookup` | is written in a document. | required | retrieval (`AGENT`) |
| `numeric` | is a number, read or computed from the documents. | required | retrieval (`AGENT`) |
| `multi_hop` | combines facts from several places. | required | retrieval (`AGENT`) |
| `not_in_corpus` | is not in the documents, and a correct answer says so. | `null`, with `absent_terms` | retrieval (`AGENT`) |
| `direct` | needs no document, such as arithmetic. | `null` | direct answer (`DIRECT_ANSWER`) |

### Validation

`hbk-eval validate` (and `hbk-eval run`, before it asks anything) runs these checks in order. Schema problems stop the check before the documents are read.

1. **Schema.** The four top-level keys are present, `corpus` maps file names to digests and `items` is a list of mappings: a test set of another shape is reported, never a crash. Every item has the required fields, a non-empty `id`, `question` and `expected_answer`, a known `category` and `difficulty`, and a non-empty `answer_patterns` list of valid regular expressions. `evidence_patterns` are valid and only on `numeric` and `multi_hop` items. `expected_source` is `null`, a file name or a list of file names. In-corpus items (`lookup`, `numeric`, `multi_hop`) have an `expected_source` and no `absent_terms`. `not_in_corpus` and `direct` items have `expected_source: null`, and `not_in_corpus` items have a non-empty `absent_terms` list. `non_answers` is a non-empty list of non-empty strings and `context_file` a non-empty string.
2. **Duplicates.** No two items share an `id`, or a `question` (ignoring case and surrounding spaces).
3. **Corpus.** Every declared document exists and still has its declared SHA-256, and every `expected_source` is declared. A changed document means its answers must be checked again before the digest is updated and the `version` raised.
4. **Grounding.** For each in-corpus item whose documents exist, every `evidence_patterns` entry, or every `answer_patterns` entry when there are none, matches the expected documents joined together.
5. **Absent terms.** No absent term appears in any document as a whole word, ignoring case.
6. **Self-consistency.** Every `expected_answer` passes its own patterns. Outside `not_in_corpus`, no non-answer passes them.
7. **Context files** (`hbk-eval` only). Every `context_file` exists.

## Context files

The `openai` target can send each question with plain text that stands for what a retriever would have found. For each item, `hbk-eval run` sends the item's `context_file` when it has one, otherwise `<context-dir>/<id>.txt` when that file exists, otherwise nothing. Several files are joined with a blank line. The user message is then:

```text
Context:
<the text of the files>

Question: <the question>
```

Without a context file, the user message is the question alone. Context beyond 200,000 characters is cut off.

With streaming on, a reply must arrive as `data:` lines (server-sent events). A server that ignores `"stream": true` and returns one JSON body gives the question the status `error` with a message that suggests `--no-stream`. A reply or a chunk of another shape than the OpenAI one is an `error` too. `--timeout` is how long the target waits for the server to accept the connection or to send more data, not a limit on the whole answer: a server that keeps streaming is never cut off.

## Evaluation report

`kind: "horus-bench-kit-eval"`, `schema_version: 1`. Written by `hbk-eval run` after every question and rebuilt by `hbk-eval resummarize`.

```json
{
  "kind": "horus-bench-kit-eval",
  "schema_version": 1,
  "label": "first-run",
  "run": {},
  "testset": {},
  "summary": {},
  "questions": []
}
```

`label` is the run label as given, before it is made safe for the file name.

### `run`

These keys are written by `hbk-eval run`. A runner of its own can record other keys here.

| Key | Meaning |
|---|---|
| `target` | `openai`. |
| `endpoint` | Scheme, host and port of `--base-url`, without its path, user name or password. |
| `model` | The `--model` value sent with each request. |
| `started_at` | When the run started. |
| `finished_at` | When the last question was answered; `null` until then, and for a run that stopped. |
| `completed` | `true` once every selected question was asked. |
| `kit_version` | Version of horus-bench-kit. |
| `warmup` | The warmup question, which is not scored, or `null`. |
| `settings` | `max_tokens`, `temperature`, `timeout_s`, `stream`, `stream_usage`, `system_prompt` (`default` or `file`), `system_prompt_sha256` (SHA-256 of the prompt text in UTF-8) and `context_files` (how many questions were sent with a context file). |
| `observed_models` | Model names that the server reported, in first-seen order. |

The API key is never recorded.

### `testset`

| Key | Meaning |
|---|---|
| `path` | File name of the test set, without its folder, so that a shared report names no local folder. A runner may instead record the path relative to a root folder of its choice. |
| `version` | The test set's `version`, as a string. |
| `sha256` | SHA-256 of the test-set file. |
| `corpus` | The test set's `corpus` object. |
| `items_total` | Number of items in the test set. |
| `items_run` | Number of items selected for this run. |
| `filters` | `ids`, `categories` and `limit`, the selection options; `null` when not used. |

### `questions[]`

One record per question, in the order asked. With the kit's default profile, a record has these 27 keys, in this order:

| Key | Meaning |
|---|---|
| `id`, `category`, `difficulty`, `question`, `expected_answer` | Copied from the item. |
| `expected_source` | List of the expected documents; `null` when there is none. |
| `expected_route` | `DIRECT_ANSWER` for `direct` items, `AGENT` (a retrieval step is expected) for the others. |
| `status` | `ok`, `error` or `timeout`. A product may add its own values. |
| `error` | What went wrong, or `null`. |
| `observed_route` | The route the target took, when it can tell (`DIRECT_ANSWER`, `AGENT` or `NONE`); `null` otherwise. The `openai` target cannot tell. |
| `models` | Model names reported for this answer. |
| `timing_source` | How the target observed the exchange. `http` and `websocket` mean it saw all of it. Any other value, such as `poll`, means that events may be missing, so a source that was not seen is not counted as wrong. |
| `ttft_s` | Time to first token: from sending the question to the first generated token, reasoning or answer. Streamed replies only; `null` otherwise. |
| `total_s` | From sending the question to the end of the answer. |
| `usage` | The server's `usage` object (`prompt_tokens`, `completion_tokens` and so on), or `null`. |
| `answer` | The answer text, or `null`. |
| `retrieval_steps` | How many retrievals the target ran; `null` when unknown. |
| `retrieved_sources` | One ranked list of document names per retrieval; `null` when unknown. |
| `cited_sources` | Document names that the answer cites; `null` when the target cannot tell. |
| `fallback` | Name of the fallback marker found in the answer, or `null`. See [Fallbacks](#fallbacks). |
| `answer_correct_auto` | `true` when every answer pattern matches the answer. `false` for a blank answer, a fallback or a failed question. `null` in retrieval mode. |
| `missing_patterns` | The answer patterns that did not match; `null` in retrieval mode. |
| `source_basis` | `cited` when the source is scored on `cited_sources`, `retrieval` when on retrievals, `null` when not scored. |
| `source_ranks` | For each expected document, its best rank over every retrieval (1 is first), or `null` when it was never retrieved. `null` when the source is not scored on retrievals. |
| `source_correct_auto` | See [Sources](#sources); `null` when not scored. |
| `route_correct` | Whether `observed_route` is `expected_route`; `null` when the route is unknown, and in retrieval mode. |
| `review` | Two `{"reviewer", "answer_correct", "comment"}` slots for the [manual review](#manual-review), all `null` at first; `null` in retrieval mode. |

An outcome with `"mode": "retrieval"` comes from a target that retrieves documents without answering: only its sources are scored.

### `summary`

| Key | Meaning |
|---|---|
| `questions` | Number of records. |
| `answer_correct_auto` | Rate. |
| `source_correct_auto` | Rate. |
| `source_rank` | Stats of every known rank, plus `first` (ranks equal to 1) and `not_retrieved` (expected documents never retrieved). |
| `route_correct` | Rate. |
| `total_s` | Stats. |
| `status` | Count per status, in first-seen order. |
| `fallbacks` | Count per fallback name, in first-seen order. |
| `source_basis` | Count per `source_basis` over the items outside `not_in_corpus`, with `not_observable` for the ones not scored. |
| `ttft_s` | Stats. |
| `usage` | `questions` (records with a usage object), and stats of `prompt_tokens` and `completion_tokens`; `null` when no record has usage. |
| `manual_review` | `reviewed` (both slots filled), `pending` (answers not yet reviewed by both), `agreed_correct` (both said correct), `disagreements` (ids where the reviewers differ) and `answer_correct_pct` (`agreed_correct` over `reviewed`, one decimal, `null` when nothing is reviewed). |
| `by_category` | For each category present, in category order: `questions`, `answer_correct_auto`, `source_correct_auto`, `source_rank`, `route_correct` and `total_s`, computed as above. |

A **rate** is `{"n", "correct", "pct"}` over the values that are not `null`. `pct` has one decimal and is `null` when `n` is 0.

**Stats** are `{"n": 0}` when there is no value, and otherwise `{"n", "mean", "median", "p90", "min", "max", "sum"}` rounded to 3 decimals. `p90` is the value at index `min(int(n × 0.9), n − 1)` of the sorted values.

### Manual review

Two reviewers fill the `review` slots of each answered question with their name, `true` or `false`, and an optional comment. `hbk-eval resummarize REPORT` then rebuilds the summary in place and prints `manual_review`.

## Scoring rules

### Answers

Before matching, the answer is normalised: Unicode NFKC (so full-width characters become their ASCII form), curly quotes become straight quotes, the ideographic full stop `。` becomes `.`, no-break spaces become spaces, and the Markdown emphasis markers `**`, `__` and `` ` `` are removed. Patterns then match anywhere in the answer, ignoring case. A blank answer is never correct.

### Sources

Documents are compared by file name without extension, ignoring case and any folder. The first rule that applies decides:

1. `not_in_corpus` items are not scored.
2. `direct` items are correct when nothing was retrieved and nothing was cited, and wrong when a retrieval ran or a document was cited. They are not scored when the number of retrievals is unknown, or when nothing was seen but events may be missing.
3. When the target reports `cited_sources`, the item is correct when every expected document is cited.
4. When it reports neither citations nor retrievals, the item is not scored.
5. Otherwise each expected document gets its best rank over every retrieval, counting each document once. The item is correct when every expected document ranks within the top N, N being the number of expected documents: first for one document, top two for two. Otherwise it is wrong, or not scored when events may be missing.

Being returned somewhere is not enough: a deep enough retrieval returns every document.

### Routes

`direct` items expect a direct answer (`DIRECT_ANSWER`); every other item expects a retrieval step (`AGENT`). The route is scored only when the target reports the route it took.

### Fallbacks

A system can answer with a canned text when it fails, such as "the model took too long". A product lists these texts as fallback markers in its profile: a name and a lower-case text found anywhere in the normalised, lower-cased answer. The first marker found, in the profile's order, names the fallback. An answer with a fallback is never correct, even when its patterns match. The kit's own report has no markers.

## Extending the evaluation report

A product that evaluates its own system can keep the engine and add what it measures, under its own `kind`. The report keeps the core keys in their places, so `resummarize` and `compare` keep working. Pass a `Profile` (from `horus_bench_kit.report`) to `question_record`, `build_summary`, `build_report` and `resummarize`:

| Profile field | Default | Meaning |
|---|---|---|
| `kind`, `schema_version` | `horus-bench-kit-eval`, `1` | Written by `build_report` and checked by `resummarize`. |
| `fallback_markers` | none | Name to lower-case text, as in [Fallbacks](#fallbacks). |
| `final_status` | keep | Function `(status, error, answer)` returning `(status, error)`, applied before scoring, for example to turn a watchdog message into a `timeout`. |
| `outcome_fields` | `observed_route`, `models`, `timing_source`, `ttft_s`, `total_s`, `usage` | Outcome keys copied into each record, in this order, between `error` and `answer`. |
| `list_fields` | `models`, `devices` | Outcome fields copied as lists, `[]` when missing. |
| `summary_sections` | `usage` | `(key, function(records))` pairs whose results go into the summary, in this order, between `ttft_s` and `manual_review`. |
| `categories` | the five categories | Order of `by_category`. |

`build_report(..., sections={...})` places top-level sections, such as a `model` or `machine` object, between `testset` and `summary`.

For example, a product whose target also reports a queueing time and the machine it ran on could use:

```python
from horus_bench_kit.report import OUTCOME_FIELDS, Profile, build_report, field_stats

PROFILE = Profile(
    kind="acme-eval",
    schema_version=1,
    fallback_markers={"timeout": "took too long to answer"},
    outcome_fields=("queue_s", *OUTCOME_FIELDS),
    summary_sections=(("queue_s", field_stats("queue_s")),),
)
report = build_report(label="run", run=run, testset=testset, records=records,
                      sections={"machine": machine}, profile=PROFILE)
```

`hbk-eval compare` reads any JSON report whose `questions` records hold at least `id` and `category`. It recomputes the core summary from the records and ignores the keys it does not know. It checks `schema_version` only for its own kind. `hbk-eval resummarize` only rewrites `horus-bench-kit-eval` reports; a product calls `resummarize(report, PROFILE)` itself.

## Checking JSON replies

`horus_bench_kit.contract` checks a model's JSON reply against the JSON schema that the request asked for. It supports a subset of JSON Schema: `type` (including a list of types), `enum`, `const`, `properties`, `required`, `additionalProperties` (`true`, `false` or a schema), `items` (one schema), `minItems`, `maxItems`, `minLength` and `maxLength`, and the boolean schemas `true` (anything) and `false` (nothing). It ignores the annotations `title`, `description`, `$schema`, `default` and `examples`. A schema with any other keyword, or a supported keyword with a value of the wrong type (for example `"minLength": "3"` or `items` as a list), makes the reply invalid instead of silently unchecked: the violation says `the checker does not support ...`. Booleans are never integers, and `1` equals `1.0`.

Each violation is one line that starts with the JSON path, such as `$.verdict: 'maybe' is not one of ['supported', 'refuted', 'unknown']`.

`check_reply(reply)` classifies a reply dict holding `content`, `finish_reason`, `schema` and, when the request failed, `error`. The parse is strict: no code fences and no text around the JSON other than whitespace.

| Failure | Meaning |
|---|---|
| `request_error` | The request failed. |
| `empty` | Blank content. |
| `truncated` | Blank or unparsable content, and `finish_reason` is `length`. |
| `not_json` | The content is not JSON. |
| `not_object` | The JSON is not an object. |
| `no_schema` | The reply carries no schema to check against. |
| `schema` | The object breaks the schema. |
| `null` | Valid. |

## Benchmark formats

The benchmark tools write three kinds of report. Their kind strings keep the `horus-` prefix, the kit's namespace, so files written before the kit existed still read.

| Kind | Version | Written by | Read by |
|---|---|---|---|
| `horus-llama-bench` | 1 | `hbk-llama-bench` | `hbk-compare`, `hbk-model-candidates` |
| `horus-contract-probe` | 1 | `hbk-contract-probe`, the probe step of `hbk-model-candidates` | `hbk-model-candidates` |
| `horus-model-candidates` | 1 | `hbk-model-candidates`, with a Markdown twin | `hbk-model-candidates --resume` and `--resummarize` |

### Machine

`hbk-llama-bench` and `hbk-model-candidates` describe the machine they ran on in a `machine` object, with these keys in this order:

| Key | Meaning |
|---|---|
| `reference` | The `--reference` name of the machine, or `null`. |
| `cpu_model`, `physical_cores`, `logical_cpus`, `avx2` | Processor facts. |
| `ram` | Readable summary, such as `16 GiB installed, 15.4 GiB usable`. |
| `ram_total_bytes`, `ram_installed_bytes`, `ram_modules`, `ram_type`, `ram_speed` | Memory facts. |
| `disk_type`, `disk_model` | The disk that holds the models: `NVMe SSD`, `SATA SSD`, `HDD` and so on. |
| `os` | Python's `platform.platform()`. |
| `docker` | `mem_total_bytes`, `cpus`, `operating_system`, `kernel`, `server_version`, `cgroup_version` and `root_dir` from `docker info`, or `null` when Docker does not answer. |
| `sources` | For each fact, where it was read (`/proc/cpuinfo`, `dmidecode`, `Win32_PhysicalMemory`, `sysctl` and so on), or `given` when an option set it. |

Facts are read from `/proc` and `dmidecode` on Linux, CIM queries on Windows and `sysctl` and `system_profiler` on macOS. A fact that cannot be read is `null`, and the tool says which option sets it by hand: `--cpu-model`, `--ram`, `--ram-speed` or `--disk-type`.

### `horus-llama-bench`

`kind: "horus-llama-bench"`, `schema_version: 1`. Top-level keys in this order: `kind`, `schema_version`, `label`, `run`, `llama_cpp`, `models`, `machine`, `summary`, `results`.

| Key | Meaning |
|---|---|
| `label` | The run label, already made safe for the file name. |
| `run` | `started_at`, `finished_at`, `duration_s`, `git_commit` (short commit of the folder the tool ran in, or `null`), `from_json` (file name of a saved raw run that was enriched, or `null`), `models_location` (`dir`: `<models-dir>` when a host folder was used, otherwise `null`; `volume`: the Docker volume name or `null`), `command` (the `docker run` command, with the host folder replaced by `<models-dir>`; `null` for an enriched saved run) and `matrix` (`prompts`, `generations`, `depths`, `cache_types_k`, `cache_types_v`, `threads`, `repetitions`). |
| `llama_cpp` | `image`, `image_digest` (the repo digest of the local image, or `null`), `build` (`b` and the build number), `build_number`, `build_commit`, and `image_tag_matches` (whether the build in the image tag is the build that ran). |
| `models` | One object per model: `file`, `size_bytes`, `sha256` (measured in the container), `known_source` (download URL from the known models, or `null`) and `matches_known_sha256` (`null` when the model is not known or its digest was not measured). |
| `summary` | A **list** with one row per result: `model`, `model_type`, `test` (`pp512`, `tg128`, `pp512+tg128`), `n_depth`, `type_k`, `type_v`, `n_threads`, `flash_attn`, `avg_ts` and `stddev_ts` (tokens per second, 2 decimals). |
| `results` | The rows of `llama-bench -o json`, unchanged. |

No host folder is written into this report: the models folder appears only as `<models-dir>`.

`hbk-compare` also reads a bare `llama-bench -o json` array saved to a file. It takes the file name, without `.json`, as its label.

### Known models

`hbk-llama-bench --known-models FILE` gives the download URL, size and SHA-256 of the models it may fetch and check. The file is JSON (or YAML with PyYAML):

```json
{
  "models": [
    {"file": "model-Q4_K_M.gguf", "url": "https://...", "size_bytes": 2497281120, "sha256": "<64 hex>"}
  ]
}
```

`file` is a bare `.gguf` name, `url` an `https://` or `http://` address, `size_bytes` a positive whole number and `sha256` 64 lower-case hexadecimal characters. A [model catalog](#model-catalog) can be given instead: every GGUF it lists becomes a known model. `examples/known-models.json` holds one model.

`--fetch` runs the kit's `fetch-model.sh` in the llama.cpp server image, mounted at `/opt/hbk/fetch-model.sh`. It downloads to `<name>.part` with resume and retries, checks the size and the SHA-256, then moves the file in place and writes `<name>.sha256` next to it, so a later run skips a file it already verified. The kit passes it `LLM_GGUF_FILE`, `LLM_GGUF_URL`, `LLM_GGUF_SHA256` and `LLM_GGUF_SIZE`, and `HF_TOKEN` from your environment for gated models.

### Model catalog

The input of `hbk-model-candidates`, JSON or YAML. `examples/catalog.yaml` and `examples/catalog.json` hold the same catalog.

| Key | Meaning |
|---|---|
| `version` | Version of the catalog. |
| `looked_up` | Date the facts were checked. |
| `llama_cpp` | `pinned_build` (such as `b11382`), `server_image` and `bench_image`. Both images must be tagged with the pinned build. |
| `licences_allowed` | Licence names a model may have; any other licence is skipped. |
| `llama_bench` | The llama-bench matrix used for every model: `prompts`, `generations`, `depths`, `cache_types_k`, `cache_types_v`, `threads`, `repetitions`. The first KV cache type is the one the summary shows. |
| `candidates` | The models, described below. The ids of candidates and GGUFs, and the GGUF file names, must be unique, and one candidate has the role `baseline`. |

Each candidate has `id`, `role` (`baseline` or `candidate`), `name` (older catalogs may say `plan_name`; a product can require its own key through `CandidatesProfile.name_key`), `model_repo` and `model_revision` (a 40-character commit), `licence`, `licence_statement` (where the licence was read), `licence_flags` (sentences that call for a closer look; may be empty), `architecture`, `gguf_architecture`, `llama_cpp` (`since_build`: the first llama.cpp build that runs it, or `null`; `since_pr`; `evidence`), `parameters`, `active_parameters` (or `null`), `size_note`, `context_length`, `thinking_default` (`on`, `off` or `none`), `thinking_evidence`, `notes` and `ggufs`.

Each GGUF has `id`, `file` (the name it is saved under), `quant`, `repo`, `revision` (a 40-character commit), `upstream_file`, `publisher`, `size_bytes`, `sha256` and `default` (`true` for the files run without `--all-quants`; every candidate needs one). It is downloaded from `https://huggingface.co/<repo>/resolve/<revision>/<upstream_file>`.

A model whose licence is not allowed, or that needs a llama.cpp build newer than the pinned one, is skipped with a `skipped:` problem.

### `horus-model-candidates`

`kind: "horus-model-candidates"`, `schema_version: 1`, `label: "model-candidates"`. The summary is `<out-dir>/model-candidates-<date>.json` with a Markdown twin `.md`; the reports of each step go to the folder of the same name without `.json`. The summary is rewritten after every step, so an interrupted run keeps what it did.

Top-level keys in this order: `kind`, `schema_version`, `label`, `catalog`, `run`, `machine`, `variants`.

| Key | Meaning |
|---|---|
| `catalog` | `path` (file name, or the path below a root folder a product chooses), `version`, `sha256`, `looked_up` and `pinned_build`. |
| `run` | `started_at` (of the first session), `finished_at`, `completed`, `git_commit`, `steps` (every step run in any session, in the order `fetch`, `bench`, `probe`, `eval`), `reasoning` (of the last session that served models), `stack_llm` (the inspected container whose arguments the candidates reuse, when a product serves them that way; `null` otherwise), `testset` and `sessions`. |
| `run.sessions[]` | One per run or `--resume`: `started_at`, `finished_at`, `completed`, `git_commit`, `steps`, `reasoning`, `only`, `all_quants`, `models_dir` (always `<models-dir>`), `server_image`, `llm_mem_limit_bytes` and `testset`. |
| `run.testset` | `path`, `version`, `sha256`, `filters` (`ids`, `categories`, `limit`) and `probe_items`; `null` without a test set. |
| `machine` | See [Machine](#machine). |
| `variants` | One per GGUF, described below. |

Each variant holds, in this order: `id`, `candidate`, `role`, `name`, `model_repo`, `licence`, `licence_flags`, `gguf_architecture`, `thinking_default`, `quant`, `file`, `gguf_repo`, `revision`, `publisher`, `size_bytes`, `sha256`, then:

| Key | Meaning |
|---|---|
| `fetch` | `status` (`verified` or `failed`), `method` and `path` (`<models-dir>/<file>`) or `error`; `null` when the fetch step did not run. |
| `reports` | `llama_bench`, `contract` and `eval`: paths of the step reports relative to the summary's folder, or `null`. |
| `llama_bench` | `build`, `speeds` (for the catalog's first KV cache type, the best thread count of each test and depth: `test`, `depth`, `tps`, `stddev`, `threads`), `model_sha256` and `sha256_matches_catalog`; `null` without a benchmark. |
| `contract` | Keys copied from the contract report's summary: `replies`, `json_valid`, `failures`, `thought_first`, `truncated`, `expected_correct`, `patterns_correct`, `wall_s`, `completion_tokens`, `prompt_tps`, `generation_tps`. A product can choose other keys. |
| `eval` | From the evaluation report: `completed`, `questions`, `status`, `answer_correct_auto`, `answer_correct_reviewed_pct`, `review_pending`, `source_correct_auto`, `route_correct`, `fallbacks`, `total_s`, `ttft_s`. A product can add its own. |
| `server` | `container`, `image`, `command` (with `<models-dir>`), `memory_limit_bytes`, `reasoning`, and from llama-server's `/props`: `build_info`, `build`, `n_ctx`, `model_path`. |
| `memory` | `after_probe` and `after_eval` snapshots: `taken_at`, `process` (`name`, `vm_hwm_bytes`, `vm_rss_bytes`, `rss_anon_bytes`, `rss_file_bytes` of the server process), `cgroup_peak_bytes`, `oom_kills`, `oom_killed`, `restart_count`. |
| `problems` | Sentences about what went wrong for this model. |

`--resummarize` rebuilds every variant from the step reports, for example after the manual review of an evaluation, and keeps the rest of the summary.

### `horus-contract-probe`

`kind: "horus-contract-probe"`, `schema_version: 1`. Top-level keys in this order: `kind`, `schema_version`, `label`, `run`, `model`, `llama_server`, `summary`, `replies`.

| Key | Meaning |
|---|---|
| `run` | From `hbk-contract-probe`: `mode` (`template`, `prepared` or `command`), `started_at`, `finished_at`, `completed` (every item got a reply and the probe exited with 0), `endpoint` (scheme, host and port only), `kit_version`, `warmup`, `items`, and `settings`: the request settings and the SHA-256 of the prompt, template and schema files in template mode, of the request file in prepared mode, or the protocol version in command mode. From `hbk-model-candidates`: `mode`, `started_at`, `finished_at`, `completed`, `warmup` and `items`. |
| `model` | `name` from `hbk-contract-probe`; `id`, `file` and `sha256` from `hbk-model-candidates`. |
| `llama_server` | The `server` object of [`horus-model-candidates`](#horus-model-candidates), or `null`. |
| `replies` | One record per item that got a reply, in item order. |

Each record holds, in this order: `id`, `category`, `question`, `expected`, `json_valid`, `failure`, `violations`, `expected_correct`, `patterns_correct`, `missing_patterns`, `error`, `finish_reason`, `thought_first`, `labels`, `retrieved_titles`, `wall_s`, `prompt_tokens`, `completion_tokens`, `cached_tokens`, `prompt_n`, `prompt_ms`, `predicted_n`, `predicted_ms`, `prompt_tps`, `generation_tps`, `content`, `reasoning_chars`.

| Key | Meaning |
|---|---|
| `json_valid`, `failure`, `violations` | The [JSON reply check](#checking-json-replies) against the schema the request asked for. `json_valid` is `null` and `failure` is `retrieval_error` when the probe could not prepare the request. |
| `expected_correct` | Every field of the item's `expected` object has that exact value in the reply; `null` when the item has no `expected`. |
| `patterns_correct`, `missing_patterns` | Every regular expression of the item's `patterns` matches its field (normalised as answers are); the ones that did not, by field. `null` when the item has no `patterns`. |
| `thought_first` | The reply has `reasoning_content`, or its content starts with `<think`. |
| `labels`, `retrieved_titles` | Passed through from the reply line. |
| `wall_s` | Time of the request. |
| `prompt_tokens`, `completion_tokens` | The server's `usage`. |
| `cached_tokens`, `prompt_n`, `prompt_ms`, `predicted_n`, `predicted_ms`, `prompt_tps`, `generation_tps` | llama-server's `timings`, `null` from other servers. |
| `content`, `reasoning_chars` | The raw reply and the length of its reasoning. |

`summary` holds `replies`, the rates `json_valid`, `expected_correct` and `patterns_correct`, `failures` (count per failure, first-seen order), `thought_first`, `truncated` (finish reason `length`), the stats `wall_s`, `prompt_tokens` and `completion_tokens`, `prompt_tps` and `generation_tps` (tokens over time, summed over the records that report both), and `by_category` (`replies` and the rates for each category, in first-seen order).

A product that scores other fields passes a `ContractProfile` (from `horus_bench_kit.probe`): its own `kind` and `schema_version`, a `head` function for the keys after `question`, a `scores` function for the scoring keys, the `rate_fields` of the summary, extra summary `counts`, and a fixed `categories` order. The record keys from `error` on and the summary keys outside the rates stay the same.

### Probe items

`hbk-contract-probe --items` and `hbk-model-candidates --probe-items` read a JSON file (a list, or an object with an `items` list), a JSON Lines file (`.jsonl`) or a YAML file. Each item has:

| Key | Required | Meaning |
|---|---|---|
| `id` | yes | Unique id. It also names the item's context file in `--context-dir`. |
| `question` | yes | Fills `{question}` in the user template. |
| `category` | no | Groups the summary. |
| `context` | no | Text for `{context}`. |
| `context_file` | no | File, relative to the item file, read into `{context}` when there is no `context`. |
| `expected` | no | Object of field values the JSON reply must hold. |
| `patterns` | no | Object of field names to lists of regular expressions the field must match. |

Without `context` or `context_file`, `<context-dir>/<id>.txt` is used when it exists, otherwise `{context}` is empty. The user template is filled in one pass, so braces in the context or the question stay as they are. `examples/probe/` holds a system prompt, a user template, a `{verdict, reason}` schema and eight items.

In prepared mode, `--prepared` is a JSON Lines file with one request per line: `id`, `payload` (a full chat completion request, sent as it is to `<base-url>/chat/completions`; `--model` replaces its `model`), and optionally `question`, `category`, `expected`, `patterns`, and `meta` with `labels`, `sources_by_label` and `retrieved_titles` copied into the reply. The schema to check against comes from `payload.response_format`.

A response format may be OpenAI's nested form, `{"type": "json_schema", "json_schema": {"name", "strict", "schema"}}`, or llama-server's flat form, `{"type": "json_schema", "schema": {...}}`. Both are sent unchanged and both are checked.

## Comparing benchmark files

`hbk-compare` turns one side, or two sides `before` and `after`, into a Markdown table. Each side holds at most one llama-bench file (`horus-llama-bench` or a raw array) and one end-to-end file: by default a `horus-bench-kit-eval` report. Files of any other kind are refused, and so is a file whose `schema_version` is newer than the one the kit reads.

The header rows name the files, labels, start times, machine, RAM, Docker memory, disk, llama.cpp build, models and their SHA-256, test set and which llama-bench rows are shown. The metrics table shows, for the chosen model, KV cache type (`--kv`, default `f16`) and thread count (`--threads`, default the fastest), the six llama-bench headline tests (`pp512`, `pp2048` and `tg128`, at depth 0 and 4096), then the evaluation rows: questions, time to first token and total time (median, p90 and the whole run), reviewed and automatic answer rates, source rate and fallbacks. With two sides a `Change` column follows; totals over different question counts are marked as not comparable. A second table lists every llama-bench configuration, and `notes` of any file are listed at the end. Warnings name unfinished runs, pending reviews, different test sets, different machines and a changed KV cache.

### Registering a product's kinds

A product that writes its own end-to-end reports registers them with a `CompareProfile` (from `horus_bench_kit.compare`), and calls `compare_markdown(before, after, selection, profile)` or `horus_bench_kit.cli.compare.main(argv, profile=profile)`.

| Field | Meaning |
|---|---|
| `rows` | The `MetricRow` list of the metrics table: `key`, `label`, `how` (how it is measured), `unit` (`t/s`, `s`, `ms`, `GiB`, `%`, `count`, `text` and so on) and `is_total`. Start from `LLAMA_BENCH_ROWS` to keep the llama-bench rows. |
| `families` | One `Family` per end-to-end kind: `kind`, the newest `schema_version` read, `metrics` (document to a dict of row key to `Metric(value, n, note)`), and optionally `warnings` (document to sentences), `build`, `started` and `model` (what the header shows for that document). |
| `heading` | Title of the metrics table. |
| `headline_tests` | The llama-bench `(test, depth)` pairs shown. |

A metric keyed `kv_cache` with a text value turns on the KV cache warning. Helpers for metric functions are `stat_metric`, `rate_metric`, `count_total`, `container_total`, `gib` and `methods_text`.

```python
from horus_bench_kit.compare import LLAMA_BENCH_ROWS, CompareProfile, Family, stat_metric
from horus_bench_kit.markdown import MetricRow

PROFILE = CompareProfile(
    rows=(*LLAMA_BENCH_ROWS, MetricRow("queue_median_s", "Queue time, median", "scheduler", "s")),
    families=(Family("acme-eval", 1, lambda doc: {"queue_median_s": stat_metric(doc["summary"], "queue_s", "median")}),),
    heading="## Acme metrics",
)
```

## Probe protocol v1

`hbk-contract-probe --probe-command` and `hbk-model-candidates --probe-command` hand the probe to another program. Use it when a product builds its requests in a way a template cannot reproduce, for example with live retrieval: the program builds and sends the requests, and the kit only checks and scores the replies. `examples/probe/command_probe.py` is a complete probe of this kind, with the standard library only.

The command is split like a POSIX shell command (quote Windows paths), or given as a JSON list of strings. `--probe-setup` runs once before it, for example to copy the probe into a container; when the setup fails, nothing is probed.

**The job.** The kit writes one JSON object to the command's standard input, then closes it:

| Key | Meaning |
|---|---|
| `items` | List of `{"id", "question"}` objects, with `context` when the item has some. |
| `warmup` | A question to ask first and not report, or `null`. |
| `endpoint` | The OpenAI-compatible API root the probe should call, when the kit knows it. Optional. |

**The replies.** The probe writes one JSON object per line on standard output for each item it handled, in any order. A line that is not a JSON object with an `id` is ignored, so progress belongs on standard error. When two lines carry the same `id`, the last one wins.

| Key | Meaning |
|---|---|
| `id` | The item's id. Required. |
| `schema` | The JSON schema the request asked for; the reply is checked against it. Without it the failure is `no_schema`. |
| `content`, `reasoning_content`, `finish_reason` | From the first choice of the chat completion. |
| `usage`, `timings` | The server's `usage` and, from llama-server, `timings`. |
| `wall_s` | Seconds the request took. |
| `max_tokens` | The limit that was sent. |
| `labels`, `sources_by_label`, `retrieved_titles` | Optional facts about what the probe put in the prompt; `labels` and `retrieved_titles` are copied into the record. |
| `error_stage`, `error` | When the item failed: `retrieval` when the request could not be prepared, `llm` when the request failed; `error` says why. |

An item without a reply line is left out of the report, and the run is not `completed`. A non-zero exit code also leaves the run not `completed`, but the replies read are kept.

## Report written

Every tool that writes a report prints `[done] wrote <path>` when it succeeds. `hbk-eval run` also prints `writing <path>` when it starts asking the questions, after a `--warmup` succeeded, so a run that stopped still points to its partial report; a run whose warmup failed writes nothing and prints no path. A program that starts a tool takes the path from the last line that holds `[done] wrote <path>` or `writing <path>`: `hbk-model-candidates` finds the reports of its llama-bench and evaluation steps that way, which is how a product's own tools can take their place.
