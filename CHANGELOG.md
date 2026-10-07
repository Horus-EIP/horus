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

## Unreleased

The rest of the ATP fixes (Phase 0C) and the low-end hardware plan (Phases 1 to 8, B-87 to B-102): a 16 GB CPU-only machine runs one llama-server for every model, answers are never lost on a reconnect, and answers cite their sources. Measured live on 2026-10-06 on the development laptop (Ryzen AI 9 HX 370; RTX 4070 Laptop 8 GB), not yet on the reference machines: on the CPU profile 93 of 100 evaluation answers are correct with a median of 18 s per question (the old CPU setup took 14 minutes for one wrong answer), on the 8 GB GPU 96 of 100 with a median of 3 s; reports in `benchmarks/`.

### Upgrading an existing install

- Database migrations add the `queued` task status, `tasks.owner_username`, `tasks.skills_required` and `tasks.completed_at`, and the worker-claim columns. MAS also adds a missing `queued` value to a `taskstatus` enum built by the `create_all` fallback.
- The knowledge store re-embeds every stored document once on its first start (passages instead of whole files, FastEmbed instead of sentence-transformers). `KNOWLEDGE_STORE_REINDEX_ON_STARTUP=0` turns it off.
- RabbitMQ work queues get a length limit: an empty queue declared by an older version is deleted and declared again; a queue that still holds tasks is kept and limited by MAS until it drains.
- The CPU profiles download a 2.5 GB GGUF for llama-server instead of the in-process 1.5B router and 4B worker. Docker Compose 2.33.0 or later is required.
- Tasks are now read, created and cancelled per owner (B-110): a `user` sees and cancels their own tasks and every task in a conversation they own, and posts only into their own conversations; a `manager` reads and cancels every task but posts only into, and reads the history and chat of, their own conversations; an `admin` can do everything. A client that read other users' tasks with the `user` role now gets `403`, and reading another user's conversation history answers `403` instead of `404`. The full matrix is in `docs/security.md` ("Who can see what").

### Fixed

- **F27** The chat socket no longer drops after about 40 s on CPU (WebSocket ping timeout 120 s, aggregation off the event loop), and a result that finished while the browser was disconnected is shown after the reconnect (`ef05b6b`)
- **F29/F36** The task page shows the skills and the start and end times, its spinner follows the task's status, and the documents tile refreshes once after an upload (`cd8247a`)
- **F37** No horizontal page scroll at 1366x768 or on a 768 px tablet (`ae538f3`)
- **F34/F35** MAS traces appear under the service name `mas`, routing, publishing and knowledge-store calls have spans, and the admin metrics page has p50/p95 latency panels with buckets up to 1,800 s (`e5a3589`)
- The answer cache stores only validated answers and is keyed on a corpus version that every upload, delete, scan and re-index changes (`fd4ae36`)
- Attached knowledge-store files reached the agent as "(no content available)"; their text is now read and sent once (`3ba1272`)
- A fresh MAS image failed to reach Postgres because SQLAlchemy 2.1 defaults to psycopg 3; the URL now names psycopg2 and SQLAlchemy is bounded (`6851af5`)
- A direct answer to a request with attached files was dropped; such requests go to an agent (`e8c79df`)
- `--start` waits for a service that is still downloading its model instead of exiting with code 42 (`0f0b39b`)
- Found by the live tests on 2026-10-06:
  - The router's LLM fallback sent most of the questions it saw to the multi-agent path; it now treats one agent as the default (router accuracy 73.3% to 94.0% on the 116-question set) (`09e72dd`)
  - The installer's smoke test left the demo document it uploaded in the store, so the first corpus scan indexed it twice; it now deletes it (`13cdeba`)
  - Running the installer again while Horus was up stopped at the port check; ports held by the install's own containers are accepted (`04c05a7`)
  - The CPU banner said "No NVIDIA GPU was usable" when a CPU profile was forced on a machine with a usable GPU (`c67ed96`)
  - The evaluation runner never renewed its 20-minute login token, so long runs failed after about 35 questions (`23c1a08`)
  - The knowledge store never received `KNOWLEDGE_STORE_EMBED_THREADS` or `KNOWLEDGE_STORE_REINDEX_ON_STARTUP` from `.env` (`2affc76`)
