# MAS -- Multi-Agent System Orchestrator

> For the development team. Paths such as `tests/` and `scripts/dev/` are
> relative to the git checkout and are not part of the beta archive.

The MAS service is the central orchestrator of the Horus AI platform. It manages agent registration and lifecycle, user authentication and authorization, conversations, real-time chat over WebSockets, task distribution to agents via RabbitMQ, and user administration.

## Architecture

MAS is a **FastAPI** application backed by:

- **PostgreSQL** (via SQLAlchemy 2.x + Alembic migrations) for persistent storage of users, agents, conversations, tasks, and messages.
- **Redis** for session caching and token management.
- **RabbitMQ** for asynchronous task dispatch and inter-agent delegation messaging.
- **Prometheus** metrics exposed at `/metrics` via `prometheus-fastapi-instrumentator`.
- **OpenTelemetry** tracing exported over OTLP to Tempo (viewable in Grafana).

On startup the application creates database tables, seeds an initial admin user, connects to RabbitMQ, and launches background tasks for agent heartbeat monitoring and task timeout checking.

## Directory Structure

```
mas/
  main.py                   # Application entry point (uvicorn main:app)
  requirements.txt          # Python dependencies
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
| `LLM_AUTOINIT`         | Auto-load LLM at startup (0 to disable) | `0`           |
| `TASK_TIMEOUT`         | Global task timeout in seconds           | `300`         |
| `ROUTER_MIN_SCORE`     | Embedding stage: lowest agent score that may decide a route | `0.40` |
| `ROUTER_MIN_MARGIN`    | Embedding stage: lowest lead of the best agent over the next one | `0.10` |
| `ROUTER_LLM_MAX_TOKENS` | Token budget of the constrained LLM routing call | `32` |

## Task Routing

The background job of `POST /tasks/new_task` routes each `auto` task with `tasks/router.py` (`route_task`). Three stages run in order and the first confident one decides:

1. **Rules** (`tasks/intent_rules.py`, no model). Greetings and small talk get a fixed reply (`tasks/direct_answers.py`); arithmetic is computed exactly by a small parser (`tasks/arithmetic.py`, no `eval`), never generated. A phone number or a dashed range such as `555-1234` or `2019-2020` is not arithmetic. "compare", "versus", "and also" or two questions in one go to `COMPLEX_TASK` and the planner.
2. **Embeddings.** The question is embedded with the MiniLM model (`embed_for_routing`, the only embedder call) and compared with the labelled examples in `tasks/router_examples.yaml`, embedded once on first use (or by the preload thread). An agent's score is the mean similarity of its two closest examples. The best live agent wins when its score is at least `ROUTER_MIN_SCORE` and leads the next agent by at least `ROUTER_MIN_MARGIN`. A request made of sub-questions ("…, and who…", "…; how…") goes to `COMPLEX_TASK` when its parts confidently belong to different agents. Example groups follow the live roster: by agent name, else the live agent that shares most of the group's skills; groups of offline agents are ignored.
3. **LLM.** With `LLM_BACKEND=vllm` (llama-server or vLLM) one short call with `response_format: json_schema` lets the model choose only `SINGLE_AGENT` or `COMPLEX_TASK` and a live agent name, with `ROUTER_LLM_MAX_TOKENS` tokens. `DIRECT_ANSWER` is not offered: only the rules may answer directly. With the in-process Transformers backend the full LLM router (`select_agent_for_task`) runs as before. If this stage fails, the task falls back to the skill match and the catch-all agent.

Every decision is logged as `Routing decision` with `method` (`rules`, `embedding`, `llm`, `none`), `route`, `agent`, the top `scores` and `latency_ms`, and counted in `mas_routing_decisions_total{method,route}` and `mas_routing_decision_seconds{method}`.

Measure the router on the labelled test set (`tests/mas/data/router_testset.yaml`, kept apart from the examples). From `src/services/mas`, `python -m tasks.router_eval` routes it with the rules and the embeddings and prints the accuracy, the share and p50/p95 latency of each method and the fallback rate; `--json report.json` also writes the report as JSON:

```bash
cd src/services/mas
python -m tasks.router_eval --json report.json
```

`--llm` also sends the undecided questions to the constrained LLM call, which needs the OpenAI-compatible server:

```bash
LLM_BACKEND=vllm LLM_VLLM_URL=http://llm:8080/v1 python -m tasks.router_eval --llm
```

`--min-score` and `--min-margin` try other thresholds. `tests/mas/unit/test_router_model.py` (marker `requires_model`) runs the same report when the MiniLM model is on disk and is skipped otherwise.

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
