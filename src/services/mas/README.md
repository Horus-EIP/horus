# MAS -- Multi-Agent System Orchestrator

> For the development team. Paths such as `tests/` and `scripts/dev/` are
> relative to the git checkout and are not part of the beta archive.

The MAS service is the central orchestrator of the Horus AI platform. It manages agent registration and lifecycle, user authentication and authorization, conversations, real-time chat over WebSockets, task distribution to agents via RabbitMQ, and user administration.

## Architecture

MAS is a **FastAPI** application backed by:

- **PostgreSQL** (via SQLAlchemy 2.x + Alembic migrations) for persistent storage of users, agents, conversations, tasks, and messages.
- **Redis** for session caching and token management.
- **RabbitMQ** for asynchronous task dispatch and inter-agent delegation messaging. Tasks go to bounded `horus.work.{type}` queues (`x-max-length`, `x-overflow: reject-publish`) with publisher confirms; when a queue is full the task waits in MAS's line and the user sees "Busy, position N" (see "Bounded work queues and the agent worker" in `docs/architecture.md`).
- **Prometheus** metrics exposed at `/metrics` via `prometheus-fastapi-instrumentator`.
- **OpenTelemetry** tracing exported over OTLP to Tempo (viewable in Grafana).

On startup the application creates database tables, seeds an initial admin user, connects to RabbitMQ, and launches background tasks for agent heartbeat monitoring and task timeout checking.

## Directory Structure

```
mas/
  main.py                   # Application entry point (uvicorn main:app)
  requirements.txt          # Python dependencies of the CPU image: FastEmbed, no torch
  requirements-gpu.txt      # GPU image: requirements.txt plus torch, transformers, accelerate
  requirements-cpu.txt      # Same set as requirements.txt, kept for scripts that name it
  core/
    app.py                  # FastAPI application factory (lifespan, middleware, routers)
    config.py               # Pydantic-settings configuration loader
    logger.py               # Structured logging helpers
    middleware.py            # Request/response logging middleware
    correlation_middleware.py
    rabbitmq_manager.py     # RabbitMQ connection management
    rabbitmq_tool.py        # RabbitMQ router (delegation, health)
    agent_communication.py  # Inter-agent messaging via RabbitMQ
    llm_setup.py            # Optional LLM auto-initialization
    metrics.py              # Prometheus metric definitions
    metrics_middleware.py    # Metrics collection middleware
    tracing.py              # OpenTelemetry tracing setup
    structured_logging.py   # Structured log formatting
    hybrid_logging.py       # Hybrid console + structured logging
  db/
    database.py             # SQLAlchemy engine and session factory
    models.py               # ORM models (User, Agent, Task, Conversation, Message)
    dependency.py           # FastAPI database session dependency
    init_setup.py           # Admin user seeding on first run
    pool_monitor.py         # Connection pool monitoring
    redis_client.py         # Redis client helper
    migrate_critical_logs.py
    alembic/                # Alembic migration environment
  auth/
    routes.py               # /auth endpoints (register, token, logout)
    auth_tool_functions.py  # JWT creation, password hashing, get_current_user
    permissions.py          # Role-based access control helpers
  agents/
    routes.py               # /agents endpoints (register, unregister, details, heartbeat)
    controller.py           # Agent heartbeat background checker
    registry_tool_functions.py
  tasks/
    routes.py               # /tasks endpoints (new_task, task-result, cancel, status)
    router.py               # Task router: rules, then embeddings, then a constrained LLM call
    router_examples.yaml    # Labelled routing examples per agent identity (versioned)
    router_eval.py          # Router report on the labelled test set (python -m tasks.router_eval)
    intent_rules.py         # Greeting, small talk, arithmetic and multi-question cues
    direct_answers.py       # Fixed replies and computed arithmetic for direct answers
    arithmetic.py           # Exact arithmetic parser (no eval)
    controller.py           # Task timeout background checker
    collaborative_task.py   # Multi-agent collaborative task orchestration
    task_tool_functions.py
    status.py               # Task state machine
  chat/
    routes.py               # /chat WebSocket endpoint
    chat_tool_functions.py
  conversations/
    routes.py               # /conversations CRUD endpoints
    conversation_tool_functions.py
  users/
    routes.py               # /users admin endpoints (make-admin, remove-admin, list, stats)
    user_tool_functions.py
  schemas/
    schemas.py              # Pydantic request/response schemas
    agent_message.py        # Delegation and agent message schemas
```

Pytest suites and client scripts live under `tests/mas/` at the repository root (see `tests/mas/pytest.ini`). Local dev launcher: `scripts/dev/run-mas.sh`.

## API Endpoints