- Found by the B-106 review of these commits on 2026-10-07:
  - The benchmark tools wrote absolute host paths into their reports; they now write `<models-dir>` for the models folder and the file name for other files, and the 2026-10-06 reports were cleaned in history (`4ce62d6`)
  - A database or Redis error right after a request joined the "Busy" line left it at the head of the line, so every later request for that agent type showed "Busy" until MAS restarted (B-94, `67b48a4`)
  - Publishing to RabbitMQ waited for the broker's confirm on the event loop, so a RabbitMQ disk or memory alarm froze MAS for up to 300 s; work, cancel and delegation messages are now published from a worker thread (B-94, `a7c0b0d`)
  - The knowledge store extracted PDF text and ran OCR on its event loop, so retrievals and `/health` hung during a large upload (`bd870a6`)
  - A result published while the chat page was opening its socket after adopting a running task was never shown; the page re-syncs on every socket open while a task runs, ends the turn when the task poll sees it finished, and drops a replay for a conversation the user has left (B-93, `9ea8dae`)
  - The evaluation runner did not renew its login token while polling a task, so a finished task could be reported as a timeout (`72b0b49`)
  - Answers lost their superscripts and fractions (`10⁶ m²` became `106 m2`); only full-width forms are folded now (B-62, `c6afebf`)
  - The installer said its images were signed although it checks no signature, the CPU profiles said nothing had been measured, and the candidates summary named a 100-question evaluation for a 20-question run (`5496787`)
- Who can read and change which task (B-110):
  - Any user could read any task, its result, its events and the running tasks of any conversation, and `GET /tasks/list` returned everyone's tasks; now only the task's owner (or the owner of its root task, then of its conversation), a manager or an admin, and the list holds a user's own tasks (`94228c2`)
  - Any user could post into another user's conversation and cancel another user's task; posting now needs the conversation's owner or an admin, cancelling the task's owner, a manager or an admin, and a replayed `Idempotency-Key` cannot get around it (`11667e0`)
- Follow-ups of the B-106 review (B-111):
  - Registering an agent declared its work queue on the event loop, so a RabbitMQ alarm could still freeze MAS; the declaration now runs in a worker thread (B-94, `0c23b80`)
  - Switching conversation while a request ran kept its spinner and its task poll in the new conversation; the turn is cleared and the new conversation's running tasks are adopted (`d2fff7e`)
  - `npm run typecheck` pointed at a missing tsconfig and `npm run lint` used the `next lint` that Next.js 16 removed and crashed on its config; both run now, and the small lint findings in files this branch changed are fixed (`cc10222`)
  - The installer and the tester documents said the images were signed; they now say the release workflow signs them but nothing checks the signature yet. The cpu-lean notes add that it failed the ADR-006 timing condition on the laptop run (`ff7556d`)
- Found by the review of B-110 and B-111:
  - `scripts/integration-checks/mas-agents-persistence.py` called the now-async `create_agent` without waiting for it (`804aa9a`), and `agent-delegation-integration.py` imported the tool definitions under their pre-B-99 name (`cada13a`)
  - A file attached to a message sent just before switching conversation stayed in the picker and went out with the next message in the other conversation; the picker is emptied when the message leaves and when the conversation changes (`e5246bf`)
  - Creating a task in a conversation that does not exist failed with `500`; it answers `404` and leaves the `Idempotency-Key` free (`a6f06d7`)
- Access decisions after that review:
  - A conversation's owner can read and cancel every task in it, whoever posted it, for example an admin; the chat page no longer re-asks such a task every 1.6 s (`7e5275f`)
  - The chat page stops polling a task the server answers `403` or `404` for, drops its spinner and says the task is no longer available (`94f4bc0`)
  - Managers keep reading every task but not other users' conversations: the history route answers `403` with an explicit message and the chat WebSocket gives its reason when it refuses (`aca0a9c`)

