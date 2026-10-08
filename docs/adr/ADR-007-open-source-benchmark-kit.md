# ADR-007: The benchmark and evaluation kit is open source

**Date:** 2026-10-08
**Status:** Accepted (08/10/2026)
**Deciders:** Loup Marquez-Luttringer, Noah Gibelli, Matheus Lopez
**Related:**

- [ADR-004](ADR-004-closed-source-licence.md) (Horus is closed source), amended by this ADR for one folder
- `opensource/horus-bench-kit/` (the kit, with its own `LICENSE`, `NOTICE` and `README.md`)
- `benchmarks/README.md` (how Horus runs its benchmarks and evaluations)

---

## Context

ADR-004 keeps Horus closed: no part of the repository is under an open-source licence.

To choose and size the models Horus runs, we built tools that have nothing to do with Horus itself:

- a llama-bench runner that measures any GGUF model in the official llama.cpp image and records the machine, the llama.cpp build and the SHA-256 of each model;
- a comparison that turns those reports into Markdown tables;
- a model-candidates runner that checks GGUF models against a JSON-schema answer contract through llama-server's OpenAI-compatible API;
- an evaluation engine: a test-set format, answer and source scoring, reports and their comparison.

They exist because the llama.cpp, Qwen, Hugging Face and FastEmbed communities published their work openly. Tek5 Objective 1 asks us to protect the product and also to give back. These tools let us give back without opening the product.

## Decision

The generic part of these tools becomes one standalone package, `horus-bench-kit`, in `opensource/horus-bench-kit/`, under the Apache License 2.0. The folder can be zipped and shared as it is: it has its own licence, notice, README and tests, and it imports nothing from the rest of the repository.

Horus uses the kit instead of keeping its own copy: `scripts/eval/` and `scripts/benchmarks/` import it and add what is specific to Horus. There is one copy of the generic code.

### What is opened

- the llama-bench runner, the benchmark comparison, the model-candidates runner and a contract probe for any OpenAI-compatible endpoint (`hbk-llama-bench`, `hbk-compare`, `hbk-model-candidates`, `hbk-contract-probe`);
- the evaluation engine: the test-set format and loader, the scoring, the report and the comparison (`hbk-eval`);
- a small target interface (a question in, an answer with its sources and timings out) and one target, `openai`, for any OpenAI-compatible chat endpoint;
- their tests, a small example test set and corpus written for the kit, and the documented JSON formats of the result files.

### What stays closed

- everything that talks to Horus: login, tasks, task events, the stack helpers, the Horus evaluation target, `run-eval.py` and the probe that runs inside the agent container;
- Horus's prompts, including the B-98 answer-contract prompt, and the router examples;
- the 100-question test set in `tests/eval/` and the documents in `demo_assets/`;
- the benchmark results in `benchmarks/` and `models/manifest.json`;
- the rest of the repository.

### Licence choice

Apache-2.0:

- It is permissive, so anyone, companies included, can use and change the kit, and Horus itself can keep using it inside a closed product.
- It grants a patent licence, which MIT does not.
- Section 5 makes contributions to the kit come in under the same licence, so the kit needs no separate contributor agreement. Contributions to the rest of Horus still need the Horus Contributor Agreement (`LICENSE` section 9, `CONTRIBUTING.md`).
- It is the licence of much of the stack the kit measures (vLLM, FastEmbed, the Qwen models).

A copyleft licence (GPL, AGPL) would keep companies from adopting the kit and add nothing for us: we are the copyright holders.

## Consequences

- This ADR amends ADR-004 for `opensource/horus-bench-kit/` only. The rest of the repository stays under the Horus proprietary licence, and the root `README.md` says so.
- The root `LICENSE`, which covers Horus in every form, leaves this folder to its own Apache-2.0 licence since version 2.1 (08/10/2026), agreed by the three copyright holders: section 1 says `opensource/horus-bench-kit/` is not part of the Software.
- The kit is our own code, not a third-party component, so `THIRD_PARTY_NOTICES` does not list it.
- A test in `tests/ci` keeps the kit publishable: it fails when the kit imports anything outside itself, lacks its licence files or the SPDX header on a source file, contains Horus-only content, or gains a dependency that is not permissive. A CI job installs the kit in a fresh environment and runs its tests.
- Work that touches the kit is open source the moment it is merged: Horus prompts, test sets, results and anything that talks to Horus must stay in `scripts/eval/` and `scripts/benchmarks/`.
