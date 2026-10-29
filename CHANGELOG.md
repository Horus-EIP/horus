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

The rest of the ATP fixes (Phase 0C) and the low-end hardware plan (Phases 1 to 8, B-87 to B-102): a 16 GB CPU-only machine runs one llama-server for every model, answers are never lost on a reconnect, and answers cite their sources. Measured live on 2026-10-06 on the development laptop (Ryzen AI 9 HX 370; RTX 4070 Laptop 8 GB), not yet on the reference machines: on the CPU profile 93 of 100 evaluation answers are correct with a median of 18 s per question (the old CPU setup took 14 minutes for one wrong answer), on the 8 GB GPU 96 of 100 with a median of 3 s; reports in `benchmarks/`. It also holds the repository side of Tek5 Objective 1: the contributor documents, THIRD_PARTY_NOTICES with the full licence texts and the offer of the GPL sources, Valkey instead of Redis, Grafana Alloy instead of Promtail, lock files and a licence check in CI, and the benchmark and evaluation tools as an open-source kit. The follow-ups of 08/10 add LICENSE 2.1 for that kit, log rotation and an Alloy limited to Horus's own containers, ports bound to 127.0.0.1 with a generated Valkey password, orphan clean-up on upgrade and an agent build without the local models. The second round of 08/10 generates the admin password, keeps the web client on 127.0.0.1 unless `HORUS_WEB_BIND` opens it, and makes `--uninstall` remove every container of the project and offer every volume `down` keeps. The CI fixes of 09/10 make the evaluation paths and the agent tests pass on Linux, run the service tests on the images' Python, keep the coverage figures out of artifact storage and pin every action at a Node 24 release. On 10/10 the README publishes the coverage CI measured, and the test jobs upload their reports only when they fail. Mock AI mode (09/10, a 0.2.0 feature, ADR-008) runs Horus without any AI model: a mock model server answers from the retrieved documents and computes the embeddings from their words, and spaCy and monitoring are off, so a demo or test install needs no GPU, 3.0 GiB of memory for Docker and no model download. CI runs the whole stack end to end that way. On 13/10 the code moves to the Horus-EIP organisation, `Horus-EIP/horus` on `main`: CI follows it, the team-internal documents leave for the team's private repository, and the benchmark kit gets what its public repository needs. On 14/10, B-116 gives agent workers a dedicated least-privilege MAS login instead of the super-user credentials. On 15/10, B-112 uses one MAS middleware to read or generate a correlation ID, include it in request logs, and return it in both correlation headers.

### Added

- [+] Added outreach posts for five communities and recorded feedback on asynchronous CPU-bound work, memory limits, container isolation and Python packaging (`docs/eip/community-outreach.md`; `64c7632`).

### Fixed

- [x] Refused access to another user's conversation now returns the same `404` response as a missing conversation, preventing enumeration of sequential IDs (B-117; ca7b7da).

### Upgrading an existing install

