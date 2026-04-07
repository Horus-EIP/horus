# MAS (Multi-Agent System) service

FastAPI orchestrator for agent registration, tasks, conversations, chat (WebSocket), authentication, and RBAC. Full-stack local runs use **`src/infra/docker-compose.yml`** at the repository root; this document focuses on the `src/services/mas` package.

## Architecture overview

- **Agents**: Registration, heartbeat, discovery (`agents/`)  
- **Tasks**: Create, dispatch via RabbitMQ, results (`tasks/`)  
- **Conversations and messages**: Persistence in PostgreSQL (`conversations/`, `db/`)  
- **Chat**: WebSocket endpoints (`chat/`)  
- **Auth**: JWT, bcrypt, permissions (`auth/`)  
- **Users**: Admin-oriented user routes (`users/`)  
- **Core**: Config, logging, metrics, tracing, RabbitMQ (`core/`)  

## Project structure (service root)

```
src/services/mas/
├── agents/
├── auth/
├── chat/
├── conversations/
├── core/
├── db/                 # SQLAlchemy models, Alembic, Redis helper
├── schemas/
├── tasks/
├── users/
├── main.py
├── Dockerfile
├── entrypoint.sh
└── requirements.txt
```

## Technology stack

- FastAPI, Uvicorn, Pydantic / pydantic-settings  
- PostgreSQL, SQLAlchemy, Alembic  
- Redis (sessions, token blacklist)  
- RabbitMQ (Pika)  
- Optional local LLM wiring (`core/llm_setup.py`)  

## Docker and local run

Do **not** rely on a `docker-compose.yml` inside `src/services/mas` (none is shipped). Use:

```bash
cd src/infra
cp .env.example .env
docker compose up --build
```

Typical URLs when the stack is up:

- MAS OpenAPI: http://localhost:8000/docs  
- PgAdmin: http://localhost:5433 (see `PGADMIN_*` in `.env`)  
- RabbitMQ UI: http://localhost:15672  

Defaults for database and super-user credentials are defined in **`src/infra/.env.example`** (for example `POSTGRES_DB=mas_db`, `POSTGRES_USER=postgres`).

## Configuration

See **`src/services/mas/core/config.py`** and the infra `.env.example`. Key groups: PostgreSQL, Redis, RabbitMQ, JWT, LLM flags, OpenTelemetry when enabled in Compose.

## API surface (summary)

| Area | Examples |
|------|----------|
| Auth | `POST /auth/register`, `POST /auth/token`, `POST /auth/logout` |
| Agents | `POST /agents/register`, `DELETE /agents/unregister/{agent_id}`, `GET /agents/details/` |
| Tasks | `POST /tasks/new_task/`, `POST /tasks/task-result/` |
| Conversations | Routes under `/conversations/` (see OpenAPI) |
| Chat | `WS /chat/{conversation_id}/` |

Authoritative paths and schemas: **http://localhost:8000/docs** when MAS is running.

## Testing

From the repository root:

```bash
pytest -c tests/mas/pytest.ini tests/mas -v
bash scripts/python/mas/test_code.sh
```

Example clients: `tests/mas/client_tests/`.

## Development (host)

```bash
cd src/services/mas
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Start Postgres, Redis, and RabbitMQ (e.g. via `docker compose` in `src/infra`), set `DB_HOST`, `REDIS_HOST`, `RABBITMQ_HOST` to `localhost`, then run **`scripts/dev/mas/run_local.sh`** from the repo root or `uvicorn main:app --reload --port 8000` from `src/services/mas` with correct `PYTHONPATH`.

## Monitoring

Metrics: `GET /metrics/` on MAS. Traces: OTLP to Tempo when `OTEL_*` env vars are set (see Compose). Details: [Monitoring](../../operations/monitoring.md).

## Contributing

Follow [Workflow](../workflow.md) and [Commit convention](../commit-convention.md). Match existing style (type hints, async endpoints, Pydantic models).
