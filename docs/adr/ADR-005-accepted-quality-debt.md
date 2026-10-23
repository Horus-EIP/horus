# ADR-005: Quality debt we accept (for now), and when we repay it

**Date:** 2026-09-24
**Status:** Accepted (24/09/2026). Reviewed at every MINOR release (see `VERSIONING.md`). The 07/10/2026, 09/10/2026 and 23/10/2026 updates, which mark what was repaid since, are not reviewed by the team yet.
**Last updated:** 2026-10-23
**Deciders:** Loup Marquez-Luttringer, Noah Gibelli, Matheus Lopez
**Related:**

- ADR-004 (licence), ADR-006 (machines under 16 GB)
- `TESTING.md` (test strategy), `VERSIONING.md` (versions and releases)
- ATP v7 results (18/09/2026) and `docs/eip/regressions.md`
- `CHANGELOG.md`

---

## Context

Tek5 asks us to *"document quality debt: things we could have done differently but didn't"*. The mentor adds *"document technical debt with estimated cost"* (follow-up of 19/09/2026).

Horus is built by three people with other jobs, on a stack of 12 services and multi-GB models. In several places we knowingly chose the faster or simpler option over the "textbook" one.

This ADR lists those choices. For each one it says:

- what we did
- what the better way would be
- **why we didn't do it then**
- the **estimated cost** to fix
- the **risk** of leaving it (the "interest")
- the **decision**: when we repay it, or why we accept it