| Prefix           | Description                                          |
|-------------------|------------------------------------------------------|
| `/auth`           | User registration, JWT token issuance, logout        |
| `/agents`         | Agent registration, unregistration, details, heartbeat |
| `/tasks`          | Task creation, result submission, cancellation, status |
| `/chat`           | WebSocket real-time chat per conversation             |
| `/conversations`  | Conversation CRUD and message history                 |
| `/users`          | User administration (admin-only role management)      |
| `/rabbitmq`       | RabbitMQ health check, inter-agent delegation         |
| `/health`         | Public liveness probe with the release `version`      |
| `/`               | Health check / authenticated user info                |

Interactive API documentation is available at `/docs` (Swagger UI) when the server is running.

## Environment Variables

All configuration is loaded from environment variables. A reference file is located at `src/infra/.env.example`. Key variables:

| Variable               | Description                              | Default       |
|------------------------|------------------------------------------|---------------|
| `POSTGRES_USER`        | PostgreSQL username                      | (required)    |
| `POSTGRES_PASSWORD`    | PostgreSQL password                      | (required)    |
| `POSTGRES_DB`          | Database name                            | (required)    |
| `DB_HOST`              | Database host                            | `localhost`   |
| `DB_PORT`              | Database port                            | `5432`        |
| `JWT_SECRET_KEY`       | Secret for signing JWT tokens            | (required)    |
| `JWT_ALGORITHM`        | JWT signing algorithm                    | `HS256`       |
| `SUPER_USER_USERNAME`  | Initial admin username                   | (required)    |
| `SUPER_USER_PASSWORD`  | Initial admin password                   | (required)    |
| `REDIS_HOST`           | Redis server host                        | `localhost`   |
| `REDIS_PORT`           | Redis server port                        | `6379`        |
| `REDIS_PASSWORD`       | Redis password                           | (required)    |
| `RABBITMQ_HOST`        | RabbitMQ host                            | `localhost`   |
| `RABBITMQ_PORT`        | RabbitMQ port                            | `5672`        |
| `RABBITMQ_USER`        | RabbitMQ username                        | `guest`       |
| `RABBITMQ_PASSWORD`    | RabbitMQ password                        | `guest`       |
| `WORK_QUEUE_MAX_LENGTH` | Waiting tasks each `horus.work.{type}` queue holds before a new task waits in MAS's line as "Busy, position N". The agent reads the same variable. A queue declared earlier with another limit, or none, is declared again once it is empty | `10` |
| `LLM_AUTOINIT`         | Auto-load LLM at startup (0 to disable) | `0`           |
| `TASK_TIMEOUT`         | Global task timeout in seconds           | `300`         |
| `ROUTER_MIN_SCORE`     | Embedding stage: lowest agent score that may decide a route | `0.40` |
| `ROUTER_MIN_MARGIN`    | Embedding stage: lowest lead of the best agent over the next one | `0.10` |
| `ROUTER_LLM_MAX_TOKENS` | Token budget of the constrained LLM routing call | `32` |
| `LLM_PROMPT_TOKEN_BUDGET` | Prompt tokens one orchestrator LLM call may use before it logs a warning and counts in `mas_llm_prompts_over_budget_total` | `4096` |
| `MAS_EMBED_THREADS`    | Threads of the MiniLM embedder's ONNX Runtime session. Unset, the embedder takes `LLM_TORCH_INTRAOP_THREADS` (the installer's thread budget for MAS, 1 on the CPU profiles), and without either onnxruntime chooses | unset |
| `FASTEMBED_CACHE_PATH` | Where FastEmbed keeps the ONNX model. The image sets `/app/models/fastembed` and downloads the model there at build time | FastEmbed's default (a temp folder) |

The skill matcher (`core/skill_cache.py`) and the router's embedding stage share one embedder, `sentence-transformers/all-MiniLM-L6-v2` on FastEmbed (ONNX Runtime, CPU, no torch), loaded in the background at startup (`core/embedding_setup.py`). Its vectors match the old sentence-transformers ones (cosine 1.000000 on 336 texts, `scripts/compare-embeddings.py`) and the router report gives the same decisions with both.

### CPU and GPU images

The Dockerfile installs `requirements.txt` when the build argument `TORCH_INDEX_URL` is the CPU wheel index (`https://download.pytorch.org/whl/cpu`, set by `docker-compose.cpu.yml`), so a CPU image has no torch, transformers or sentence-transformers. On the CPU profiles MAS routes and plans through llama-server (`LLM_BACKEND=vllm`) and never needs them: `core/llm_setup.py` imports without them, and the in-process router (`LLM_BACKEND=transformers`) then fails with a message that names the missing packages. Any other index (the default `https://pypi.org/simple`) builds the GPU image from `requirements-gpu.txt`, which installs the pinned torch from that index first and keeps the in-process router available.

