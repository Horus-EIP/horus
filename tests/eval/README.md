# Evaluation test set

`testset.yaml` holds the 100 questions of the dev plan's §10 benchmark, asked against the fixed demo corpus in `demo_assets/`. `scripts/eval/run-eval.py` runs it against a live stack and writes the results to `benchmarks/` (format in `benchmarks/README.md`).

```bash
python -m pytest tests/eval -q -p no:cacheprovider
```

These tests are hermetic. They check the set itself and unit-test the runner's scoring and report building. CI runs them (`.github/workflows/eval-testset.yml`) whenever `demo_assets/`, `tests/eval/`, `scripts/eval/` or the reused `scripts/perf/` scripts change. A change to `scripts/benchmarks/` alone does not trigger that workflow yet: run the tests by hand.

The same folder tests the benchmark tooling of `scripts/benchmarks/` (`pytest.ini` puts both script folders on the path), with Docker, the host queries and llama-server replaced by fakes:

| Test file | What it covers |
|---|---|
| `test_bench_host.py` | CPU, RAM, disk and Docker facts parsed from Linux, Windows and macOS outputs, and the `machine` block. |
| `test_bench_llama.py` | The plan's llama-bench command, the pinned image and model hashes against the CPU stack, parsing and the enriched report. |
| `test_llama_bench_runner.py` | `run-llama-bench.py` end to end: run, fetch, missing models, `--from-json`, `--dry-run`. |
| `test_bench_compare.py` | `compare-benchmarks.py`: the §10 table, changes, warnings, the 2026-09-01 baseline, llama-bench selection. |
| `test_eval_stack.py` | llama-server `/metrics`, `/props`, command-line and `/proc/1/status` parsing, the MAS router histogram, and the cgroup files (`memory.peak`, `memory.events`, `memory.stat`). |

## Contents

| Category | Items | Expected behaviour |
|---|---:|---|
| `lookup` | 47 | One fact stated in one document. |
| `numeric` | 22 | A number from one document. Two are computed from figures of the same document. |
| `multi_hop` | 15 | Two or more facts: 5 inside one document, 10 across two documents. |
| `not_in_corpus` | 10 | The documents do not say. The system must answer that the documents do not contain it. |
| `direct` | 6 | Greetings, small talk and arithmetic. Routed as `DIRECT_ANSWER`, with no retrieval. |

The 84 in-corpus questions cover all five documents.

## Item fields

| Field | Meaning |
|---|---|
| `id` | Stable, unique. The prefix names the document (`fin`, `hr`, `comp`, `exp`, `it`), `cross` for two documents, `none` for not-in-corpus, `direct` for direct answers. Never reuse a removed id. |
| `question` | Asked verbatim. |
| `expected_answer` | Short reference answer for the reviewers, with facts copied from the document. |
| `answer_patterns` | Case-insensitive regexes. The answer is correct when **every** pattern matches. Use alternation inside one pattern for variants (`\b4\.2\s*(m\b|million)|\b4,200,000\b`). Start numbers with `\b` so `85,000` cannot match inside `185,000`. Not-in-corpus items share `refusal_patterns`. |
| `expected_source` | The document file name, a list of file names when the answer needs all of them, or `null` for `not_in_corpus` and `direct`. |
| `category`, `difficulty` | See above; `easy`, `medium` or `hard`. |
| `evidence_patterns` | Only for computed answers (`numeric`, `multi_hop`), whose result is not written in the document: the patterns of the figures it is computed from. |
| `absent_terms` | Only for `not_in_corpus`: words that must not appear in any document (whole-word match). |

## What the tests enforce

- 100 items, unique ids and questions, the schema above, valid regexes.
- `corpus` lists the SHA-256 of each document (line endings normalised to LF). If a document changes, the tests fail until the answers that cite it are checked again and the hash is updated.
- Every answer pattern of an in-corpus item matches its source document (or, for computed answers, every evidence pattern does).
- No absent term of a not-in-corpus item appears in the corpus.
- Each `expected_answer` passes its own patterns, and no in-corpus or direct item accepts "The retrieved content does not contain this information."

## Changing the set

Read the document, copy the facts, run the tests. Bump `version` (semantic versioning): patch for a pattern fix that does not change what counts as correct, minor for a changed question or answer, major when items are added or removed or the corpus changes. Results in `benchmarks/` record the version and file hash they were measured with, so only compare runs with the same version.
