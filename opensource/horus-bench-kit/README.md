# horus-bench-kit

[![CI](https://github.com/Horus-EIP/horus-bench-kit/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/Horus-EIP/horus-bench-kit/actions/workflows/ci.yml)

Tools to measure language models that you run yourself. The kit's home is [github.com/Horus-EIP/horus-bench-kit](https://github.com/Horus-EIP/horus-bench-kit).

- **Evaluation** (`hbk-eval`): write a small question-answering test set over your own documents, check it, ask every question to a model behind any OpenAI-compatible chat endpoint (llama.cpp's `llama-server`, vLLM, Ollama, LM Studio and others), score the answers and the cited sources, then review and compare the runs.
- **Benchmarks**: check that a model's JSON answers fit a schema (`hbk-contract-probe`), run llama-bench in Docker with the facts of the machine and the SHA-256 of every model (`hbk-llama-bench`), compare runs as Markdown (`hbk-compare`), and take a catalog of GGUF models through download, benchmark, probe and evaluation (`hbk-model-candidates`). See [Benchmark tools](#benchmark-tools).

The kit needs only the Python standard library. Every result is a plain JSON file whose format is documented in [docs/FORMATS.md](docs/FORMATS.md), so other tools can read it. The `horus-` prefix in the package name and in the report kinds is the kit's namespace.

## Install

Python 3.10 or later.

```sh
git clone https://github.com/Horus-EIP/horus-bench-kit.git
cd horus-bench-kit
python -m venv .venv
. .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install .                   # from this folder
pip install ".[yaml]"           # optional: read test sets written in YAML
```

JSON test sets work without any extra package. Each tool also runs as a module, for example `python -m horus_bench_kit.cli.eval`: the modules are `cli.eval`, `cli.llama_bench`, `cli.compare`, `cli.candidates` and `cli.contract_probe`. Every tool takes `--help`, and `--version` prints the kit's version.

`hbk-llama-bench` and `hbk-model-candidates` also need Docker (Engine on Linux, or Docker Desktop) to run llama.cpp; the other tools do not.

## Quick start: evaluate a model

The `examples/` folder holds a test set of nine questions about a fictional community garden, its three documents (`examples/corpus/`) and one context file per question (`examples/context/`).

1. Check the test set against its documents:

   ```sh
   hbk-eval validate examples/testset.json
   ```

2. Start any OpenAI-compatible server. With llama.cpp:

   ```sh
   llama-server -m your-model.gguf --port 8080
   ```

3. Ask every question and write a report:

   ```sh
   hbk-eval run --base-url http://127.0.0.1:8080/v1 --model local \
     --testset examples/testset.json --context-dir examples/context \
     --label first-run --out-dir results
   ```

   Each question is sent with the text of its context file, if it has one, and the reply is streamed to measure the time to first token. The report is saved after every question as `results/first-run-<date>.json` (`-2`, `-3` and so on when that name is taken), and one line per question shows its status, time and scores.

4. Read the result as Markdown, or compare two runs:

   ```sh
   hbk-eval compare results/first-run-<date>.json
   hbk-eval compare results/small-model-<date>.json results/large-model-<date>.json --out results/comparison.md
   ```

### Options of `hbk-eval run`

| Option | Default | Meaning |
|---|---|---|
| `--target` | `openai` | the system asked; `openai` is the only built-in target (any OpenAI-compatible chat endpoint) |
| `--base-url` | required | API root, for example `http://127.0.0.1:8080/v1`; requests go to `<base-url>/chat/completions` |
| `--model` | required | model name sent with each request |
| `--testset` | required | test set, `.json` or `.yaml` |
| `--label` | required | run label, used in the report file name |
| `--out-dir` | `.` | folder for the report |
| `--context-dir` | none | folder of `<question id>.txt` context files; an item's own `context_file` wins |
| `--ids`, `--category`, `--limit` | all | run part of the test set, for example `--category lookup,numeric --limit 5` |
| `--system-prompt-file` | built-in prompt | plain-text system prompt |
| `--max-tokens`, `--temperature`, `--timeout` | 512, 0, 600 s | request settings; the timeout is how long to wait for the server to connect or to send more data, so a reply that keeps streaming is never cut off |
| `--api-key-env` | `OPENAI_API_KEY` | environment variable that holds the API key, if the server needs one. The key is never written to the report |
| `--no-stream` | streaming on | wait for whole replies; the time to first token is then not measured |
| `--no-stream-usage` | sent | leave out `stream_options.include_usage` for servers that refuse it |
| `--warmup QUESTION` | none | ask this question first and do not score it, so the model is loaded before the timings start |

Exit codes: `0` when the run finished; `1` when the warmup failed (nothing is written) or no question got an answer (the report is kept, with the errors); `2` for bad options or a test set that does not validate.

### Review the answers by hand

Patterns catch most right and wrong answers, not all of them. Each answered question has two empty `review` slots in the report. Two reviewers fill them in:

```json
"review": [
  {"reviewer": "ana", "answer_correct": true, "comment": null},
  {"reviewer": "ben", "answer_correct": false, "comment": "gives the weekend time"}
]
```

Then rebuild the summary:

```sh
hbk-eval resummarize results/first-run-<date>.json
```

The reviewed rate counts the answers that both reviewers marked correct, over the answers that both reviewed.

## Write your own test set

A test set is one JSON or YAML file next to a folder of plain-text documents. Each item gives a question, the expected answer for people, regular expressions that a correct answer must all match, and the document that holds the answer. `hbk-eval validate` checks that:

- every document is unchanged since you wrote the answers (SHA-256 per file);
- each answer pattern matches its own expected answer and can be found in the expected document;
- patterns do not also accept a non-answer such as "I don't know.";
- the terms that a question about a missing topic names really are absent from every document.

The full format, with every field and rule, is in [docs/FORMATS.md](docs/FORMATS.md#test-set). Start from `examples/testset.yaml` or `examples/testset.json`.

## Use the kit from Python

Any system that answers questions can be evaluated: write a target with a `name` and an `ask` coroutine that returns an outcome, then let the kit run the items and build the report.

```python
import asyncio

from horus_bench_kit.report import build_report, question_record
from horus_bench_kit.target import run_items
from horus_bench_kit.testset import load_testset


class MyTarget:
    name = "my-system"

    async def ask(self, question, *, item_id, files=()):
        answer = ...  # call your system here
        return {"mode": "chat", "status": "ok", "answer": answer, "timing_source": "http", "total_s": 1.2}


testset = load_testset("examples/testset.json")
records = asyncio.run(run_items(MyTarget(), testset["items"], record=question_record))
report = build_report(label="my-run", run={"target": "my-system"}, testset={"version": testset["version"]}, records=records)
```

An outcome that also lists the documents your system retrieved (`retrieved_sources`) or cited (`cited_sources`) gets its sources scored. A product that records more per question, such as its own timings, extends the report through a `Profile`: its own report kind, extra outcome fields, extra summary sections and fallback texts that never count as an answer. See [Extending the evaluation report](docs/FORMATS.md#extending-the-evaluation-report).

## Benchmark tools

Four tools measure the models themselves. `hbk-contract-probe` and `hbk-compare` need only Python. `hbk-llama-bench` and `hbk-model-candidates` run llama.cpp in Docker: they need Docker Engine or Docker Desktop, room for the llama.cpp images (`ghcr.io/ggml-org/llama.cpp:full-b11382` for llama-bench, about 4 GB, and `:server-b11382` for downloads and serving, about 1.2 GB, pulled on first use), and GGUF model files, which you download yourself or let the tools download and verify (the example known model is 2.5 GB; the example catalog's two default files are about 7 GB together). The two Docker tools, `hbk-llama-bench` and `hbk-model-candidates`, print what they would run with `--dry-run`, without Docker.

The examples are the same community garden as the evaluation quick start: `examples/catalog.json` (and `catalog.yaml`) lists two real public models with their pinned download facts, `examples/known-models.json` one of them, and `examples/probe/` a claim-checking contract with eight items.

### Probe a JSON answer contract (`hbk-contract-probe`)

Ask a model for JSON answers and check every reply against the JSON schema it was sent with. No Docker: any OpenAI-compatible server works.

1. Start a server, for example `llama-server -m your-model.gguf --port 8080`.

2. Run the example contract: each item is a claim about the garden, sent with the document it is about, and the model must answer `{"verdict": "supported" | "refuted" | "not_stated", "reason": "..."}`.

   ```sh
   hbk-contract-probe --label first-probe --out-dir results \
     --base-url http://127.0.0.1:8080/v1 --model local \
     --items examples/probe/items.json \
     --system examples/probe/system.txt --user-template examples/probe/user.txt \
     --schema examples/probe/schema.json
   ```

   The report, `results/first-probe-<date>.json`, holds one record per claim: whether the reply is valid JSON for the schema (and every violation if not), whether the verdict is the expected one, whether the reason matches the item's patterns, the finish reason, and the tokens and timings the server reported. The summary gives the rates overall and per category.

3. The same items through a probe program of your own, which builds and sends the requests itself and prints one reply line per item ([probe protocol v1](docs/FORMATS.md#probe-protocol-v1)):

   ```sh
   hbk-contract-probe --label adapter-probe --out-dir results \
     --items examples/probe/items.json --base-url http://127.0.0.1:8080/v1 \
     --probe-command "python examples/probe/command_probe.py"
   ```

   `--probe-setup` runs a command first, for example `docker cp` of a probe into a container that `--probe-command` then runs with `docker exec -i`. A third mode, `--prepared requests.jsonl`, sends requests that are already built.

Other options: `--response-format FILE` instead of `--schema` (OpenAI's nested `json_schema` form or llama-server's flat form, sent unchanged), `--context-dir DIR` for `<id>.txt` context files, `--ids`, `--category`, `--limit`, `--warmup QUESTION`, `--max-tokens`, `--temperature`, `--timeout` and `--api-key-env`. Exit codes: `0` when the report is written, `1` when the setup failed or no item got a reply, `2` for bad options or items.

### Benchmark llama.cpp models (`hbk-llama-bench`)

Run llama-bench in the llama.cpp container and save the result with the build, the SHA-256 of every model and the facts of the machine. Needs Docker.

1. Download the example model and run a short benchmark (3 repetitions of `pp512` and `tg128`, 4 threads, f16 KV cache):

   ```sh
   hbk-llama-bench --models-dir models --known-models examples/known-models.json --fetch \
     --prompts 512 --generations 128 --depths 0 \
     --cache-types-k f16 --cache-types-v f16 --threads 4 --repetitions 3 \
     --reference my-laptop --out-dir results
   ```

   `--fetch` downloads every known model missing from `models/` and checks its size and SHA-256 before using it; a model already verified is not downloaded again. Without `--fetch`, give your own files with `--model file.gguf` (repeat for several). `--models-volume NAME` reads the models from a Docker volume instead of a folder.

2. Read the console summary, one line per test, or the report `results/my-laptop-<date>.json`. Without the matrix options, the default matrix runs `pp512`, `pp2048` and `tg128` at depth 0 and 4096, with f16 and q8_0 KV caches and 4 and 8 threads, 5 repetitions each: 48 tests per model, which takes a while on a CPU.

The machine facts are read automatically. When one cannot be read (RAM speed needs root on Linux), the tool says which option sets it: `--cpu-model`, `--ram`, `--ram-speed`, `--disk-type`. `--from-json raw.json` turns a saved `llama-bench -o json` output into a report without running anything. `--image` and `--fetch-image` choose other llama.cpp images.

### Compare benchmark reports (`hbk-compare`)

Print one run, or the difference between two, as a Markdown table: the llama-bench headline speeds, then the evaluation metrics when a side holds an evaluation report.

```sh
hbk-compare results/my-laptop-<date>.json
hbk-compare results/my-laptop-<date>.json results/other-machine-<date>.json --out results/bench-comparison.md
hbk-compare --before results/my-laptop-<date>.json results/first-run-<date>.json \
  --after results/other-machine-<date>.json results/second-run-<date>.json
```

Two positional files are `before` and `after`. With `--before` and `--after`, each side takes one llama-bench file (a `hbk-llama-bench` report or a bare `llama-bench -o json` array) and one evaluation report. `--model`, `--threads` and `--kv` choose the llama-bench rows shown (default: the first model, the fastest thread count, f16). Warnings name different machines, different test sets, unfinished runs and pending reviews. `--out` also writes the Markdown to a file.

### Screen model candidates (`hbk-model-candidates`)

Take every model of a catalog through the same steps, and keep one summary of all of them: `fetch` (download and verify), `bench` (`hbk-llama-bench` with the catalog's matrix), then, with each model served in turn by its own llama-server container, `probe` (the contract probe) and `eval` (`hbk-eval run`). Needs Docker.

1. See the plan without running anything:

   ```sh
   hbk-model-candidates --catalog examples/catalog.json --dry-run
   ```

2. Download and benchmark the default file of each model (`--steps fetch,bench` is the default). This downloads about 7 GB; add `--only qwen3-4b-instruct-2507` to take only the 2.5 GB model:

   ```sh
   hbk-model-candidates --catalog examples/catalog.json --models-dir models --out-dir results --reference my-laptop
   ```

3. Add the probe and the evaluation to that summary. Each model is served on `127.0.0.1:18080` (`--port`) in a container named `hbk-candidate`, which is removed afterwards. `--resume` keeps the models and the machine name (`--reference`) of step 2:

   ```sh
   hbk-model-candidates --catalog examples/catalog.json --models-dir models \
     --resume results/model-candidates-<date>.json --steps probe,eval \
     --probe-items examples/probe/items.json --probe-system examples/probe/system.txt \
     --probe-user-template examples/probe/user.txt --probe-schema examples/probe/schema.json \
     --testset examples/testset.json --eval-arg=--context-dir=examples/context
   ```

The summary `results/model-candidates-<date>.json` and its Markdown twin compare the models side by side: JSON validity and answer rates from the probe and the evaluation, llama-bench speeds, reply times, and the peak memory of each llama-server. The reports of every step are kept in `results/model-candidates-<date>/`.

A model whose licence is not in the catalog's `licences_allowed`, or that needs a newer llama.cpp than the catalog pins, is skipped.

After the answers of an evaluation step were [reviewed by hand](#review-the-answers-by-hand), bring the reviews into the summary in two steps: rebuild each reviewed evaluation report, then the summary:

```sh
hbk-eval resummarize results/model-candidates-<date>/<gguf id>-eval-<date>.json
hbk-model-candidates --catalog examples/catalog.json --resummarize results/model-candidates-<date>.json
```

#### Options of `hbk-model-candidates`

| Option | Default | Meaning |
|---|---|---|
| `--catalog` | required | model catalog, `.json` or `.yaml` |
| `--only` | every model | candidate or GGUF ids, comma-separated |
| `--all-quants` | off | also the GGUF files that are not defaults |
| `--steps` | `fetch,bench` | among `fetch`, `bench`, `probe` and `eval` |
| `--models-dir`, `--out-dir` | `models`, `.` | folder of the GGUF files; folder of the summary and of the step reports |
| `--reference` | none (kept by `--resume`) | name of the machine, kept in the reports |
| `--cpu-model`, `--ram`, `--ram-speed`, `--disk-type` | read from the machine | machine facts that cannot be read |
| `--bench-arg ARG` | none | extra `hbk-llama-bench` argument, repeat for several (write `--bench-arg=--threads`) |
| `--server-image` | the catalog's `server_image` | llama.cpp image that downloads and serves the models |
| `--port`, `--ctx-size`, `--server-arg ARG` | 18080, 8192, none | host port on 127.0.0.1, context size and extra llama-server arguments |
| `--reasoning` | `off` | llama-server reasoning mode: `off`, `on` or `auto` |
| `--llm-mem-limit` | none | memory limit of the served model's container, for example `6g` |
| `--start-timeout` | 900 s | how long a model may take to load |
| `--probe-items` | required by `probe` | probe items, `.json`, `.jsonl` or `.yaml` |
| `--probe-system`, `--probe-user-template`, `--probe-schema` | required by the template probe | system prompt, user template and JSON schema of the reply |
| `--probe-response-format` | none | a whole `response_format` object instead of `--probe-schema` |
| `--probe-context-dir` | none | folder of `<item id>.txt` context files for the probe |
| `--probe-max-tokens`, `--probe-timeout` | 512, 600 s | `max_tokens` of each probe request; seconds to wait for the server to connect or to send more data |
| `--probe-command`, `--probe-setup` | none | a [probe v1](docs/FORMATS.md#probe-protocol-v1) program instead of the template probe, and a command run before it |
| `--warmup QUESTION` | none | asked first in the probe and not scored |
| `--testset` | required by `eval` | test set of the evaluation step |
| `--eval-arg ARG` | none | extra `hbk-eval run` argument, repeat for several (write `--eval-arg=--context-dir=DIR`) |
| `--ids`, `--category`, `--limit` | all | keep part of the items; they filter the probe items and the test set alike, so give ids or categories that both use |
| `--resume SUMMARY` | none | run more steps into an earlier summary |
| `--resummarize SUMMARY` | none | rebuild an earlier summary and its Markdown from its step reports |
| `--dry-run` | off | print the plan without running anything |

## Use the benchmark tools in a product

Each tool takes a profile and an injectable `Shell` (every process, Docker call and machine fact goes through it), so a product can keep the kit's code and give its own names, defaults, kinds and texts:

- `hbk-llama-bench`: `LlamaBenchProfile` (default images, known models, report kind, the containers that compete for the machine, messages).
- `hbk-compare`: `CompareProfile`, which registers the product's own report kinds, rows and warnings. See [Registering a product's kinds](docs/FORMATS.md#registering-a-products-kinds).
- `hbk-contract-probe`: `ContractProfile`, the product's own record fields, summary rates and kind.
- `hbk-model-candidates`: `RunnerProfile` and `CandidatesProfile` (defaults, kinds, headline keys, Markdown texts and columns), and a subclass of `CandidateRun` for the steps that depend on the product: how a model is fetched, how it is served (for example in place of a running server, under the same network alias), how it is probed and how it is evaluated.

Each of these tools has a `main(argv, profile=...)`, with `shell=...` where it runs commands, that returns its exit code, so a product's script stays a few lines long.

A product whose older scripts the kit replaces can keep their exact behaviour: `LlamaBenchProfile` and `RunnerProfile` take the help text of each option (`option_help`, `None` for none), can leave out the kit's own options (`version_option`, `known_models_option`) and can let an unreadable input raise instead of printing `[error]` (`input_errors=()`); a `Shell` subclass with `start_errors = ()` lets a program that cannot start raise too. A `CandidateRun` subclass adds its options after `--server-image` (`add_serving_arguments`) or at the end (`add_arguments`), reads its own test sets (`load_testset`), and `CandidatesProfile.name_key` makes the catalog require the product's own name key.

## Result formats

Every report is a JSON file whose first keys are `kind` and `schema_version`; a tool refuses a file whose `schema_version` is newer than the one it reads. The full reference, key by key, is [docs/FORMATS.md](docs/FORMATS.md).

| Report | `kind`, version | Written by |
|---|---|---|
| [Evaluation](docs/FORMATS.md#evaluation-report) | `horus-bench-kit-eval`, 1 | `hbk-eval run` |
| [llama-bench run](docs/FORMATS.md#horus-llama-bench) | `horus-llama-bench`, 1 | `hbk-llama-bench` |
| [Contract probe](docs/FORMATS.md#horus-contract-probe) | `horus-contract-probe`, 1 | `hbk-contract-probe`, `hbk-model-candidates` |
| [Model candidates](docs/FORMATS.md#horus-model-candidates) | `horus-model-candidates`, 1, with a Markdown twin | `hbk-model-candidates` |

The inputs are documented there too: [test sets](docs/FORMATS.md#test-set), [model catalogs](docs/FORMATS.md#model-catalog), [known models](docs/FORMATS.md#known-models), [probe items](docs/FORMATS.md#probe-items) and the [probe protocol](docs/FORMATS.md#probe-protocol-v1).

## Dependencies and licences

| Component | Needed for | Licence |
|---|---|---|
| Python 3.10 or later, standard library | everything | PSF-2.0 |
| PyYAML 6 or later, optional (`[yaml]`) | YAML test sets | MIT |
| setuptools 77 or later | building and installing the package | MIT |
| pytest 8 or later (`[test]`) | running the tests | MIT |
| pytest's own dependencies, installed with it: iniconfig, packaging, pluggy, Pygments, colorama (Windows), exceptiongroup, tomli and typing_extensions (older Pythons) | running the tests | MIT; Apache-2.0 or BSD-2-Clause; MIT; BSD-2-Clause; BSD-3-Clause; MIT; MIT; PSF-2.0 |
| Docker Engine and CLI, an external program | only llama-bench, model downloads and serving | Apache-2.0 |
| llama.cpp container images (`ghcr.io/ggml-org/llama.cpp`), pulled by Docker when a tool runs them | llama-bench, model downloads (`curl`, `sha256sum` inside the image) and serving | MIT |
| GGUF model files, downloaded by you or by `--fetch` | benchmarks, probes and evaluations | each model's own licence; a catalog lists the licences it accepts |

The OpenAI-compatible server you evaluate is not a dependency: the kit only sends it HTTP requests. The kit ships no model and no image: it only runs what you choose.

## Development

```sh
pip install -e ".[test]"
python -m pytest
python scripts/make-zip.py      # dist/horus-bench-kit-<version>.zip, the folder as it can be shared
python scripts/make-zip.py --out /tmp/zips
```

`make-zip.py` reads the version from `pyproject.toml` and leaves out caches, build output, virtual environments, `dist/`, and `results/` and `out/` folders. It refuses to build, and names each problem, when `LICENSE`, `NOTICE` or `README.md` is missing, a Python or shell file does not start with the SPDX line, a Python file imports anything but the standard library, the kit, PyYAML or pytest, a dependency in `pyproject.toml` is outside the permissive allowlist, or a file holds a string that must not be published or a path inside a personal home folder (`/home/<name>/`, `C:\Users\<name>\`). Those checks live in `src/horus_bench_kit/publishable.py`, which needs only the standard library, so another project can load it by path and run `problems(kit_folder)`; the strings it looks for are stored as SHA-256 digests only.

The tests start a small fake OpenAI-compatible server on `127.0.0.1`; they need no network and no model.

## Contributing

Contributions are welcome. Pick an issue labelled `good first issue` or `help wanted` and comment "I'd like to work on this": a bot assigns it to you. [CONTRIBUTING.md](CONTRIBUTING.md) has the steps, the kit's rules, the commit norm and the sign-off every commit needs. Questions go to [Discussions](https://github.com/Horus-EIP/horus-bench-kit/discussions).

By Apache License 2.0 section 5, any contribution you submit for inclusion is licensed under the same Apache License 2.0, with no extra terms; you need no separate agreement. Everyone who takes part follows the [Code of Conduct](CODE_OF_CONDUCT.md). Report a vulnerability privately, as [SECURITY.md](SECURITY.md) explains.

## Licence

Copyright 2025-2026 Loup Marquez-Luttringer, Noah Gibelli and Matheus Lopez. Licensed under the Apache License, Version 2.0: see [LICENSE](LICENSE) and [NOTICE](NOTICE).
