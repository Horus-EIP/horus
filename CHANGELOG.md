# Changelog

All notable changes to **Horus AI** since project inception.

Format inspired by [Keep a Changelog](https://keepachangelog.com/). Entries are reverse-chronological. The repo's commit convention is `[+]` added · `[~]` changed/refactored · `[x]` fixed · `[#]` cleanup. Each entry below cites its commit SHA.

---

## Highlights

Major tech integrations and milestones across the project life cycle:

- **2025-05**: Project bootstrapped — initial repo structure, docs, base CI.
- **2025-08**: Horus MVP base ships — service-oriented layout (`mas`, `agent`, `knowledge-store`, `web-client`), Docker Compose stack, OpenTelemetry instrumentation.
- **2025-10**: Research dossiers added on Orchestrator infrastructure, LLM infrastructure, Agent management, Observability, and Security process.
- **2026-01**: First-semester review — full multi-agent system, WebSocket chat, RAG pipeline, JWT+RBAC auth.
- **2026-02 → 2026-03**: Knowledge Store hardening — file management, smart-search, OCR, hybrid search, chunking, embedding tuning.
- **2026-04**: Observability stack consolidation — Loki + Promtail + Tempo + Prometheus + Grafana, shared RabbitMQ work queues, demo guide & cheatsheet, ADRs for RabbitMQ / ChromaDB / FastAPI, code-quality review for greenlight.
- **2026-05**: Pre-release fixes — environment + Docker tuning, agent seeding, consumer queue routing.
- **2026-06**: Grafana removed — logs, metrics, and traces now viewed in the web client's admin pages (Loki, Prometheus, Tempo backends, admin-only); `src/infra/grafana` renamed to `src/infra/observability`.
- **2026-09**: First tagged beta releases — 0.1.0 (beta installer, Tauri desktop shell, in-stack vLLM) and 0.1.1 (installer retries, CPU profiles).

Releases from 0.1.0 on have their own section, named after the tag. The monthly sections below them are the history before the first tag.

---

## 0.1.2 (unreleased)

Fixes for what the ATP beta testers hit. Not tagged yet: the tag waits for the smoke test on a clean CPU VM and on the GPU VM (B-47).

### Fixed

- **F25** `/tasks/new` and the chat file picker no longer crash when two knowledge-store documents share a filename: each document is picked by id, and same-named copies are labelled with their upload time and size. Regression test: `web/__tests__/file-attachments.test.tsx` "regression F25 duplicate knowledge-store file names", plus `tests/mas/api/test_tasks_routes_coverage.py::TestAttachedKnowledgeStoreRefs::test_f25_same_name_documents_dispatch_with_their_doc_ids` (`6db6bcc`)
- **F28** Task stats count top-level tasks only, so Total Tasks matches the Recent tasks list; the always-zero `timeout` count is gone. Regression test: `tests/mas/api/test_tasks_routes_coverage.py::TestQueueStatsHelper::test_f28_queue_stats_count_root_tasks_not_subtasks` (`0908680`)
- **F7** Back after logout no longer restores the logged-in view: logout goes through the auth context, the login redirect replaces the history entry, and a page restored from the back-forward cache checks the session again. Regression test: `web/__tests__/navbar-logout.test.tsx` "regression F7 navbar logout" and "regression F7 back-forward cache restore" (`2cb874b`)
- **F20** Factual questions such as "What is the capital of Peru?" are no longer answered without retrieval: only greetings, small talk and arithmetic stay DIRECT_ANSWER, and a code post-check sends anything else to an agent. The router, planner and review prompts no longer show the model doubled braces. Test: `tests/mas/unit/test_decomposition_coverage.py::TestDirectAnswerPostCheck::test_f20_capital_of_peru_is_rerouted_to_single_agent` (`31b0e9d`)
- **F15** Deleting a document removes its stored file and every entry built from the same corpus file, and a later corpus scan does not add it back. `POST /corpus/scan?include_deleted=true` brings deleted files back on purpose. Test: `tests/knowledge_store/api/test_store_routes.py::TestStoreDelete::test_deleted_document_is_absent_from_later_queries` (`76fcb9c`)
- **Tek3 R18** Agent answers and streamed tokens are NFKC-normalised, so "Ｑ４ ２０２５ $4。2M" reads "Q4 2025 $4.2M" (`8847dbc`)
- **F1/T5** The installer pulls images one at a time and retries each up to 3 times. When Docker cancels a start because a service is still downloading its model, the installer waits for it to become healthy and starts the rest, instead of exiting with code 42. `docker compose config` output, which holds `.env` secrets, is kept out of `install-log.txt` (`b4b0ca7`)

### Added

- **F13/F14** Search field and category filter on the Knowledge Store page; `GET /categories` and `GET /file` use the same `general` label for documents without a category (`86eacdc`)
- Healthchecks for the agent (new unauthenticated `GET /health`), the knowledge store and the web client (new `GET /api/health`); dependents wait for `service_healthy` (B-59, `0d397da`)
- One version number: `VERSION` at the repository root feeds the installer, the bundle name, the services' `/health` and OpenAPI version, the web client and the desktop shell; `scripts/ci/check-versions.py` fails CI when a copy differs (B-51, `d136093`)
- 100-question evaluation set on `demo_assets/` (`tests/eval/testset.yaml`) and `scripts/eval/run-eval.py`, which writes `benchmarks/<label>-<date>.json` (B-54, `7f0e74c`)

### Changed

- The first-install time is given as 1.5 to 2 hours everywhere, the figure the beta testers measured (`b4b0ca7`)
- Task attachments carry an optional `doc_id` next to the filename; filename-only requests work as before (`6db6bcc`)
- `DELETE /{id}` on the knowledge store returns `deleted_ids` and `removed_files`, and answers 404 for an unknown id (`76fcb9c`)


## 0.1.1 - 2026-09-07

Tag `v0.1.1` (`0fc5378`). The installer of this release still reported `0.1.0`: the bump commit only changed a document.

### Added

- Installer retries `docker compose up` once when a service aborts while still starting, offers to reclaim the Docker build cache, and takes `--skip-disk-check`; the free-disk requirement is raised to 150 GB (125 GB with a GPU) and the MAS start period is longer (`39acd3d`)
- `.gitattributes` line-ending rules, and the bundle builder normalises line endings on the way into the archive, with tests (`39acd3d`)

### Changed

- CPU profiles: the installer warns before a CPU install, and the smoke test warns instead of failing when the CPU answer is slow or wrong (`fb12a0e`)
- Stronger password policy on the server and in the web client; Hugging Face and transformers dependencies pinned; ruff pinned in CI and a `.env` provided for the MAS tests (`39acd3d`)
- Refresh `docs/eip/code-vs-docs-audit.md` (`0fc5378`)


## 0.1.0 - 2026-09-02

Tag `v0.1.0` (`18704c0`), the first tagged beta. Covers the commits after the May 2026 entries below.

### Added

- Tauri desktop shell and its release workflow; beta installer with preflight checks, a file-access consent flow, hardware profiles, start/restart/stop/uninstall commands and an end-to-end smoke test; token-gated corpus scanning in the knowledge store (`b59fe65`)
- Bundle builder `--stage` review folder; desktop releases drafted with the gh CLI on tags (`4e62673`, `8783ce0`)
- In-stack vLLM service (`vllm/vllm-openai:v0.23.0`) with a healthcheck, and vLLM token streaming in the agent (`c46243c`, `cafd6f3`)
- Task cancellation in the chat, task detail and task list pages; restart policies on every service; RabbitMQ consumer reconnection with backoff (`eb5510f`)
- Agent API key regeneration, backend and web client (`e1fd512`)
- End-to-end LLM pipeline benchmark with a baseline, and server-side generation parameters in its report (`76b0d94`, `2415eea`)
- EIP Tech 4 deliverables, performance tooling and security scan (`7aa328a`, `66c12ed`)

### Changed

- Remove Grafana; logs, metrics and traces are viewed in the web client's admin pages (`4b92d11`)
- vLLM token budgeting and anti-looping; agent telemetry in the thought-process card (`ef1755b`)
- Retrieval query separated from the LLM context; request timeouts and abort signals in the web client; agent API key caching (`a0ec4a6`)
- Installer errors explain how to read a container's own log; `COMPOSE_PROJECT_NAME=horus_betatest` keeps installs apart; release notes and first-run README refreshed (`18704c0`, `d69297d`)
- Docs and scripts consolidated into per-topic files; Python 3.13 and always-on observability (`04ba999`, `71a4d84`)
- Hermetic test suites; CI rewritten with branch coverage gates (`6f8e919`, `a149653`, `c8dde07`, `4582fed`)

### Fixed

- MANAGER role gets `TASK_READ`, so chat works for managers (`4179981`)
- Knowledge store volumes mounted at the paths the app writes to, so a rebuild no longer wipes the documents (`eb5510f`)
- Knowledge-store circular import, API test imports and patch targets; 4534 ruff errors cleared (`07c6d0f`, `84fcda5`, `a51a32a`, `743e6a7`, `e62ce2b`, `6e4c086`)


## June 2026

### Changed

- Remove Grafana; view logs, metrics, and traces in the web client's admin pages (`/admin/logs`, `/admin/metrics`, `/admin/traces`) backed by Loki, Prometheus, and Tempo — the in-app routes enforce the `admin` role; rename backend config dir `src/infra/grafana` → `src/infra/observability` (`4582fed`)


## May 2026

### Added

- Update .env and Docker configurations for agent service (`e775b7d`)


## April 2026

### Added

- Introduce stack management scripts and enhance environment setup (`452fc89`)
- Update environment configurations and enhance documentation (`f9022f9`)
- Enhance Knowledge Store API and Update Documentation (`578cca1`)
- Update environment variables for GPU and agent configurations (`f1f4f07`)
- Enhance agent registration and RAG pipeline timeout handling (`710fabd`)
- Add internal technical report forTesting and enhance agent response handling (`9c42531`)
- Adding of the greenlight directory structure (`0606a80`)
- Adding of the greenlight directory structure (`a7abbbf`)
- Adding Summary for greenlight code review (`15d9717`)
- Adding ADR Documentation for chromadb, fastapi and rabbitmq (`c9dd5cb`)
- Adding ADR Documentation for chromadb, fastapi and rabbitmq (`4ae57bf`)
- Update MAS and RAG benchmark scripts for improved functionality and documentation (`827d9ba`)
- Add docstring-length pre-commit hook and CI check script (`508bdb1`)
- Add architecture narratives and contributor code style guide (`4e45560`)
- Add demo guide and copy-paste cheatsheet for Horus live demo (`7b998f9`)
- Enhance observability stack with Loki and Promtail integration (`dbc8f5b`)
- Enhance agent service with shared RabbitMQ work queues and documentation updates (`cfdba9b`)
- Update Grafana configuration and add new documentation (`a2af311`)
- Implement default agent seeding and update RabbitMQ consumer (`7794f97`)
- Implement Update action Plan (`50ac9f8`)

### Changed

- Merge: Semester 2 Academic Cycle  (#189) (`1690ee3`)
- Restructure docs, tests, scripts and CI (`78f5c29`)
- Restructure docs, tests, scripts and CI (Part 2) (`61ef604`)
- Update configurations and enhance logging for services (`4d2b0a7`)
- feat: add code quality and coverage reports (`924348e`)
- feat: add html coverage artifacts (`4e8e2b3`)
- fix: align ruff report with configured quality gate (`decb165`)
- fix: stabilize py312 env and raise service coverage above 70 (`ea8c95f`)
- Split agent server.py into consumers + delegation_bridge modules (`552e011`)
- Split MAS db/models.py into per-model package (`f5f0985`)
- Split MAS tasks/task_tool_functions.py into focused modules (`a62e9b8`)
- Extract OpenAPI response docs from MAS route files (`02da271`)
- Reconcile agent service merge drift (`70512b1`)

### Fixed

- Update consumer test for assigned_agent_id kwarg (`566044d`)
- Fix consumers.py basic_consume queue (use WORK_QUEUE_NAME) (`983f240`)

### Cleanup

- Trim verbose comments and docstrings across MAS service (`31158b6`)
- Trim verbose comments across agent and knowledge-store services (`d43caa5`)


## January 2026

### Changed

- First Semester Review: Complete Horus Multi-Agent System Implementation (#110) (`1f3a203`)
- Refactor beta test plan documentation to enhance clarity and consistency (`331abec`)


## October 2025

### Changed

- Create Orchestrator_infrastructure.docx (`4c22c13`)
- Delete Orchestrator_infrastructure.docx (`464cb2f`)


## August 2025

### Added

- Add complete Horus MVP base and service-oriented repo layout (`f4c2fd4`)

### Changed

- Align README and CI with new src/ layout (`56a1534`)

### Fixed

- Fix knowledge-store telemetry error and RabbitMQ management warning (`d5dd717`)

### Cleanup

- Temporary no-op CI to unblock PRs (`0371d04`)


## May 2025

### Added

- Initialize Horus project with full structure, docs, and base configuration (`0ffa2ad`)

### Fixed

- Fix missing pytest-cov dependency for CI coverage (`da3f731`)


