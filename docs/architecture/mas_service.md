# MAS Orchestrator — Service Reference

The MAS (Multi-Agent System) orchestrator is the central FastAPI service that receives
user requests, manages conversations, dispatches tasks to agents via RabbitMQ, and
persists state in PostgreSQL and Redis.

This page collects the operational details that used to live as long docstrings inside
source files. Code now carries short Google-style docstrings; long-form descriptions
live here.

---

## Configuration

The service loads configuration from environment variables, optionally from an `.env`
file. Search order (first match wins):

1. `src/infra/.env` — Docker Compose setup
2. `src/services/mas/.env` — standalone MAS execution
3. `src/.env` — project root for local development

Environment variables always override `.env` values. The `.env` file must never be
committed to version control.

### Required variables

| Group | Variable | Purpose |
|-------|----------|---------|
| Database | `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `DB_PORT` | PostgreSQL connection |
| Auth | `JWT_SECRET_KEY`, `JWT_ALGORITHM` | JWT signing — use a strong random key in prod |
| Initial setup | `SUPER_USER_USERNAME`, `SUPER_USER_PASSWORD` | First admin account |
| Cache | `REDIS_PASSWORD` | Redis auth |
| Messaging | `RABBITMQ_HOST` (default `localhost`) | RabbitMQ broker |
| LLM | `LLM_AUTOINIT` (default `0`) | Auto-initialise LLM at boot |

### Usage

```python
from core.config import settings
db_url = f"postgresql://{settings.postgres_user}:..."
```

---

## Logging

Logging is built on `structlog` and emits JSON lines for machine parsing (Datadog, ELK).
Every log entry carries a correlation ID propagated via `contextvars` so a single
request can be traced across middleware, route handlers, database calls, and outbound
HTTP/AMQP calls.

### Outputs

- `logs/mas_YYYYMMDD.log` — all events
- `logs/mas_errors_YYYYMMDD.log` — error events only

### API

```python
from core.logger import get_logger, log_agent_operation, log_db_operation

logger = get_logger("my_module")
logger.info("event_name", key="value")

log_agent_operation("Agent-001", "START", "Task assignment")
log_db_operation("CREATE", "users_table", "New user registered")
```

Each component (auth, db, agent, …) obtains its own logger bound with the component
name so logs can be filtered by subsystem.

---

## Database Schema

SQLAlchemy ORM models live in `src/services/mas/db/models.py`. The schema is the
system of record for users, conversations, and audit logs.

### Entities

| Entity | Purpose |
|--------|---------|
| `User` | Authenticated users with role-based access |
| `Conversation` | Chat sessions with ownership and metadata |
| `Message` | Individual turns within a conversation |
| `CriticalLog` | Audit trail for security-relevant events |

### Relationships

```
User 1 ─── N Conversation 1 ─── N Message
```

### Conventions

- Timestamps are timezone-aware and managed automatically.
- Foreign keys use cascade rules sized to the relationship (delete a conversation and its messages go with it).
- Indexes are declared for every column that participates in a WHERE clause in a hot path.
- Event listeners emit audit entries for inserts, updates, and deletes on sensitive tables.

### Security notes

- Passwords are always stored as bcrypt hashes. No plaintext path exists.
- Cascading deletes are deliberate; orphaned rows are never acceptable.
- The audit log is append-only at the application layer.

---

## Conversation Persistence

Functions in `mas/conversations/conversation_tool_functions.py`:

| Function | Purpose |
|----------|---------|
| `get_history(conv_id, db)` | Retrieve messages for one conversation, ordered by creation time and id |
| `get_full_history(conv_id, db)` | Same as above without pagination |
| `get_conversations(user_name, db)` | List conversations owned by a given user |
| `add_messages(author, message, conversation_id, db)` | Append a message; uses a savepoint so failures roll back cleanly |

### Message authors

| Author | Meaning |
|--------|---------|
| `user` | Human input |
| `assistant` | Agent or LLM output |
| `system` | System-generated notifications |

Functions accept an optional `db: Session`; when omitted they open and close their
own session, useful for standalone invocations outside a FastAPI request context.

---

## Chat WebSocket Endpoint

`src/services/mas/chat/routes.py` exposes a single WebSocket:

```
ws://host:port/chat/{conversation_id}/?token={jwt}
```

### Authentication

- JWT passed as query parameter `?token=` or as an `Authorization` header.
- Handshake validates the token; invalid/expired → close code `1008`.
- Each connection is assigned a `session_id` stored in Redis (1 hour idle TTL).

### Message protocol

Client → Server:

```json
{"type": "message", "content": "User query", "conversation_id": 1}
```

Server → Client:

```json
{
  "type": "agent_response",
  "agent_id": "agent-001",
  "content": "Processing result",
  "status": "completed",
  "timestamp": "2025-09-25T15:30:00Z"
}
```

Additional server-side message types: `task_update`, `system_notification`,
`connection_status`.

### Connection lifecycle

1. Client opens WS with token.
2. Server validates and accepts; session registered in Redis.
3. Bidirectional messaging.
4. Server broadcasts task updates, agent responses.
5. Either side closes; server cleans up Redis session.

### Error codes

| Code | Meaning |
|------|---------|
| 1000 | Normal closure |
| 1001 | Server going away |
| 1002 | Protocol error / malformed message |
| 1003 | Unsupported data type |
| 1008 | Authentication failed |
| 1009 | Message too large |
| 1011 | Server error — client should reconnect with backoff |

### Example client

```javascript
const ws = new WebSocket(`ws://localhost:8000/chat/${conversationId}/?token=${token}`);
ws.onopen = () => ws.send(JSON.stringify({type: "message", content: "Hello"}));
ws.onmessage = e => console.log(JSON.parse(e.data));
```

---

## Tasks API

Routes live under `src/services/mas/tasks/`. Split into focused modules after the
April 2026 cleanup:

| File | Responsibility |
|------|----------------|
| `tasks/router.py` | `APIRouter` aggregator |
| `tasks/endpoints/create.py` | `POST /tasks/new_task` |
| `tasks/endpoints/query.py` | `GET /tasks`, `GET /tasks/{id}` |
| `tasks/endpoints/cancel.py` | `PATCH /tasks/{id}/cancel` |
| `tasks/endpoints/share.py` | Agent result sharing |
| `tasks/endpoints/stats.py` | Queue depth and statistics |
| `tasks/status.py` | Status enum and helpers |
| `tasks/task_tool_functions.py` | Background task helpers |
| `tasks/controller.py` | Task state machine |
| `tasks/collaborative_task.py` | Cross-agent task coordination |

---

## Schemas

Pydantic v2 models in `src/services/mas/schemas/schemas.py` define the public API
surface (request / response shapes) decoupled from SQLAlchemy models. The separation
allows internal schema changes without breaking the HTTP contract.