- Database migrations add the `queued` task status, `tasks.owner_username`, `tasks.skills_required` and `tasks.completed_at`, and the worker-claim columns. MAS also adds a missing `queued` value to a `taskstatus` enum built by the `create_all` fallback.
- The knowledge store re-embeds every stored document once on its first start (passages instead of whole files, FastEmbed instead of sentence-transformers). `KNOWLEDGE_STORE_REINDEX_ON_STARTUP=0` turns it off.
- RabbitMQ work queues get a length limit: an empty queue declared by an older version is deleted and declared again; a queue that still holds tasks is kept and limited by MAS until it drains.
- The CPU profiles download a 2.5 GB GGUF for llama-server instead of the in-process 1.5B router and 4B worker. Docker Compose 2.33.0 or later is required.
- Tasks are read, created and cancelled per owner (B-110): a `user` sees and cancels their own tasks and every task in a conversation they own, and posts only into their own conversations; a `manager` reads and cancels every task but posts only into, and reads the history and chat of, their own conversations; an `admin` can do everything. Reading another user's task as `user` returns `403`; refusing access to another user's conversation returns the same `404` as a missing conversation (B-117). The full matrix is in `docs/security.md` ("Who can see what").
- The cache is now Valkey 9.1.2 on a new volume, `valkey_data`, because Valkey refuses the files Redis 7.4 wrote. The old `redis_data` volume only held keys that expire within a day (sessions, task events, idempotency records): once the stack runs, delete it with `docker volume rm horus_betatest_redis_data` (the prefix is `COMPOSE_PROJECT_NAME` in `src/infra/.env`) (`9b72084`). `--uninstall` now lists it, with RedisInsight's volume, and deletes them when you answer yes (B-124, `816d592`).
- The installer's `--admin-profile` flag is gone. PgAdmin starts with `docker compose --profile dev-tools up` (`01df0ee`); RedisInsight is gone (`17b0cce`).
- Grafana Alloy replaces Promtail (`79679bc`), and RedisInsight is removed (`17b0cce`). The installer, START-HERE and the desktop app's start now pass `--remove-orphans` when `COMPOSE_PROJECT_NAME` names the project, which every release `.env` does, so the old `promtail` and `redisinsight` containers go away (B-124, `816d592`). A stack started by hand with a plain `docker compose up` keeps them, and Promtail would then send every log line to Loki a second time: run `docker compose up -d --remove-orphans` once from `src/infra`, or `docker rm -f promtail redisinsight`. On its first start Alloy reads each container's log from the beginning; Loki refuses the lines older than a week and Alloy logs a warning for them, once.
- Every service now rotates its Docker log (B-125, `b35d01f`). The next `docker compose up -d`, which the installer runs, recreates every container, and recreating a container deletes its old log, which nothing limited before (the beta's MAS log had reached about 620 MB). The lines Alloy already shipped stay in Loki. `docker compose restart` does not apply the new limits.
- Every port is now published on 127.0.0.1 only (B-123, `d586e09`): Postgres, Valkey, RabbitMQ and its management UI, MAS, the agent, vLLM, Tempo's OTLP ports and PgAdmin no longer answer other machines on the network, and neither does the web client's 3000 (B-131, `d583524`). If other machines used Horus, set `HORUS_WEB_BIND=0.0.0.0` in `src/infra/.env` before the upgrade: the web client, and through it the sign-in page and the MAS API, is then on the network again, while chat and the knowledge store still do not work from other machines (B-133).
- The installer generates the Valkey password (`REDIS_PASSWORD`, 64 hex characters) as it does `JWT_SECRET_KEY`, and so does `init-env.sh`; `.env.example` leaves it empty. Run over an install that still has the shipped `redis_password`, the installer replaces it, and the `docker compose up -d` it ends with recreates `redis`, `mas`, `agent` and `postgres`; what Valkey holds is kept (B-123, `d586e09`).
- No install keeps `admin` / `admin` (B-131, `4a006ae`). The installer and `init-env.sh` generate `SUPER_USER_PASSWORD`, `.env.example` leaves it empty, and MAS refuses to create the admin account with an empty password or `admin`. Run over an install whose `.env` still has `admin`, the installer writes a generated password, MAS gives it to the admin account when it starts if the account still has `admin`, and the installer shows it once, at the end. An account whose password was changed in Horus keeps it, and the installer says so when `.env` disagrees. A stack started by hand keeps `admin` until `SUPER_USER_PASSWORD` is set in `src/infra/.env`, and MAS logs an error at every start until then. B-116 replaces the former agent use of these admin credentials with a separate account; see the next entry.
- B-116 provisions a dedicated `agent` account with a generated `SUPER_AGENT_PASSWORD` on new installs and upgrades, and the agent container uses those credentials rather than `SUPER_USER_USERNAME` / `SUPER_USER_PASSWORD`. MAS provisions the account idempotently and always enforces the `agent` role for an existing account; legacy `.env` files can start with the old credentials until the installer generates the dedicated password. Re-registration replaces an existing worker identity regardless of its state, so restarts and stale inactive entries do not block the name. Registration is limited to the agent role's `agent:create` and `agent:execute` permissions, while the worker uses its own API key for subsequent task operations (`ac5236e`, `05178b7`).
- A database migration adds `ai_provider` to `messages` and `task_results`; older answers keep `null` (B-75, `3853b6f`).
- Nothing changes in local mode: `HORUS_AI_MODE` defaults to `local` and the stack starts as before. The new settings are unset or on by default (`MAS_EMBED_URL`, `KNOWLEDGE_STORE_EMBED_URL`, `HORUS_SPACY=on`, and `HORUS_MONITORING`, which is on in local mode), so FastEmbed and spaCy load and monitoring runs as before. `--ai mock` switches an install to mock AI mode; a prebuilt install then needs the `horus-llm-mock` image, which the release workflow builds from 0.2.0 on. A switch either way re-embeds the stored documents, and the installer waits for it.

### Fixed

- `POST /tasks/abandoned-claims` now fails tasks from an earlier run only when the authenticated agent may run the assigned agent's work; cleanup for unregistered agents remains unchanged. Queue statistics and `GET /analytics/overview` now count only tasks visible to the caller, while managers and admins retain global counts (B-114; cc7bae1).
- `compare-benchmarks.py` crashed on every llama-bench report (B-122, `3711a7b`)
- `ruff` failed CI on a `dict()` call in the agent (C408, `0ebc769`)
- Valkey answered on every network interface with the password every install shipped, `redis_password`; it is bound to 127.0.0.1 and gets a generated password (B-123, `d586e09`)
- A local build of the agent image sent the git-ignored `app/models` folder (7.6 GB of model snapshots) to Docker and baked it into the image: its build context went from 8.06 GB to 715 kB. The other images' `.dockerignore` files leave out caches, `.env` files, logs and the local Chroma index too (B-126, `5b8a9ae`)
- An upgrade left the containers of services the compose files no longer define running next to the new stack; `COMPOSE_IGNORE_ORPHANS` is respected (B-124, `816d592`)
- `scripts/dev/run-mas.sh` could not find the repository, and bound MAS to every interface; it now binds 127.0.0.1 (B-123, `d586e09`)
- Every install shipped the admin password `admin`, which the web client's sign-in page and MAS API proxy offered to whoever reached port 3000, and the installer wrote it into `install-log.txt` at the end of each install. It is generated now, shown once on screen and never logged (B-131, `4a006ae`)
- The installer rewrote a kept `REDIS_PASSWORD` without its quotes, which changes a value with `#` or `$` in it; it keeps the line as it was, as it does for the admin password (B-123, `4a006ae`)
- `--uninstall` left the containers of services whose profile is off running, `pgadmin` and, after a switch to a CPU profile, the old `vllm`, with the project's network and the images they use (B-132, `a611a26`)
- The build-context test read bracket ranges and `**` differently from Docker, so it could pass on a `.dockerignore` that Docker reads otherwise (B-126, `35ef74d`)
- Two evaluation tests failed on Linux: a test set outside the repository, given as a Windows path, was recorded with its whole folder, because Linux reads `C:\...` as a relative name. horus-bench-kit 0.1.1 keeps only the file name of a drive-letter or UNC path read on Linux or macOS, and `run-eval.py` no longer resolves the path before the kit records it (`d2a3950`)
- The bench kit's zip built on Windows differed from the one CI builds by its "made by" field (`d2a3950`)
- Tests · Agent failed 4 tests. The fake `transformers` made `_SpiralStoppingCriteria` a MagicMock that answers once and then raises `StopIteration`, and the fake generation had no `.shape` for the token count; both fakes are fixed, and `test_logger.py` puts back the logger state it changes (`93aeeae`)
- The CI test jobs failed when the artifact storage quota was full, and the coverage summary was then empty (`f15a1be`)
- Every CI run warned that six actions run on Node 20 (`14a0974`)
- The desktop release workflow still used end-of-life Node.js 20; it now uses Node.js 24 LTS (B-135, `fc7d39d8`)
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
  - Managers keep reading every task but not other users' conversations. An initial change made the history route answer `403` with an explicit message and the chat WebSocket give its reason when it refused; B-117 restores indistinguishable `404` responses for refused and missing conversations before release (`aca0a9c`)

### Added

- Release-candidate image runs now generate, verify and upload the GPL/LGPL source bundle alongside each CPU and GPU image bundle; the Alpine source fetcher falls back promptly to the GitHub APorts mirror when GitLab is unreachable. The workflow and all nine bundle artifacts completed successfully on `v0.1.2-rc8` (B-127, `07343cc`, `10453335`, `5cb1f6c`, `c2bdd37`, `05520096`).
- A dedicated, least-privilege MAS account for agent workers (B-116): the installer and `init-env.sh` generate `SUPER_AGENT_PASSWORD`, MAS creates or upgrades the account at startup, and agent containers no longer authenticate with the super-user login. The role can register agents and execute agent work; it does not receive admin permissions (`ac5236e`, `05178b7`).
- CI runs Bandit to scan Python code for security issues (B-42, `8561544`)
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
- `VERSIONING.md` (`b4e63c2`), `TESTING.md` (`2dbffb9`), ADR-005 on the quality debt we accept and when we repay it (`466f959`), `CONTRIBUTING.md` (`fd7ad5f`) and `CONTRIBUTORS.md` (`6054b3b`), checked against the code (B-29, B-30, B-32)
- The reproducibility test for someone outside Epitech, protocol and form, in `docs/eip/reproducibility-test.md` (B-39, `d7565e8`)
- `THIRD_PARTY_NOTICES`, generated by `scripts/licences/third_party_notices.py` (`--check` fails when it is out of date) and shipped in the release ZIP next to `LICENSE`; the licence inventory gains the GGUF model, the ONNX exports fastembed downloads, fastembed and the llama.cpp image (B-07, `2df368e`, `86e6e39`)
- A lock file with hashes for every requirements file (`requirements*.lock`, for the images' Python 3.11, made by `scripts/dev/lock-requirements.sh`); the images install from them with `--require-hashes` (B-09, `b816e70`)
- CI job `licences`: fails on GPL, AGPL or SSPL among the Python packages, the web client's production dependencies and the desktop app's crates, warns on LGPL, and keeps reviewed exceptions in `scripts/licences/allowlist.yaml` (B-09, `ade67e9`)
- The full licence texts in `LICENSES/` (SPDX licence list v3.29.0, plus each component's own licence file when its licence carries a copyright line) and every NOTICE a component ships in `NOTICES/`, fastembed's and onnxruntime's among them. Each entry of `THIRD_PARTY_NOTICES` names its files, `--check` fails on a missing text or NOTICE, and the release ZIP and every image (`/usr/share/doc/horus/`) carry all three (B-120, `79ac576`)
- Section 7 of `THIRD_PARTY_NOTICES`, "Source code of GPL and LGPL components": the GPL and LGPL system packages of each image with their exact versions (`--refresh system`; 69 in mas and agent, 114 in knowledge-store, 11 in web-client), psycopg2-binary and sharp's libvips, where their source is, and a three-year written offer at the maintainers' addresses. `scripts/licences/fetch-gpl-sources.py` downloads the exact sources of an image into one archive (B-121, `f3bb793`)
- `opensource/horus-bench-kit/`, horus-bench-kit 0.1.0 under Apache-2.0: `hbk-eval` with an `openai` target for any OpenAI-compatible endpoint, `hbk-llama-bench`, `hbk-compare`, `hbk-model-candidates` and `hbk-contract-probe`, standard library only, Python 3.10 or later, with documented result formats and its own example test set (B-122, `3711a7b`). ADR-007 makes it open source and amends ADR-004 for that folder only (`fb6169d`). The CI job `bench-kit` installs it fresh on Python 3.10 and 3.13, runs its tests and builds its zip, and `tests/ci/test_bench_kit.py` fails when it holds Horus content (`d9fff20`)
- ADR-008: mock AI mode is a mock model server, not mock code in the services (B-69, `8b9a394`); its update of 09/10 makes mock mode replace every model, the embeddings and spaCy too, and turn monitoring off (B-73, B-74, B-137, `2ddb32b`)
- `llm-mock`, an OpenAI-compatible mock model server on the Python standard library: `/health`, `/v1/models` (`owned_by: "horus-mock"`) and `/v1/chat/completions`, plain and streamed. It recognises MAS's calls by their schema name or `X-Horus-Purpose` (routing, plan, announce, review, aggregate), answers greetings directly and a factual question never, replies deterministically, and takes `HORUS_MOCK_LATENCY_MS` and `HORUS_MOCK_SCENARIO` (normal, slow, invalid_json, refuse, error). Its own non-root image, `horus-llm-mock`, built by `images.yml`, and a Tests · LLM mock CI job (B-71, `f7aba3b`)
- `llm-mock` answers the agent from the retrieved passages: the best 1 to 3 sentences with their `[Source: file]`, or "I don't have that information yet." below `HORUS_MOCK_MIN_SCORE`; on the demo corpus the Q4 2025 revenue question passes the smoke test's check and the capital of Peru is refused (B-72, `830496d`)
- `docker-compose.mock.yml` on top of the CPU stack, an installer `mock` profile offered below the `cpu-lean` minimum, and `--ai mock`, `--ai local` and `--ai status`, which back up `.env`, restart, run the smoke test and roll back on failure (B-76, `2bbbb0e`)
- Mock mode is always visible: MAS asks the model server what it serves and reports it at the public `GET /system/ai`, each answer stores `ai_provider`, the web client shows a banner on every page and a Simulated badge on each mock answer, the desktop app shows `AI: Mock` or `AI: Local`, and each service logs one WARNING at start (B-75, `3853b6f`)
- CI job `e2e-mock`: the CPU images and `llm-mock` built in the job, the stack started with the mock overlay, the demo corpus uploaded and `installer/smoke.py` run, with every step required to pass; and `tests/contract`, the same model assertions on the mock in CI and on a real model by hand. ADR-005 B1 repaid (B-77, `4dca7dc`)
- `docs/mock-ai.md`, a README section and ATP v8 notes for F18 to F20 in mock mode
- `llm-mock` serves `POST /v1/embeddings`: each text becomes a hashed bag of its words and word pairs, unit length, the same vector for the same text, and `dimensions` honoured (B-73, `e86c46c`)
- MAS and the knowledge store take their embeddings from an OpenAI-compatible server when `MAS_EMBED_URL` or `KNOWLEDGE_STORE_EMBED_URL` is set, and then import no FastEmbed and load no model; the mock overlay points both at `llm-mock`. Unset, FastEmbed runs as before (B-73, `7ab84f6`)
- `HORUS_SPACY=off` turns spaCy off in the knowledge store and the agent, which then extract with regular expressions; the mock overlay sets it (B-74, `e90883d`)
- Monitoring is off in mock mode unless `HORUS_MONITORING=on`: `docker-compose.monitoring-off.yml` leaves out Prometheus, Loki, Tempo and Alloy and the services' traces, and the logs, metrics and traces pages say monitoring is off (B-137, `2c026ac`)
- `--ai mock` and `--ai local` say how many documents will be re-embedded and how long that takes, ask first above 100, and wait for the knowledge store's re-index before the smoke test (B-73, `e499cf1`)
- `GET /system/ai` also reports the embeddings, spaCy and monitoring; the banner, the desktop app and each service's startup WARNING say that no AI model runs; `docs/mock-ai.md` describes the whole mode, its limits and what it needs (B-75, B-137, `b5b8da7`)
- The `mock` profile's minimum, measured on a fresh mock install: 3.0 GiB of memory for Docker, 12 GiB of free disk (23 GiB built from source). The installer offers mock mode only to machines that meet it and says so below it (B-137, `3d39fff`)
- `e2e-mock` runs the whole stack with no model and monitoring off, and fails if a service logs a model load; `tests/contract` covers the embeddings requests of MAS and the knowledge store; `test-knowledge-store` keeps one test of real search with FastEmbed and the BGE model (B-77, `d441a5d`)
- A Test coverage section in the README, with the figures of CI run #270 of 10/10/2026 (commit `cf0b622`): lines covered 93.8 % in MAS, 94.8 % in the agent and 92.1 % in the knowledge store, with each suite's gate (85, 90 and 85 %, on lines and branches together); TESTING.md gives the same figures (B-44, `588faae`)
- `.github/CODEOWNERS` (the `maintainers` team), a pull request template with its checklist, and two issue forms, Bug report and Task, with blank issues off and the kit's issues sent to `Horus-EIP/horus-bench-kit`. CONTRIBUTING says how an outside contributor works from a fork, and how we merge, which GitHub can't enforce on a private repository on the Free plan (`c505fcf`)
- What the kit's public repository needs, in `opensource/horus-bench-kit/` (B-142, `e53264d`): CONTRIBUTING.md, CODE_OF_CONDUCT.md (Contributor Covenant 2.1) and SECURITY.md; issue forms, a pull request template and CODEOWNERS; workflows for CI (tests on Python 3.10 and 3.13, and the zip), a sign-off check on every commit of a pull request, a bot that assigns an issue to whoever claims it in a comment, reminds them after 7 days without activity and frees it after 14, and a welcome for newcomers; the ruleset to import for its default branch, and its labels. Its tests are in `tests/github/`. These workflows don't run here: GitHub only runs the ones in the root `.github/workflows/`. CONTRIBUTING says the kit changes only in its public repository, and how its changes come back

### Changed

- MAS passes Alembic commands as argument lists with shell execution disabled (B-42, `aae370c`)
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
- CI runs on pushes to `Sprint#1_September2026_Tek5`, the working branch, and the README badge follows it (B-118, `8f11aaa`)
- Valkey 9.1.2 (BSD-3-Clause) replaces `redis:7`, which had become Redis 7.4 under RSALv2 or SSPL; the service is still `redis`, with the same `REDIS_*` settings (B-08, `9b72084`)
- PgAdmin and RedisInsight start only with the Compose profile `dev-tools`, which the installer never uses, and the installer no longer checks their ports (B-08, `01df0ee`)
- Every image tag names an exact version: postgres 18.6, pgadmin4 9.18.0, redisinsight 3.8.0, prometheus v3.15.0, python 3.11.17-slim and node 20.20.2-alpine, the versions the floating tags gave (B-09, `a820a0d`)
- The README says what Horus does and does not do, gives the requirements from the installer's code and ADR-006, puts the tester path first and shows the evaluation runs of 06/10/2026 (B-31, `8dc2410`)
- `docs/contributing.md` holds the code style only: branching from `develop`, two approvals, squash merges, the `test-integration` job and the links to missing pages are gone, `ci.yml` explains its `.env` workaround itself, and `scripts/docs.sh` no longer overwrites the MkDocs nav (B-32, B-33, `beed5fd`)
- ADR-004 and ADR-005 mark what this work repaid (`e3ca092`)
- The MAS image is a multi-stage build: `build-essential` and `g++` stay in the builder stage, the final stage installs no system package (its healthcheck uses Python instead of curl), and pip resolves the lock without the legacy resolver. The CPU image went from 1.32 GB to 877 MB. Test tools moved to each service's `requirements-test.txt`, which only CI installs, so no image ships pytest any more (B-67, B-46, `9a00c78`); ADR-005 C2 and C3 repaid
- Grafana Alloy v1.20.1 replaces Promtail, which reached end of life: the same Loki labels, so `/admin/logs` is unchanged, and a container without a Compose service label is no longer sent to Loki at all (B-67, `79679bc`); ADR-005 C7 repaid
- `scripts/eval/` and `scripts/benchmarks/` run on the bench kit, with every Horus value in two profile modules; their outputs stay byte for byte the same, which golden tests check (B-122, `00329ef`)
- The licence inventory marks the GPL source offer, the MAS build tools and the test tools done (`a006984`)
- `LICENSE` 2.1 (08/10/2026): `opensource/horus-bench-kit/` is not part of the Software and keeps its own Apache-2.0 licence; nothing else in the licence changed (B-122, `e9ba604`)
- Alloy reads only the containers of its own Compose project (`com.docker.compose.project` equal to `COMPOSE_PROJECT_NAME`, passed to Alloy as `HORUS_COMPOSE_PROJECT`): a second Horus install or any other Compose project on the same Docker host no longer reaches this install's Loki. The labels are unchanged, so `/admin/logs` is too (B-125, `b35d01f`)
- Docker rotates every service's log: `json-file`, at most 10 files of 40 MB per container (3 to 7 days of MAS at its usual rate, under an hour during a burst of tracebacks), set by `HORUS_LOG_MAX_SIZE` and `HORUS_LOG_MAX_FILE` in `src/infra/.env` (B-125, `b35d01f`)
- The installer passes `--remove-orphans` to every `docker compose up` it runs when the project is named, and `--uninstall` offers to delete `<project>_redis_data` and `<project>_redisinsight_data`, which `down --volumes` no longer sees (B-124, `816d592`)
- MAS creates the admin account only with a password other than an empty one or `admin`, and when it starts gives an account still on `admin` the `SUPER_USER_PASSWORD` from `.env`; an account whose password was changed in Horus keeps it. `python -m db.admin_account` runs the same check and prints only its outcome, which the installer reads once the stack is up (B-131, `4a006ae`)
- The installer and `init-env.sh` generate `SUPER_USER_PASSWORD`: 24 characters that meet the MAS password policy. The installer shows it once, at the end, on a terminal only (B-131, `4a006ae`)
- The web client is published on `${HORUS_WEB_BIND:-127.0.0.1}:3000`. `.env.example` sets `HORUS_WEB_BIND=127.0.0.1`; `0.0.0.0` opens the web client to the network on purpose, and `docs/security.md` says what that opens (B-131, `d583524`)
- After `down`, `--uninstall` removes the containers labelled with the project's name, which a turned-off profile left, and runs `down` again to free the network and the images. It does so only when `COMPOSE_PROJECT_NAME` is set (B-132, `a611a26`)
- `--uninstall` asks one question for every volume `down --volumes` keeps: the old Redis volumes, `pgadmin_data`, and `vllm_hf_cache` when no service that is on uses it, each listed with its size and what it holds (`vllm_hf_cache`: the GPU model weights, which a reinstall downloads again). A yes deletes them once the stack is down; no, `--non-interactive` or a run without a terminal deletes none and prints the `docker volume rm` command (B-132, `3ad6586`)
- CI runs the service and installer tests on the images' Python, 3.11.17, read from `src/services/PYTHON_VERSION`, and a new Tests · Installer job runs `installer/tests` on every push and pull request, with coverage (B-09, B-46, `93aeeae`)
- Each CI test job writes its suite, lines covered and test counts to its own job summary, even when its tests fail, and the coverage summary collects those lines without artifacts. No upload can fail a job; coverage and junit reports are kept 3 days, the desktop app builds 7 and the release zip 14, and the release bundle stops when one platform's app is missing (`f15a1be`)
- The MAS, agent and knowledge-store test jobs upload their coverage and junit reports only when they fail, still kept 3 days, so a green run adds nothing to the organisation's shared artifact storage quota; the figures stay in each job summary (`e074f74`)
- Each test job's summary, and the run's coverage table, give two figures: lines, and lines and branches together, the figure a job's gate compares with its minimum (the job log's `Total coverage`; the installer job has no gate); `tests/ci` checks it against a real pytest-cov gate (B-44, `047fd47`)
- The README and TESTING.md coverage tables give CI run #274 of 13/10/2026 (commit `047fd47`) for all five suites, lines and then lines and branches: MAS 93.8 and 92.69 %, agent 94.8 and 94.06 %, knowledge store 92.1 and 90.72 %, installer 79.3 and 77.00 % (no gate), LLM mock 98.0 and 97.40 % (B-44)
- `docs/mock-ai.md` gives the end-to-end job's time on GitHub, 7 min 1 s in run #274 of 13/10/2026 (build 293 s, start 38 s, smoke 2 s), where it expected a runner to be slower than the local replay
- Every action is pinned by commit SHA at a Node 24 release: checkout v7.0.1, setup-python v7.0.0, upload-artifact v7.0.1, download-artifact v8.0.1, cache v6.1.0 and setup-node v7.0.0. The Linux jobs run on `ubuntu-24.04` instead of `ubuntu-latest`, which moves to Ubuntu 26.04 from 19/10 (`14a0974`)
- horus-bench-kit 0.1.1: the path fix and the zip fix above (`d2a3950`)
- MAS and the agent name each model call in an `X-Horus-Purpose` header (`intent`, `plan`, `announce`, `review`, `aggregate`, `task_route`; `answer`, `react_step`, `grounded`, `instruction`), which real model servers ignore (B-71, `cff8243`)
- CI runs on pushes to `main` and `master`, on every pull request and by hand, no longer on `pre-release-fix` and `Sprint#1_September2026_Tek5`. A new push to a pull request cancels its older run, never a run on `main` or `master`. No pull request job reads a secret or gets a write token: the `checks` and `pull-requests` write permissions are gone. `tests/ci` checks the triggers, the cancelling, and the SHA pins of every workflow file in the repository, nested ones included (`d255edc`)
- The repository lives at `github.com/Horus-EIP/horus`, working branch `main`: the README's badge and clone commands, CONTRIBUTING, getting started, operations, VERSIONING and TESTING say so. The Epitech repository's `master` gets the work through a sync pull request (`ec98b68`)
- ADR-004 and the diffusion strategy say what the team decided: Horus stays closed, the benchmark kit is the one open-source part (ADR-007, public as `Horus-EIP/horus-bench-kit`), the agent marketplace is not decided yet, and ADR-004 is not yet validated by the study supervisor. ADR-004 also says how an outside contributor gets access in the Horus-EIP organisation (B-145, `1084a9a`, `1ab19cc`)

### Removed

- RedisInsight (SSPL), whose connection was never set up; `docs/operations.md` shows how to open `valkey-cli` in the `redis` container instead (B-08, `17b0cce`)
- The team-internal documents, which move to the team's private repository: `docs/ip_protection/`, `docs/eip_pool_tek5/`, `greenlight/`, `docs/archive/`, `beta_test_plan.md`, the Technical Track Student Guide and the dependency licence inventory spreadsheet, 39 files in all. The links to them became plain text, and git history keeps them (B-143, `9dfbc9f`)

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