## Task Routing

The background job of `POST /tasks/new_task` routes each `auto` task with `tasks/router.py` (`route_task`). Three stages run in order and the first confident one decides:

1. **Rules** (`tasks/intent_rules.py`, no model). Greetings and small talk get a fixed reply (`tasks/direct_answers.py`); arithmetic is computed exactly by a small parser (`tasks/arithmetic.py`, no `eval`), never generated. A phone number or a dashed range such as `555-1234` or `2019-2020` is not arithmetic, and neither is any unspaced dash between two numbers of three or more digits or across three numbers (`1000-250`, `10-2-3`): those go to the next stages, so write `1000 - 250` to have it computed. A result above 10^100 or below 10^-100 is not answered by the rules either. "compare", "versus", "X vs Y" (not "VS Code"), "and also" or two questions of at least three words each go to `COMPLEX_TASK` and the planner.
2. **Embeddings.** The question is embedded with the MiniLM model on FastEmbed (`embed_for_routing`, the only embedder call) and compared with the labelled examples in `tasks/router_examples.yaml`, embedded once on first use (or by the preload thread). An agent's score is the mean similarity of its two closest examples. The best live agent wins when its score is at least `ROUTER_MIN_SCORE` and leads the next agent by at least `ROUTER_MIN_MARGIN`. A request made of sub-questions ("…, and who…", "…; how…") goes to `COMPLEX_TASK` when its parts confidently belong to different agents. Example groups follow the live roster: by agent name, else the live agent that shares most of the group's skills; groups of offline agents are ignored.
3. **LLM.** With `LLM_BACKEND=vllm` (llama-server or vLLM) one short call with `response_format: json_schema` lets the model choose only `SINGLE_AGENT` or `COMPLEX_TASK` and a live agent name, with `ROUTER_LLM_MAX_TOKENS` tokens. `DIRECT_ANSWER` is not offered: only the rules may answer directly. With the in-process Transformers backend the full LLM router prompt (`choose_route_with_llm`, the routing call of `select_agent_for_task`) runs as before. If this stage fails, the task falls back to the skill match and the catch-all agent.

Every decision is logged as `Routing decision` with `method` (`rules`, `embedding`, `llm`, `none`), `route`, `agent`, the top `scores` and `latency_ms`, and counted in `mas_routing_decisions_total{method,route}` and `mas_routing_decision_seconds{method}`. The latency is the time to the decision on every path: it never includes the planner that a `COMPLEX_TASK` then runs.

Measure the router on the labelled test set (`tests/mas/data/router_testset.yaml`, kept apart from the examples). From `src/services/mas`, `python -m tasks.router_eval` routes it with the rules and the embeddings and prints the accuracy, the share and p50/p95 latency of each method and the fallback rate; `--json report.json` also writes the report as JSON:

```bash
cd src/services/mas
python -m tasks.router_eval --json report.json
```

To measure on a running stack, run the report inside the MAS container. The test set is not in the MAS image, so copy it in and pass `--testset`. `--llm` also sends the undecided questions to the constrained LLM call; it needs `LLM_BACKEND=vllm` and `LLM_VLLM_URL` (llama-server or vLLM), which the container already has from `.env`:

```bash
cd src/infra
docker compose cp ../../tests/mas/data/router_testset.yaml mas:/tmp/router_testset.yaml
docker compose exec mas python -m tasks.router_eval --testset /tmp/router_testset.yaml --json /tmp/router-report.json
docker compose exec mas python -m tasks.router_eval --testset /tmp/router_testset.yaml --llm --json /tmp/router-llm.json
```

`--min-score` and `--min-margin` try other thresholds. `tests/mas/unit/test_router_model.py` (marker `requires_model`) runs the same report when FastEmbed's MiniLM model is on disk and is skipped otherwise.

Measured on 2026-10-05 (AMD Ryzen AI 9 HX 370, Windows 11, rules and embeddings, no LLM): the same 116 decisions with sentence-transformers and with FastEmbed (98.7% correct without the LLM, 33.6% sent to it); embedding-stage latency p50 9.0 ms and p95 16.1 ms before, 3.3 ms and 7.5 ms after.

## Agent answers