### Added

- One llama-server (`ghcr.io/ggml-org/llama.cpp:server-b11382`, Qwen3-4B-Instruct-2507 Q4_K_M) serves MAS and every agent on the CPU profiles; neither service loads a local model (B-90, `9739864`)
- `POST /tasks/new_task` answers 202 with the task id at once; task events are stored in Redis Streams, replayed with `GET /tasks/{id}/events?since=`, and a heartbeat arrives every 5 s; an `Idempotency-Key` keeps a retried request from creating a second task (B-93, `fd8778b`)
- Bounded work queues with publisher confirms ("Busy, position N"), a claim-based agent worker that never runs a task twice, and a timeout that fails the task instead of answering with a canned text (B-94, `84fc34b`)
- A router that tries rules, then embeddings, then a constrained LLM call: 98.7% of the 116 router test questions routed correctly without the LLM, in a median 2.5 ms on the development laptop (B-92, `0ca74e7`)
- Model manager: `models/manifest.json`, resumable and hash-checked downloads with mirror switching (B-95, `e9364c8`)
- Prebuilt, signed images per profile from `.github/workflows/images.yml`; the installer pulls instead of building (B-66, `736fdc2`)
- Documents are indexed as passages (`{doc_id}:{n}`) with page and offset metadata, and agents can fetch an attachment by its document id (B-97, `8670bec`)
- Answer contract: every agent answer is JSON with a status and its sources, the chat shows the sources under the answer, and MAS retries once on `not_found` or `failed` (B-98, `803176d`)
- Benchmark tooling (`scripts/benchmarks/`, `scripts/eval/` resource sampling and comparison) and ADR-006 on machines under 16 GB (B-91, `cc03ea7`)
- The installer decides the CPU profile, or refuses an unsupported machine, before any large download; it warns without AVX2 and re-detects only when the hardware changed (B-100, `5154b23`)
- Research note on integrated GPUs and NPUs (B-101, `8d91cef`) and a harness for the model candidates (B-102, `5b304e6`)
- Preflight refuses Docker Compose older than 2.33.0 and checks that ghcr.io is reachable on CPU profiles (`2cb3aa9`)
- Regression log `docs/eip/regressions.md` with F25, F28 and F7, and a What / How / When docstring on their tests (B-48, B-49, B-50, `3dc3813`)
- The prompt-cache reuse the B-102 contract probe measured, per model, in `benchmarks/README.md`; the full-stack measurement is still to do (B-99, `edc3d3b`)

### Changed

- CPU images install the CPU PyTorch wheel, and torch is pinned to 2.14.1 (B-87, `c0f89b3`); since B-96 the CPU images contain no torch at all
- Memory limits for the agent and the knowledge store, thread budgets from the physical core count, and one MAS generation at a time (B-88, `39fc78c`)
- CPU profiles use fewer passages and a 6,000-character context cap, and stream the answer (B-89, `1d5dd31`)
- Embeddings run on ONNX Runtime with FastEmbed in MAS and the knowledge store (B-96, `5055cd2`)
- Agent personas fit 300 tokens with at most 5 tools, prompts put the fixed part first so llama-server can reuse it, and prompt tokens are counted per call (B-99, `c19eff0`)
- The actions in `.github/workflows/images.yml` run at pinned commit SHAs (`f3db7d7`)
- The ADR on machines under 16 GB is ADR-006; ADR-005 is the quality-debt ADR (`d4cdf34`)
- The README calls the CPU memory thresholds planning figures kept until the reference-machine run, and `.env.example` documents `KNOWLEDGE_STORE_EMBED_THREADS` and `KNOWLEDGE_STORE_REINDEX_ON_STARTUP` (`590547a`)
- The F25 web and agent tests have their What / How / When block and are in the regression log, and the docs nav lists the validation and error-handling guide, the community outreach plan and Noah's who-made-what page (`67d9afb`)
- `docs/security.md` has one "Who can see what" matrix of roles against tasks, the task list, conversations and chat, cancelling and creating, with the two access decisions and why; `docs/api-reference.md` links to it (`ba9023f`)

