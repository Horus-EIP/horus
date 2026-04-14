# Architecture Documentation

## 1. Persistence Topology

The persistence layer is built on PostgreSQL, using SQLAlchemy as the ORM. The schema is designed to support multi-agent orchestration, conversation history, and user management.

### Entity-Relationship Diagram (ERD)

```mermaid
erDiagram
    USERS ||--o{ CONVERSATIONS : owns
    CONVERSATIONS ||--o{ MESSAGES : contains
    CONVERSATIONS ||--o{ TASKS : contains
    TASKS ||--o{ TASKS : "parent/child"
    TASKS ||--|| TASK_RESULTS : has
    AGENTS ||--o{ TASKS : "assigned_to"

    USERS {
        int id PK
        string username UK
        string hashed_password
        string role
    }

    CONVERSATIONS {
        int id PK
        string owner_username FK
        string name
        datetime created_at
        datetime modified_at
    }

    MESSAGES {
        int id PK
        string role
        string content
        datetime created_at
        int conversation_id FK
    }

    AGENTS {
        string id PK
        string name UK
        json skills
        string status
        datetime last_heartbeat
    }

    TASKS {
        string id PK
        int conversation_id FK
        string parent_task_id FK
        string agent_id
        string status
        string query
        int order
    }

    TASK_RESULTS {
        string id PK
        string task_id FK
        json result_data
        json history
        json future_actions
    }
```

## 2. Connection Lifecycle

The system manages connections to three primary infrastructure components: PostgreSQL, Redis, and RabbitMQ.

### PostgreSQL (Database)
- **Library:** `SQLAlchemy`
- **Lifecycle:**
  - A connection pool is initialized at application startup (`db.database.engine`).
  - **Pool Settings:** Size=10, Max Overflow=20, Timeout=30s, Recycle=1800s.
  - **Session Management:** A new `Session` is created for each request via the `get_db` dependency and closed immediately after the request completes.
  - **Monitoring:** Slow queries (>0.5s) are logged automatically.

### Redis (Cache & Pub/Sub)
- **Library:** `redis-py`
- **Lifecycle:**
  - Used for caching and potentially session management.
  - Connections are typically managed via a connection pool to ensure efficient resource usage.
  - **Configuration:** Host, Port, and Password are loaded from environment variables.

### RabbitMQ (Message Broker)
- **Library:** `pika`
- **Lifecycle:**
  - The `RabbitMQ` class in `core.rabbitmq_manager` handles connection logic.
  - **Retry Mechanism:** Implements a retry loop with exponential backoff (default 500 retries) for robust startup.
  - **Channels:** A channel is opened upon successful connection.
  - **Heartbeats:** Configured with a 600s heartbeat to maintain connection stability.

## 3. Configuration Contract

The application is configured via environment variables. These should be set in the deployment environment (e.g., `docker-compose.yml` or Kubernetes ConfigMaps).

| Category | Variable | Required | Description |
|----------|----------|----------|-------------|
| **Database** | `POSTGRES_USER` | Yes | Database username |
| | `POSTGRES_PASSWORD` | Yes | Database password |
| | `POSTGRES_DB` | Yes | Database name |
| | `DB_PORT` | Yes | Database port (e.g., 5432) |
| **Auth** | `JWT_SECRET_KEY` | Yes | Secret for signing tokens |
| | `JWT_ALGORITHM` | Yes | Algorithm (e.g., HS256) |
| **Admin** | `SUPER_USER_USERNAME` | Yes | Initial admin username |
| | `SUPER_USER_PASSWORD` | Yes | Initial admin password |
| **Redis** | `REDIS_HOST` | Yes | Redis hostname |
| | `REDIS_PORT` | Yes | Redis port |
| | `REDIS_PASSWORD` | Yes | Redis password |
| **RabbitMQ** | `RABBITMQ_HOST` | Yes | RabbitMQ hostname |
| | `RABBITMQ_PORT` | Yes | RabbitMQ port |
| | `RABBITMQ_USER` | Yes | RabbitMQ username |
| | `RABBITMQ_PASSWORD` | Yes | RabbitMQ password |
| **App** | `LLM_AUTOINIT` | No | Auto-initialize LLM (0/1) |

## 4. Sequence Diagrams

### Agent Registration Flow

```mermaid
sequenceDiagram
    participant Client
    participant API
    participant DB
    participant RabbitMQ

    Client->>API: POST /agents/register
    API->>DB: Create Agent Record (Status: Active)
    DB-->>API: Success
    API->>RabbitMQ: (Optional) Announce New Agent
    API-->>Client: Return agent_id
```

### Task Dispatch & Execution Flow

```mermaid
sequenceDiagram
    participant User
    participant API
    participant LLM
    participant DB
    participant RabbitMQ
    participant Agent
    participant WebSocket

    User->>API: POST /tasks/new_task
    API->>DB: Create Task (Status: Pending)
    API->>LLM: Analyze Request & Select Agent
    LLM-->>API: Selected Agent & Plan
    API->>DB: Update Task (Agent Assigned)
    API->>RabbitMQ: Publish Task to Agent Queue
    RabbitMQ->>Agent: Consume Task
    Agent->>Agent: Process Task
    Agent->>API: POST /tasks/task-result
    API->>DB: Store TaskResult & Update Task Status
    API->>WebSocket: Notify User of Completion
    WebSocket-->>User: Display Result
```

## 5. Architecture Decision Records (ADR)

To view the detailed reasoning behind our technology choices, please refer to the following records:
- [ADR-001: RabbitMQ](architecture/ADR-001-rabbitmq.md)
- [ADR-002: ChromaDB](architecture/ADR-002-chromadb.md)
- [ADR-003: FastAPI](architecture/ADR-003-fastapi.md)