The register was written from `master` at `61ce28a` (24/09/2026), the CI configuration and the ATP beta results. On 07/10/2026 every item was checked again against `Sprint#1_September2026_Tek5` at `8f11aaa`. [Status on 07/10/2026](#status-on-07102026) gives the commits and the evidence.

**Cost scale:** person-days (d) for one of us, including tests and review. XS < 0.25 d · S ≈ 0.5 d · M ≈ 1–2 d · L ≈ 3–5 d. Costs are the 24/09 estimates for the whole item. Where part of an item is repaid, the rest has not been re-estimated.

---

## Decision

We keep this register as the single list of accepted debt. Every item is either:

- **Accept**: we consciously keep it, and the reason stays valid, or
- **Repay by** a named version (for example 0.2.0): we fix it in that release.

New debt is added in the commit or PR that creates it (one line here). The register is reviewed at each MINOR release.

---

## The register

The debt as recorded on 24/09/2026. The Decision column says where each item stands on 07/10/2026.

### A. CI and code-quality tooling

| # | Debt | Better way | Why we didn't | Cost | Risk if we leave it | Decision |
|---|---|---|---|---|---|---|
| A1 | The **web client is not in CI**. It has `lint`, `typecheck` and `test` (Vitest) scripts, but nothing runs them, and two did not work: `typecheck` pointed at a missing `tsconfig.app.json`, and `lint` ran `next lint`, which Next.js 16 removed. | A CI job running `npm ci`, `npm run typecheck`, `npm test` and `npm run lint` in `src/services/web-client` | CI was built service by service, Python first; the frontend was moving fast | S | Front-end bugs reach testers. The ATP crash F25 and the layout overflow F37 went through. | **Open.** Repay by 0.1.2 |
| A2 | **No static type checking** on Python: no mypy or pyright. The pre-commit config points to a mypy configuration that does not exist. | mypy on new code and `src/services/mas/auth`, then extend gradually | A large codebase with many untyped ML libraries: turning it on everywhere means hundreds of errors | M to start, then ongoing | Type bugs only found at runtime | **Open.** Repay by 0.2.0 (start); full coverage: accept |
| A3 | `ruff format` runs only in pre-commit, which is optional; CI runs only `ruff check` | `ruff format --check` in CI | Nobody made the one big formatting commit | XS | Noisy diffs, style arguments in review | **Open.** Repay by 0.1.2 |
| A4 | **Narrow ruff rule set**: bug-catching rules only; style, docstring and annotation rules off; several bugbear rules ignored (e.g. B904) | A wider rule set | Deliberate: we want lint failures to mean real bugs, not style noise | — | Some real issues (e.g. exception chaining) not flagged | **Accept** |
| A5 | **bandit** (security scan) was run once for the greenlight, not in CI | A bandit job that fails on MEDIUM and above | Done by hand for the jury, never automated | XS | A new security smell goes unnoticed | **Open.** Repay by 0.2.0 |
| A6 | **Installer tests run only on release tags** (`desktop-release.yml`, or by hand) | Run them on every push and PR | The installer was added late, in its own workflow | XS | An installer regression is found only when tagging | **Repaid** on 09/10/2026: the `test-installer` job of `ci.yml` runs them on every push and pull request |
| A7 | **Coverage is per service with fixed thresholds** (MAS 85 %, agent 90 %, knowledge store 85 %), and some tests were written to raise the number (e.g. `tests/mas/unit/test_registry_tool_functions_coverage.py`) | Coverage as a floor, plus behaviour-focused tests on the critical path | Coverage gates were a fast way to force testing; the greenlight looked at the number | M (gradual) | High percentage, weak assertions; the ATP still found 2 features that nobody could use (F13/F14) | **Accept the gates; repay the naming and assertions gradually** (`TESTING.md` §4) |

### B. Tests

| # | Debt | Better way | Why we didn't | Cost | Risk if we leave it | Decision |
|---|---|---|---|---|---|---|
| B1 | **No end-to-end test in CI.** `installer/smoke.py` and the 20 scripts in `scripts/integration-checks/` are run by hand. | A CI job that starts the stack with tiny models and runs `smoke.py` | 12 services and multi-GB models don't fit a standard CI runner in reasonable time | L | Breaks between services are found late (by testers) | **Repaid** on 09/10/2026, for 0.2.0 (B-77): the `e2e-mock` job of `ci.yml` runs the stack on the mock model server of ADR-008 instead of tiny models. The real model is still checked by hand: the smoke test on every release candidate (`TESTING.md`) and the contract tests with `-m real_llm` |
| B2 | **No automatic check of answer quality.** The out-of-corpus hallucination (F20) and the CPU digit corruption were found by testers. | A small grounding and refusal evaluation set, run on the GPU VM before each release | Needed a GPU runner; the school GPU VM only just became available | M | The product's core promise ("it doesn't invent") silently regresses | **Part repaid** (`084a1c2`). The rest by 0.2.0 |
| B3 | **Tests in two places**: `tests/` and `src/services/knowledge-store/tests/` | Everything under `tests/<service>/` | Historical | XS | Tests missed by CI or by the coverage config | **Open.** Repay by 0.1.2 |
| B4 | **The ATP marked features "Done" that testers couldn't use** (F13/F14 search and category filter) | Check each ATP scenario against the shipped UI before sending | Time pressure before the beta | XS per ATP | Wasted tester time; credibility with the jury | **Repay at the next ATP.** The two features now exist (`c2b3184`) |

### C. Dependencies and builds

| # | Debt | Better way | Why we didn't | Cost | Risk if we leave it | Decision |
|---|---|---|---|---|---|---|
| C1 | **Unpinned Python dependencies**; images on `latest` and `redis:7` | Lock files (`uv pip compile`), pinned tags and a CI licence gate | Easier upgrades during development | S | Silent breakage or licence changes (Redis 7.4 went RSALv2/SSPL) | **Repaid**, not released yet (`b816e70`, `a820a0d`, `ade67e9`; Valkey instead of Redis in `9b72084`) |
| C2 | **Test tools installed in production images** (pytest, pytest-cov, pytest-asyncio; pytest-html in the agent) | A `requirements-dev.txt` for tests only | One requirements file per service was simpler | XS | Bigger images, more licences to declare | **Repaid**, not released yet (B-46) |
| C3 | **The MAS image is single-stage** and keeps compilers (`build-essential`, `g++`); pip runs with `--use-deprecated=legacy-resolver` | Multi-stage build (like the knowledge store); fix the conflicts the legacy resolver hides | The legacy resolver unblocked a dependency conflict quickly | S–M | Larger image; the resolver may install incompatible versions | **Repaid**, not released yet (B-67) |
| C4 | **passlib 1.7.4 + `bcrypt<4.0`** in MAS, `bcrypt==3.2.2` pinned in the agent. Passlib clashes with recent bcrypt. | Use `bcrypt` directly, with one version everywhere | It touches password hashing, so it needs care | S | Stuck on old crypto packages; future security fixes may be blocked | **Repaid in B-68 (23/10/2026; release pending):** direct bcrypt 5.0.0, refreshed locks and licence notices, and successful authentication transparently re-hashes legacy credentials |
| C5 | **The Python version is not consistent**: the README badge says 3.13, ruff targets `py313`, CI runs 3.13, and the Docker images use `python:3.11-slim` | One supported version, the same everywhere | Each part was set up at a different time | XS–S | "Works on my machine" bugs; lint rules for a version we don't run | **Part repaid**: the README says 3.11 (`8dc2410`), and CI runs the service and installer tests on the images' Python, read from `src/services/PYTHON_VERSION` (09/10/2026). Ruff's `py313` target by 0.1.2 |
| C6 | **Unused or odd dependencies**: PyMuPDF (AGPL, never imported) in the knowledge store; the PyPI `graphlib` package in MAS next to the standard-library `graphlib` | Remove them | Nobody cleaned the requirements after refactors | XS | PyMuPDF is the only licence blocker (ADR-004) | **Part repaid**: PyMuPDF removed (`a2e5807`). `graphlib` by 0.1.2 |
| C7 | **Promtail** (log shipper) is end-of-life since March 2026 | Grafana Alloy | Still works | S | No more security fixes | **Repaid**, not released yet (B-67) |

### D. Architecture and runtime

| # | Debt | Better way | Why we didn't | Cost | Risk if we leave it | Decision |
|---|---|---|---|---|---|---|
| D1 | **Heavy install**: ~150 GB disk peak, 1.5–2 h first run, ~16 GB RAM. The stack builds from source on the customer's machine and runs two model runtimes (Transformers + vLLM) plus a full observability stack. | Prebuilt images, and a lighter CPU profile (optional observability, one model runtime) | Building from source was the fastest way to ship a beta that runs on every OS | L | The #1 ATP complaint; one tester's PC froze; it blocks pilots | **Part repaid** (`736fdc2`, `9739864`, `5055cd2`). Measure the prebuilt install by 0.2.0; slimmer profile by 0.3.0 |
| D2 | **Source code shipped in the beta ZIP** | Prebuilt, signed images; no source to customers | Same as D1 | (part of D1) | Anyone with the ZIP has our code (ADR-004) | **Open.** Repay by 0.2.0 |
| D3 | **No healthcheck for the agent, the knowledge store and the web client.** Compose treats "started" as "ready" for the three slowest services. | A healthcheck per service | Only the infrastructure services got one at first | S | Installer and smoke test race against slow services | **Repaid in 0.1.2** (`8d1da93`) |
| D4 | **Exact-match answer cache** (Redis) returns a stored answer, even a wrong one, and ignores document changes | Cache only verified answers; invalidate on document upload and delete | The cache was a quick latency win for the demo | S–M | Wrong answers persist; stale answers after a document is deleted | **Repaid**, not released yet (`fd4ae36`, `85f3d89`). Was due by 0.2.0 |
| D5 | **The chat WebSocket drops ~40 s into CPU routing** (ATP F27) | Keep-alive, and blocking LLM work off the event loop | Only visible on CPU; GPU users don't hit it | M | CPU customers see answers never arrive (F27) | **Repaid**, not released yet (`ef05b6b`). Was due by 0.2.0 |
| D6 | **Version numbers disagree**: the v0.1.1 installer, desktop app and web client all report 0.1.0, and the knowledge store reports "1.0.0" | One `VERSION` file read by every part (`VERSIONING.md`) | No versioning policy existed | S | Support confusion: "which version do you run?" | **Repaid in 0.1.2** (`2cdc325`) |
| D7 | **Observability uses AGPL components** (Loki, Tempo) | Apache-licensed alternatives if a customer requires it | They're the best fit and fine as unmodified separate services (ADR-004) | M if ever needed | Some enterprise policies ban AGPL | **Accept** (revisit on customer demand) |

### E. Documentation and process

| # | Debt | Better way | Why we didn't | Cost | Risk if we leave it | Decision |
|---|---|---|---|---|---|---|
| E1 | **Stale docs**: `docs/contributing.md` (branch from `develop`, two approvals, a link to a missing onboarding guide, a CI job that no longer exists), the README CI badge on a deleted branch (`pre-release-fix`), `ci.yml` pointing to a missing `docs/eip/post-beta.md`, and README-FIRST giving 10–30 min for the first install | One pass to align the docs with reality | Docs weren't updated when the branch model and CI changed | S | Newcomers and external contributors follow wrong instructions; testers underestimate install time (T5) | **Repaid**, not released yet (`78bb12e`, `8f11aaa`, `2dbffb9`, `beed5fd`) |
| E2 | **The branch model changed on 24/09** but isn't documented | A short "Branching and CI" section | The cleanup was just done | XS | Contributors don't know where to branch from | **Repaid**, not released yet (`fd7ad5f`, `beed5fd`) |
| E3 | **Very large squash merges** (e.g. #197: 803 files) | Small PRs per issue | That merge consolidated a year of branches into `master` (one-off) | — | Hard to show it was reviewed | **Accept as a one-off.** Rule going forward: one issue = one PR |
| E4 | **Test strategy, versioning and debt were never written down** | `TESTING.md`, `VERSIONING.md`, this ADR | Priority went to features before the beta | — | — | **Repaid**: `VERSIONING.md` (`b4e63c2`), `TESTING.md` (`2dbffb9`) and this ADR |

---

## Status on 07/10/2026

Checked against `Sprint#1_September2026_Tek5` at `8f11aaa`. Line numbers are at that commit. C1, E1 and E2 were repaid later that day by the Objective 1 commits named below, and C5 in part. C2, C3 and C7 were repaid on 08/10/2026, and B1 on 09/10/2026.

### Repaid

| # | Commits | Evidence |
|---|---|---|
| D3 | `8d1da93` (B-59) | `src/infra/docker-compose.yml` declares a `healthcheck` for `web-client` (line 142), `agent` (line 224) and `knowledge_store` (line 343). Listed under 0.1.2 in `CHANGELOG.md` (line 130). |
| D4 | `fd4ae36` (B-63), `85f3d89` | The agent stores only answers that are not empty, degenerate, the spiral fallback or a refusal, and keys them on the knowledge store's corpus version, which every upload, delete and scan changes. `85f3d89` adds the context cap to the key. `CHANGELOG.md` line 45. |
| D5 | `ef05b6b` (B-64), with `fd8778b` (B-93) and `9ea8dae` | MAS's uvicorn runs with `--ws-ping-interval 20 --ws-ping-timeout 120` (`src/services/mas/entrypoint.sh`, line 20); the chain close-out runs in a worker thread; the web client fetches a result that finished while the socket was down. `CHANGELOG.md` line 41. |
| C1 | `b816e70`, `a820a0d`, `ade67e9`, `9b72084` | Each `requirements*.txt` has a `requirements*.lock` with hashes, and the images install from it with `--require-hashes`; every image tag in the Compose files and Dockerfiles names an exact version; the CI job `licences` fails on GPL, AGPL or SSPL in our own processes; Valkey 9.1.2 (BSD-3-Clause) replaced `redis:7`. |
| E1 | `78bb12e`, `8f11aaa`, `2dbffb9`, `beed5fd` | README-FIRST gives 1.5 to 2 hours, the README badge shows the working branch, `docs/contributing.md` is the code-style page only (no `develop`, two-approval, onboarding or `test-integration` rule left), and `ci.yml` explains its `.env` workaround itself. |
| E2 | `fd7ad5f`, `beed5fd` | "Branches" in `CONTRIBUTING.md` and "Repository branches" in `docs/operations.md` say to start from `Sprint#1_September2026_Tek5`. |
| E4 | `b4e63c2`, `2dbffb9` | `VERSIONING.md` and `TESTING.md` are at the repository root, checked against the code on 07/10/2026; this ADR is in `docs/adr/`. |
| C2 | B-46, 08/10/2026 | Each service's test tools are in its `requirements-test.txt`, which `scripts/dev/lock-requirements.sh` does not lock and only the CI test jobs install; no lock file names pytest, coverage or fakeredis, and `tests/ci/test_cpu_torch_build.py` checks it. |
| C3 | B-67, 08/10/2026 | `src/services/mas/Dockerfile` has a builder stage with `build-essential` and `g++`, and a final stage that copies the virtual environment and installs no system package; pip resolves the lock with its default resolver and `pip check` passes in the image. The CPU image went from 1.32 GB to 877 MB. |
| C7 | B-67, 08/10/2026 | `src/infra/docker-compose.yml` runs `grafana/alloy:v1.20.1` with `src/infra/observability/config.alloy`, which gives Loki the labels the web client's `/admin/logs` queries (`compose_service`, `container`) and `compose_project`; no Promtail is left. |
| B1 | B-77, 09/10/2026 (ADR-008) | The `e2e-mock` job of `.github/workflows/ci.yml` builds the MAS, agent and knowledge-store CPU images and `llm-mock`, starts them with `docker-compose.mock.yml` on top of the CPU overlay, uploads `demo_assets/`, runs `installer/smoke.py` and fails unless all 9 steps pass, the out-of-corpus control included (`scripts/ci/smoke-steps.py`). It needs no artifact storage and writes its duration to the job summary. `tests/contract` runs the same model assertions on the mock in CI and on a real model by hand. |
| D6 | `2cdc325` (B-51) | `VERSION` is `0.1.2`; `desktop/package.json`, `desktop/src-tauri/tauri.conf.json`, `desktop/src-tauri/Cargo.toml` and `src/services/web-client/package.json` say `0.1.2`; the knowledge store reports `HORUS_VERSION` (`src/services/knowledge-store/app/main.py`, line 112); the CI job `versions` runs `scripts/ci/check-versions.py` (`.github/workflows/ci.yml`, lines 66–80). |

### Part repaid

| # | Commits | Done | Still open |
|---|---|---|---|
| B2 | `084a1c2` (B-54); first runs `858dcb3`, `1daf376` | 100 questions in `tests/eval/testset.yaml`, 10 of them `not_in_corpus`, and the runner `scripts/eval/run-eval.py`. First runs on 06/10/2026 on the development laptop: 93 of 100 correct on CPU, 96 of 100 on the 8 GB GPU (`CHANGELOG.md`, line 29). | The runs are by hand, not on the GPU VM and not a release step. `.github/workflows/eval-testset.yml` only checks the set and the runner, with no model. |
| C6 | `a2e5807` | PyMuPDF is gone from `src/services/knowledge-store/requirements.txt`. | The PyPI `graphlib` is still in `src/services/mas/requirements.txt` (line 38); `src/services/mas/tasks/decomposition.py` (line 10) imports the standard-library one. |
| D1 | `736fdc2` (B-66), `9739864` (B-90), `5055cd2` (B-96) | The installer pulls prebuilt images: nothing builds on the customer's machine. The CPU profiles run one model server, llama-server, for MAS and every agent, and the CPU images contain no torch. | The installer still asks for 150 GB free, 125 GB with a GPU (`installer/preflight.py`, lines 29–30), because time and disk peak of a prebuilt install are not measured yet (`docs/operations.md`, line 82). Without a GPU, Docker needs at least 13.5 GiB (`installer/profiles.py`, line 22). The GPU profiles still name the 1.5B router in `LLM_MODEL_ID` (`installer/profiles.py`, line 324), but with `LLM_BACKEND=vllm` MAS never loads it. Loki, Promtail, Tempo and Prometheus always run. |
| C5 | `8dc2410` | The README badge and its stack table say Python 3.11, the Python of the images. | `pyproject.toml` targets `py313`. The CI jobs moved to the images' Python on 09/10/2026. |

### Still open

| # | Evidence |
|---|---|
| A1 | `.github/workflows/ci.yml` runs no npm command. `cc10222` made `npm run typecheck` and `npm run lint` run; `npm run lint` now reports 31 problems (20 errors, 11 warnings) and exits 1. The F25 and F37 fixes have Vitest regression tests (`0b93375`, `ae538f3`), which CI does not run either. |
| A2 | `.pre-commit-config.yaml` line 7 still names a mypy configuration; `pyproject.toml` has none. |
| A3 | `.github/workflows/ci.yml` line 64 runs `ruff check` only; `ruff-format` is in `.pre-commit-config.yaml` (line 26). |
| A5 | No workflow runs bandit. The one report is `greenlight/code-quality-review/bandit_report.txt` (now in the team's private repository; 31/05/2026, `docs/eip/objectives-audit.md`, line 54). |
| A6 | Repaid on 09/10/2026: `ci.yml` runs `pytest installer/tests` in its `test-installer` job on every push and pull request, on the images' Python. `desktop-release.yml` and `images.yml` still run them on a `v*` tag. |
| B3 | `src/services/knowledge-store/tests/test_corpus_safety.py` is still there; CI runs `tests/knowledge_store` only (`ci.yml`, line 295). |
| B4 | The repository records no ATP after v7 (18/09/2026, `docs/eip/regressions.md`), so the rule has not been applied yet. |
| C4 | Historical evidence: the old MAS and agent requirements pinned Passlib/bcrypt. B-68 switches password and API-key hashing to the direct bcrypt API, with SHA-256 prehashing for inputs over bcrypt's 72-byte limit. The 23/10/2026 follow-up refreshes the service locks and licence notices, and verifies then re-hashes legacy raw-password hashes after successful authentication. |
| D2 | `packaging/build_bundle.py` (lines 27–31) still puts the service source in the ZIP; `docs/operations.md` (line 79) lists it as not done. The images are signed by `images.yml`, but the installer does not check the signature (`docs/operations.md`, line 80). |

The accepted items still hold: B904 is still ignored (`pyproject.toml`, line 51), the coverage gates are still 85 / 90 / 85 % (`ci.yml`, lines 198, 247 and 298), and the stack still runs `grafana/loki:3.4.2` and `grafana/tempo:2.6.0` (`src/infra/docker-compose.yml`, lines 469 and 496). For E3, the work since 24/09 is in small commits, most named after a backlog item; merging `Sprint#1_September2026_Tek5` into `master` as one squash would repeat it.

---

## Status on 23/10/2026

C4 is repaid for the next release: the MAS and agent lock files now resolve bcrypt 5.0.0 with no Passlib, generated licence records are refreshed, and legacy raw-bcrypt passwords/API keys are verified and upgraded on successful use.

## Summary: what is left and when we pay

| Repay by | Items | Estimated cost |
|---|---|---|
| **0.1.2** (not tagged yet) | A1, A3, B3; the rest of C5 and C6 | Under 2.5 d by the cost scale (S: A1; XS: A3, B3, C6; XS–S: C5). Fixing the 20 lint errors before `npm run lint` can gate CI is not estimated. |
| **0.2.0** (end of Oct) | A2 (start), A5, D2; the rest of B2 and D1 | A2 and A5: about 1 to 2.5 d by the cost scale. B2 (M) and D1 + D2 (L) are part repaid and not re-estimated. |
| **0.3.0** (Dec) | D1 (slimmer profile) | ~3 d (24/09 estimate) |
| **Next ATP** | B4 | XS |
| **Accepted** | A4, A7 (gates), D7, E3 | — |
| **Repaid** | C4, D3, D6 (in 0.1.2); B1, C1, C2, C3, C7, D4, D5, E1, E2, E4 (not released yet) | — |

**Why this order:**

- **0.1.2** holds the cheap items with high interest: they affect external contributors (who arrive in October) and the Tek5 Objective 2 deliverables (CI, test strategy).
- **0.2.0** holds what the ATP showed hurts users most: install size, grounding and the cache. The cache (D4) and the dropped socket (D5) are already fixed.
- Big-infrastructure items were to wait until the product was stable enough to be worth it. E2E in CI (B1) came early, on 09/10/2026, because the mock model server of ADR-008 made it cheap and Tek5 Objective 2.5 asks for it by the end of October.

---

## Consequences

- Reviewers can point to this list instead of re-arguing a known compromise in every PR.
- The jury and mentor can see that these are **choices with a cost and a date**, not oversights.
- When an item is repaid, mark it here as **Repaid**, with the version it ships in and the commit (or the PR, when there is one), instead of deleting it. That history is the evidence of continuous improvement.