An agent reports `completed` (with the `sources` it cites), `not_found` (the passages did not contain the answer) or `failed` with a `reason` on `POST /tasks/task-result/` (see "Answer contract" in the agent README). MAS keeps the dispatch payload of every task it publishes in Redis (`horus:task:{task_id}:dispatch`, 24 h, without an auto-created agent's API key; a task with inline files keeps none, since their content is not kept). On a first `not_found` or `failed` MAS asks the same agent once more, under the same task id, with `attempt: 2` and another retrieval query: the user's own question for a step of a chain, otherwise the request without its filler words ("What was the Q4 2025 revenue?" becomes "Q4 2025 revenue"). It clears the task's claim, adds the first answer to the task's history with its status, and sends a `task_status` event `retrying` whose `detail` says why. A `failed` answer with no other query is tried once more as it was; a `not_found` one is not. A timeout is never tried again (it would wait as long a second time), and neither is a task whose request was cancelled.

When the second attempt is `not_found` too, or there is nothing to try, the task completes with "The documents don't contain this information." and no sources; when it fails again, the task fails as before. The answer's sources are stored in `task_results.sources` and `messages.sources` (migration `c3f9a7e1d5b2`), sent in the `result` event and returned by `GET /tasks/{task_id}` and the conversation history. A chain's final answer keeps every source of its steps, each `chunk_id` once (a source without one, such as an attached file, once per document), in the order they were first cited.

## LLM prompts

Every orchestrator prompt (`tasks/prompts.py`, `tasks/router.py`) is a system message that holds everything fixed, followed by a user message that holds what changes, the request last, so llama-server's prompt cache reuses the start of the previous prompt:

| Call (`call` label) | System message | User message |
|---|---|---|
| `task_route` (router fallback, B-92) | routing rules, then the live agents sorted by name | the question |
| `intent` (full LLM router) | routing rules and JSON schema, then the live agents sorted by name | `USER INPUT:` and the request |
| `plan` (planner) | planning rules and JSON schema, then the live agent types sorted by name | `USER INPUT:` and the request |
| `announce` (Manager plan message) | the Manager's instructions | the planned steps, then the user demand |
| `review` (Manager review after a step) | the review rules and JSON schema | the chain transcript, the remaining steps, the agent types, then the user demand |
| `aggregate` (chain synthesis) | the synthesis instructions | the specialists' output, then the original request |

No system message holds a timestamp, an id or the request. The agents are sorted because the database returns them in no fixed order (a heartbeat rewrites a row), which changed the system message, and the `agent` enum of the routing schema, from one call to the next; `tests/mas/unit/test_router.py` and `tests/mas/unit/test_decomposition_coverage.py` check that two requests with the roster in two orders send byte-identical system messages.

Every call logs `LLM prompt tokens` with `call`, `prompt_tokens`, `source` and `budget`, and observes the histogram `mas_llm_prompt_tokens{call,source}` (the "MAS Prompt Tokens per Call" panel on `/admin/metrics` divides its sum by its count). `source` is `usage` (`usage.prompt_tokens` of the llama-server or vLLM response), `tokenizer` (the tokenized prompt of the in-process router) or `estimate` (one token per 3 characters when a server sends no usage). A prompt longer than `LLM_PROMPT_TOKEN_BUDGET` tokens (default 4096) logs a warning and counts in `mas_llm_prompts_over_budget_total{call}`. To measure the average prompt per call of a run against the budget, save the agent's and MAS's metrics before it and compare after it:

```bash
python scripts/perf/prompt-tokens.py --save /tmp/before
# run the questions
python scripts/perf/prompt-tokens.py --since /tmp/before --json prompt-tokens.json
```

The script prints the calls, the average prompt tokens and the calls over budget for every `call` of both services and exits with 1 when an average is over its budget (`--agent-budget`, `--mas-budget`, default 4096).

## Local Development

### Prerequisites

- Python 3.13+
- Running PostgreSQL, Redis, and RabbitMQ instances (or use the Docker Compose stack in `src/infra/`)

### Setup

```bash
cd src/services/mas
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Run

The `scripts/dev/run-mas.sh` script loads environment variables from `src/infra/.env`, runs Alembic migrations, seeds the database, and starts the Uvicorn server on port 8000:

```bash
# From repository root
bash scripts/dev/run-mas.sh
```

Or manually:

```bash
cd db && alembic upgrade head && cd ..
uvicorn main:app --host 0.0.0.0 --port 8000 --ws-ping-interval 20 --ws-ping-timeout 120
```

## Database Migrations

Migrations are managed with Alembic. The Alembic environment lives in `db/`.

```bash
cd db

# Apply all pending migrations
alembic upgrade head

# Create a new migration after model changes
alembic revision --autogenerate -m "describe change"
```

## Running Tests

From the **repository root**:

```bash
pytest -c tests/mas/pytest.ini tests/mas -vv
```

Coverage helper:

```bash
bash scripts/test/run-mas.sh
```

Tests live in `tests/mas/` and use `pytest-asyncio` for async support. `tests/mas/pytest.ini` sets `pythonpath` to this service directory.
