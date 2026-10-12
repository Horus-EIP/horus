# Evaluation test set

`testset.yaml` holds the 100 questions of the dev plan's §10 benchmark, asked against the fixed demo corpus in `demo_assets/`. `scripts/eval/run-eval.py` runs it against a live stack and writes the results to `benchmarks/` (format in `benchmarks/README.md`).

```bash
python -m pytest tests/eval -q -p no:cacheprovider
```

These tests are hermetic. They check the set itself and the Horus side of the evaluation: the agent's fallback texts and the MAS watchdog, the B-98 contract records, the stack sections of the report and the runner. The generic scoring, test-set checks, report building and benchmark engine live in the open-source kit in `opensource/horus-bench-kit/` and are tested there (`python -m pytest opensource/horus-bench-kit -q -p no:cacheprovider`). CI runs both (`.github/workflows/eval-testset.yml`) whenever `demo_assets/`, `tests/eval/`, `scripts/eval/`, `scripts/benchmarks/`, `opensource/horus-bench-kit/` or the reused `scripts/perf/` scripts change.

The same folder tests the benchmark tooling of `scripts/benchmarks/` (`pytest.ini` puts both script folders and the kit's `src/` on the path), with Docker, the host queries and llama-server replaced by fakes:

| Test file | What it covers |
|---|---|
| `test_bench_llama.py` | The plan's llama-bench command, the pinned image and the known Q4_K_M and Q5_K_M models against the CPU stack, the stack's fetch script mounted at `/opt/horus/fetch-model.sh`, and the kit's copy of that script differing from it only in its messages. |
| `test_llama_bench_runner.py` | `run-llama-bench.py` with a fake Docker shell: the Horus defaults, a run, a missing model, `--fetch`, `--dry-run`, and the errors that still stop it with a traceback as before (an unreadable `--from-json` file, a program that cannot start). |
| `test_bench_compare.py` | `compare-benchmarks.py`: the §10 table, changes, the Horus warnings, the 2026-09-01 baseline, a committed llama-bench report. |
| `test_eval_stack.py` | The MAS router histogram (`mas_routing_decision_seconds`). |
| `test_eval_contract.py` | B-102 JSON reliability of the B-98 answer: the status, answer and source scores of a reply, the record keys and the probe summary. |
| `test_agent_contract_probe.py` | `scripts/eval/agent-contract-probe.py` with a fake agent, knowledge store and llama-server. One test runs it in a subprocess against the agent's real `answer_contract` and checks that the checker accepts the schema it builds; it is skipped where the agent's packages are not installed, as in CI. |
| `test_model_candidates.py` | `scripts/benchmarks/model-candidates.yaml` (licences, pinned revisions, builds, defaults, the baseline matching B-91 and the manifest), the stack-pin gate, the candidate server command on the stack network, the response-cache check and the summary tables. |
| `test_model_candidates_runner.py` | `run-model-candidates.py` end to end with a fake Docker shell, tools and installer: every step, a failed download, a model that does not load, a missing stack, `--resume`, `--resummarize`, `--dry-run`, and the installer's real downloader adopting a file already in place. |
| `test_golden_outputs.py` | Today's code against the committed results, byte for byte (line endings aside; the reports were written with Python 3.11, and from Python 3.12 on `sum()` adds floats with compensation, so there a `sum` statistic may differ from the committed one in its third decimal): every `horus-eval` report resummarised and rebuilt from its records, the summary of every `horus-contract-probe` report, `run-model-candidates.py --resummarize` of `model-candidates-2026-10-06`, four `compare-benchmarks.py` tables kept in `golden/`, and the `--help` text of `run-eval.py`, `run-llama-bench.py`, `run-model-candidates.py` and `compare-benchmarks.py` (`golden/help/`, one file per Python version, since argparse wraps usage lines differently from one version to another; other versions skip). |

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
