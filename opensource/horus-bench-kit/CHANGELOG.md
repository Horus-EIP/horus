# Changelog

Every release of horus-bench-kit, newest first. Versions follow [Semantic Versioning](https://semver.org/). Report formats carry their own `schema_version`, described in [docs/FORMATS.md](docs/FORMATS.md).

## 0.1.0 - 2026-10-08

First release.

### Added

- Evaluation engine: the test-set format (JSON, or YAML with the optional PyYAML), its validation against the documents, answer and source scoring, the `horus-bench-kit-eval` report (schema version 1) and a two-reviewer manual review.
- `hbk-eval` with four commands: `validate`, `run`, `resummarize` and `compare`.
- The `openai` target, for any OpenAI-compatible chat endpoint, with an optional context file per question and streaming to measure the time to first token.
- `Target` and `Hooks` protocols, `run_items` and `Profile`, so another system can be evaluated and a product can extend the report with its own kind, fields and summary sections.
- A checker for a subset of JSON Schema that reports why a model's JSON reply does not fit, plus reply classification and timing helpers.
- Markdown comparison of one or two evaluation reports.
- An example test set about a fictional community garden, with its three documents and its context files.
- `hbk-contract-probe`: asks a model for JSON answers and checks every reply against the JSON schema it was sent with, from a prompt template, from prepared requests, or through a probe program (probe protocol version 1). It writes the `horus-contract-probe` report (schema version 1), and a `ContractProfile` lets a product score its own fields.
- `hbk-llama-bench`: runs llama-bench in the llama.cpp container and writes the `horus-llama-bench` report (schema version 1) with the build, the SHA-256 of every model and the facts of the machine (CPU, RAM, disk and Docker, on Linux, Windows and macOS). Known models, from a file or a model catalog, can be downloaded and verified with the packaged `fetch-model.sh`.
- `hbk-compare`: a Markdown table of one benchmark run or of two, from llama-bench reports, bare llama-bench output and evaluation reports. A product registers its own report kinds, rows and warnings with a `CompareProfile`. A llama-bench report, whose `summary` is a list, compares without error.
- `hbk-model-candidates`: takes the GGUF models of a catalog through download, llama-bench, a contract probe and an evaluation, each model served in turn by its own llama-server container, and writes the `horus-model-candidates` summary (schema version 1) with a Markdown twin. Runs can be resumed and resummarised. The serving, probe and evaluation steps are hooks that a product can replace.
- An injectable `Shell` for every process, Docker call and machine fact, so the tools can be tested and embedded without Docker.
- An example model catalog of two public models, a known-models file and a claim-checking contract probe with its system prompt, user template, schema, eight items and a probe program.
- `scripts/make-zip.py`, which builds a reproducible zip of the kit folder, version taken from `pyproject.toml`, after checks that it can be published: licence files, SPDX lines, imports, permissive dependencies, strings that must not appear and paths inside a personal home folder. The checks live in `horus_bench_kit.publishable`, which needs only the standard library.
- `docs/FORMATS.md`, the reference for the test-set, catalog, probe-item and report formats, the probe protocol and the report-written convention.