## 0.1.2 (unreleased)

Fixes for what the ATP beta testers hit. Not tagged yet: the tag waits for the smoke test on a clean CPU VM and on the GPU VM (B-47).

### Fixed

- **F25** `/tasks/new` and the chat file picker no longer crash when two knowledge-store documents share a filename: each document is picked by id, and same-named copies are labelled with their upload time and size. Regression test: `web/__tests__/file-attachments.test.tsx` "regression F25 duplicate knowledge-store file names", plus `tests/mas/api/test_tasks_routes_coverage.py::TestAttachedKnowledgeStoreRefs::test_f25_same_name_documents_dispatch_with_their_doc_ids` (`0b93375`)
- **F28** Task stats count top-level tasks only, so Total Tasks matches the Recent tasks list; the always-zero `timeout` count is gone. Regression test: `tests/mas/api/test_tasks_routes_coverage.py::TestQueueStatsHelper::test_f28_queue_stats_count_root_tasks_not_subtasks` (`ff82920`)
- **F7** Back after logout no longer restores the logged-in view: logout goes through the auth context, the login redirect replaces the history entry, and a page restored from the back-forward cache checks the session again. Regression test: `web/__tests__/navbar-logout.test.tsx` "regression F7 navbar logout" and "regression F7 back-forward cache restore" (`905cedb`)
- **F20** Factual questions such as "What is the capital of Peru?" are no longer answered without retrieval: only greetings, small talk and arithmetic stay DIRECT_ANSWER, and a code post-check sends anything else to an agent. The router, planner and review prompts no longer show the model doubled braces. Test: `tests/mas/unit/test_decomposition_coverage.py::TestDirectAnswerPostCheck::test_f20_capital_of_peru_is_rerouted_to_single_agent` (`5ed7a61`)
- **F15** Deleting a document removes its stored file and every entry built from the same corpus file, and a later corpus scan does not add it back. `POST /corpus/scan?include_deleted=true` brings deleted files back on purpose. Test: `tests/knowledge_store/api/test_store_routes.py::TestStoreDelete::test_deleted_document_is_absent_from_later_queries` (`3e4e54a`)
- **Tek3 R18** Agent answers and streamed tokens are NFKC-normalised, so "Ｑ４ ２０２５ $4。2M" reads "Q4 2025 $4.2M" (`a0c0ec5`)
- **F1/T5** The installer pulls images one at a time and retries each up to 3 times. When Docker cancels a start because a service is still downloading its model, the installer waits for it to become healthy and starts the rest, instead of exiting with code 42. `docker compose config` output, which holds `.env` secrets, is kept out of `install-log.txt` (`78bb12e`)

### Added

- **F13/F14** Search field and category filter on the Knowledge Store page; `GET /categories` and `GET /file` use the same `general` label for documents without a category (`c2b3184`)
- Healthchecks for the agent (new unauthenticated `GET /health`), the knowledge store and the web client (new `GET /api/health`); dependents wait for `service_healthy` (B-59, `8d1da93`)
- One version number: `VERSION` at the repository root feeds the installer, the bundle name, the services' `/health` and OpenAPI version, the web client and the desktop shell; `scripts/ci/check-versions.py` fails CI when a copy differs (B-51, `2cdc325`)
- 100-question evaluation set on `demo_assets/` (`tests/eval/testset.yaml`) and `scripts/eval/run-eval.py`, which writes `benchmarks/<label>-<date>.json` (B-54, `084a1c2`)

### Changed

- The first-install time is given as 1.5 to 2 hours everywhere, the figure the beta testers measured (`78bb12e`)
- Task attachments carry an optional `doc_id` next to the filename; filename-only requests work as before (`0b93375`)
- `DELETE /{id}` on the knowledge store returns `deleted_ids` and `removed_files`, and answers 404 for an unknown id (`3e4e54a`)


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


