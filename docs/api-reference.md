# API Reference

REST and WebSocket APIs across all three services. Use Ctrl+F to find an endpoint quickly.

---

## MAS API Reference

Complete REST and WebSocket API reference for the Multi-Agent System orchestrator.

**Base URL:** `http://<host>:8000` (or service name `mas` inside Docker).

**Metrics:** Prometheus-format metrics are exposed at **`GET /metrics`** (see `prometheus-fastapi-instrumentator` in the MAS app).

**Authentication methods used in this API:**

| Method | Header / Parameter | Description |
|--------|--------------------|-------------|
| JWT Bearer | `Authorization: Bearer <token>` | Obtained via `POST /auth/token`. Required for most endpoints. |
| Agent API Key | `X-API-Key: <key>` and `Agent-ID: <id>` | Issued at agent registration. Used by agents to call back into the MAS. |
| None | -- | Endpoint is publicly accessible. |

---

### Table of Contents

1. [Health](#1-health)
2. [Authentication](#2-authentication)
3. [Agents](#3-agents)
4. [Tasks](#4-tasks)
5. [Conversations](#5-conversations)
6. [Chat (WebSocket)](#6-chat-websocket)
7. [Users](#7-users)
8. [RabbitMQ / Agent Communication](#rabbitmq-agent-communication)

---

### 1. Health

#### GET /health

Liveness probe. Reports the service and the Horus release it runs (from `VERSION`, passed in as `HORUS_VERSION`). Calls no other service.

**Auth:** None

**Response 200:**

```json
{
  "status": "healthy",
  "service": "mas",
  "version": "0.1.2"
}
```

The Compose healthcheck of `mas` uses `POST /rabbitmq/heartbeat` instead, because it also proves the broker connection.

---

#### GET /

Verify the application is running and test JWT authentication. Returns the authenticated user's identity.

**Auth:** JWT Bearer

**Request:** No body.

**Response 200:**

```json
{
  "User": {
    "user_id": 1,
    "username": "admin",
    "role": "admin",
    "exp": 1640995200,
    "nonce": "abc123"
  },
  "message": "Authentification succeed"
}
```

**Errors:**

| Code | Detail |
|------|--------|
| `401` | `Not authenticated` -- missing or invalid JWT token. |

---

### 2. Authentication

#### POST /auth/register

Create a new user account. The password is hashed with bcrypt before storage.

**Auth:** None

**Request:** `application/json`

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| username | string | Yes | Unique username (3-50 chars). |
| password | string | Yes | Password (min 6 chars, hashed automatically). |

**Response 201:**

```json
{
  "id": 1,
  "username": "newuser123",
  "role": "user"
}
```

**Errors:**

| Code | Detail |
|------|--------|
| `409` | `User Registration Error : UNIQUE constraint failed: users.username` -- username already taken. |
| `422` | Request body validation error. |

---

#### POST /auth/token

Authenticate a user and receive a JWT access token. The token expires after 20 minutes.

**Auth:** None

**Request:** `application/x-www-form-urlencoded`

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| username | string | Yes | Username. |
| password | string | Yes | Password. |
| grant_type | string | No | OAuth2 grant type (default `password`). |
| scope | string | No | OAuth2 scope (default empty). |
| client_id | string | No | OAuth2 client ID. |
| client_secret | string | No | OAuth2 client secret. |

**Response 200:**

```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer"
}
```

**Errors:**

| Code | Detail |
|------|--------|
| `401` | `Could not validate User` -- invalid username or password. |
| `422` | Request body validation error. |
| `500` | Database or token generation error. |

---

#### POST /auth/logout

Invalidate the current JWT token by adding it to a Redis blacklist. The token stays blacklisted until its natural expiration.

**Auth:** JWT Bearer

**Request:** No body.

**Response 200:**

```json
{
  "message": "Successfully logout"
}
```

**Errors:**

| Code | Detail |
|------|--------|
| `401` | `Authentication Failed` -- missing or invalid token. |

---

### 3. Agents

#### POST /agents/register

Register a new agent with specified skills and capabilities. Ensures the **shared** RabbitMQ work queue for that agent’s `type` exists (e.g. `horus.work.general`), so multiple pool workers can consume the same queue.

**Auth:** JWT Bearer (requires `agent:create` permission -- admin only)

**Request:** `application/json`

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| name | string | Yes | Unique agent name (1-100 chars). |
| skills | string[] | Yes | List of capability tags (min 1 item). |
| description | string | Yes | Description of the agent's purpose. |
| type | string | No | Agent type: `researcher`, `analyst`, `writer`, or `general` (default `general`). |

**Response 200:**

```json
{
  "message": "agent with name DocumentAnalyzer successfully created",
  "agent_id": "8b9f1a3e-7a2c-4d7c-9b1b-2f4b2e0d2e5a",
  "api_key": "generated_api_key_base64_encoded"
}
```

**Errors:**

| Code | Detail |
|------|--------|
| `401` | `Authentication Failed` |
| `403` | Insufficient permissions (admin required). |
| `409` | `An agent already has the name 'DocumentAnalyzer'` -- duplicate name. |
| `500` | Database or RabbitMQ provisioning error. |

---

#### DELETE /agents/unregister/{agent_id}

Remove an agent from the registry. Does **not** delete the shared type work queue (other pool members may still use it). Irreversible for the registry row.

**Auth:** JWT Bearer (requires `agent:delete` permission -- admin only)

**Path parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| agent_id | string (UUID) | ID of the agent to unregister. |

**Request:** No body.

**Response 200:**

```json
{
  "message": "Agent 8b9f1a3e-7a2c-4d7c-9b1b-2f4b2e0d2e5a successfully unregistered"
}
```

**Errors:**

| Code | Detail |
|------|--------|
| `401` | `Authentication Failed` |
| `403` | Insufficient permissions (admin required). |
| `404` | `Agent {agent_id} not found` |
| `500` | Database error. |

---

#### GET /agents/details/{id}

Retrieve detailed information about a specific agent.

**Auth:** JWT Bearer (requires `agent:read` permission)

**Path parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| id | string (UUID) | ID of the agent. |

**Request:** No body.

**Response 200:**

```json
{
  "name": "DocumentAnalyzer",
  "skills": ["pdf_parsing", "text_extraction", "document_analysis", "nlp"],
  "status": "active",
  "last_heartbeat": "2025-09-25T14:32:18.567890",
  "description": "Analyzes PDF documents and extracts key information",
  "created_at": "2025-09-20T10:00:00.000000"
}
```

**Errors:**

| Code | Detail |
|------|--------|
| `401` | `Authentication Failed` |
| `404` | `Agent {id} not found` |
| `500` | Database error. |

---

#### GET /agents/details/

List all registered agents in the system.

**Auth:** JWT Bearer (requires `agent:read` permission)

**Request:** No body.

**Response 200:**

```json
[
  {
    "id": "8b9f1a3e-7a2c-4d7c-9b1b-2f4b2e0d2e5a",
    "name": "Alice",
    "skills": ["nlp", "retrieval"],
    "status": "active",
    "last_heartbeat": "2025-08-08T12:34:56.789123",
    "description": "Alice agent computes mathematical operations",
    "created_at": "2025-08-01T10:00:00.000000"
  },
  {
    "id": "3c2c6a7b-0b1a-4a4f-9d6e-1a2b3c4d5e6f",
    "name": "Bob",
    "skills": ["vision"],
    "status": "inactive",
    "last_heartbeat": "2025-08-08T12:00:00.000000",
    "description": "Bob agent handles image processing tasks",
    "created_at": "2025-08-02T11:00:00.000000"
  }
]
```

**Errors:**

| Code | Detail |
|------|--------|
| `401` | `Authentication Failed` |

---

#### POST /agents/heartbeat/{agent_id}

Update an agent's status to active and refresh its `last_heartbeat` timestamp. Called by the agent itself.

**Auth:** Agent API Key (`X-API-Key` + `Agent-ID` headers)

**Path parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| agent_id | string (UUID) | ID of the reporting agent. |

**Request:** No body.

**Response 200:**

```json
{
  "message": "Heartbeat received for the agent 8b9f1a3e-7a2c-4d7c-9b1b-2f4b2e0d2e5a"
}
```

**Errors:**

| Code | Detail |
|------|--------|
| `403` | `Agent ID mismatch` -- the API key does not belong to the given agent_id. |
| `404` | `Agent {agent_id} not found` |

---

### 4. Tasks

#### GET /tasks/list

Retrieve all tasks stored in the database.

**Auth:** JWT Bearer (requires `task:read` permission)

**Request:** No body.

**Response 200:**

```json
[
  {
    "id": "task-uuid-001",
    "conversation_id": 1,
    "parent_task_id": null,
    "agent_id": "8b9f1a3e-7a2c-4d7c-9b1b-2f4b2e0d2e5a",
    "status": "completed",
    "query": "Summarize the document",
    "order": 0,
    "created_at": "2025-09-25T10:30:00Z",
    "updated_at": "2025-09-25T10:31:00Z"
  }
]
```

**Errors:**

| Code | Detail |
|------|--------|
| `401` | `Authentication Failed` |
| `403` | Insufficient permissions. |

---

#### GET /tasks/stats/queue

Retrieve task counts by status (queued, pending, running, completed, failed, cancelled) and their total. Only top-level tasks are counted, like `GET /tasks/list`: the subtasks of a multi-agent chain are excluded.

**Auth:** JWT Bearer (requires `analytics:view` permission)

**Request:** No body.

**Response 200:**

```json
{
  "queued": 1,
  "pending": 5,
  "running": 2,
  "completed": 150,
  "failed": 1,
  "cancelled": 0,
  "total": 159
}
```

**Errors:**

| Code | Detail |
|------|--------|
| `403` | `Insufficient permissions` |

---

#### POST /tasks/new_task/

Queue a new task. The task is stored with status `queued` and the call answers `202` at once; it no longer waits for routing. A background job in MAS then routes the demand (direct answer, one agent, or a multi-agent chain planned by the Manager) and dispatches it. In `auto` mode the router tries rules first (greetings, small talk and arithmetic are answered at once, with no model), then embeddings over labelled examples, and calls the LLM only when neither is confident (see "Task Routing" in `src/services/mas/README.md`). The job uses its own database session and runs the blocking router and planner calls in a thread pool, so it keeps going after the HTTP request has ended. Follow the outcome on the conversation WebSocket, with `GET /tasks/{task_id}/events`, or with `GET /tasks/{task_id}`.

The `task_id` returned here is the one to follow for the whole request: a single-agent task keeps it, and a multi-agent chain uses it as the Manager-owned root of its subtasks.

**Auth:** JWT Bearer (requires `task:create` permission)

**Headers:**

| Header | Required | Description |
|--------|----------|-------------|
| `Idempotency-Key` | No (the web client always sends one) | 1 to 200 characters. Keys are scoped to the user and kept for 24 h in Redis (`horus:idempotency:{user_id}:{key}`). A request that reuses a key gets the task created by the first request, with the header `Idempotent-Replayed: true`, and never creates a second task. The web client generates one key per submit and reuses it on its automatic retries. If the task cannot be stored, the key is released so a retry can create it. |

**Request:** `application/json`

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| demand | string | Yes | The task description / user question. |
| conversation_id | integer | No | Conversation this task belongs to. Omit it for a standalone task. |
| skills_required | string[] | Yes | Skill tags for agent matching (may be empty in `auto` mode). |
| mode | string | No | `auto` (default), `specific_agent`, `any_with_skill` or `decompose`. |
| agent_id | string | No | Required with `mode=specific_agent`. |
| attached_files | object[] | No | Knowledge-store documents (`filename`, optional `doc_id`). |
| inline_files | object[] | No | One-shot files (`filename`, `mime`, `content_b64`), 2 MB each, 8 MB in total. |

**Response 202:**

```json
{
  "task_id": "3f6c2a9e-1b7d-4c8e-9a51-6e0b2d4f8c13",
  "status": "queued",
  "conversation_id": 1
}
```

A replayed `Idempotency-Key` returns the same body shape with the task's current status (for example `running`).

**What the background job does:**

| Outcome | Task status | Event |
|---------|-------------|-------|
| Direct answer (greeting, small talk, arithmetic) | `completed`, the answer is the task result | `result` with `route: "direct_answer"` |
| One agent | `running`, then `completed` when the agent posts its result | `progress` (`status: "running"`), later `result` with `route: "agent"` |
| Chain | the task becomes the chain root (`running`); its subtasks are dispatched one by one | Manager messages as `progress`, later `result` |
| Nothing can handle the demand (no agents, no plan) | `failed`, the reason is the task result | `error` with `route: "none"` |
| The router or the dispatch crashes | `failed` | `error` |
| The task was cancelled while it was routed | stays `canceled`, nothing is dispatched | `error` with `status: "cancelled"` |

At start-up MAS marks the tasks still `queued` (their routing job died with the previous process) as `failed` and stores an `error` event saying so. The `TASK_TIMEOUT` watchdog watches `queued` tasks as well as `running` ones.

The user message is saved to the conversation when the task is queued, before routing.

**Errors:**

| Code | Detail |
|------|--------|
| `400` | Invalid base64 in an inline file. Nothing is stored. |
| `401` | `Authentication Failed` |
| `413` | Inline file too large. Nothing is stored. |
| `422` | Request body or `Idempotency-Key` validation error. |
| `500` | `Failed to create task` (the queued task could not be stored). |

---

#### GET /tasks/{task_id}/events

Replay the events stored for a task. MAS sends every per-task WebSocket frame through one publish function, which gives it the next `seq` of the task (Redis `INCR horus:task:{task_id}:seq`), appends it to the Redis stream `horus:task:{task_id}:events` (kept 24 h after the last event, trimmed to about 10,000 entries) and only then sends it to the connected sockets. Events are therefore stored even when nobody is connected.

**Auth:** JWT Bearer (requires `task:read` permission). Only the task's owner (the user who queued it, or for older tasks the owner of its conversation) or an admin can read the events; anyone else gets `403`.

**Query parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| since | integer | 0 | Return the events with a `seq` greater than this. Pass the last `seq` you processed. |
| limit | integer | 1000 | Page size, 1 to 10,000. Call again with `since=last_seq` while `has_more` is true. |

**Response 200:**

```json
{
  "task_id": "3f6c2a9e-1b7d-4c8e-9a51-6e0b2d4f8c13",
  "status": "running",
  "since": 2,
  "events": [
    {
      "task_id": "3f6c2a9e-1b7d-4c8e-9a51-6e0b2d4f8c13",
      "seq": 3,
      "type": "progress",
      "stage": "retrieval",
      "data": {"type": "task_status", "status": "running", "detail": "Assigned to Finance-Analyst", "agent_id": "8b9f…", "agent_name": "Finance-Analyst"},
      "ts": "2026-10-05T09:30:12Z"
    },
    {
      "task_id": "3f6c2a9e-1b7d-4c8e-9a51-6e0b2d4f8c13",
      "seq": 4,
      "type": "heartbeat",
      "stage": "retrieval",
      "data": {"type": "heartbeat", "elapsed_s": 10.0},
      "ts": "2026-10-05T09:30:17Z"
    }
  ],
  "last_seq": 4,
  "has_more": false
}
```

**Event fields:**

| Field | Description |
|-------|-------------|
| `seq` | Per task, starts at 1 and increases by 1. Use it to deduplicate and to ask for what you missed. |
| `type` | `progress`, `token`, `heartbeat`, `result` or `error`. `result` and `error` end the task. |
| `stage` | `queued`, `routing`, `retrieval`, `generation`, `aggregation`, or `null` when the event does not change the stage. |
| `data` | The WebSocket frame as it was sent (see the WebSocket section). |
| `ts` | UTC time the event was stored. |

Token deltas (`reasoning.delta` steps) are stored as `token` events. The agent already coalesces them into at most one step every `AGENT_STREAM_FLUSH_INTERVAL` seconds (0.5 s by default), so a streamed answer adds about two events per second, the same order as heartbeats. Storing them lets a client that reconnects mid-answer rebuild the typing preview exactly; the stream length cap bounds a runaway task.

**Errors:**

| Code | Detail |
|------|--------|
| `403` | `Only the task's owner or an admin can read its events` |
| `404` | `Task not found` |
| `503` | `The task event store is unavailable` (Redis is down). |

---

#### POST /tasks/task-result/

Submit a completed task result from an agent. Updates the task status to COMPLETED, stores the result, handles sub-task chaining, and broadcasts the final answer via WebSocket.

**Auth:** Agent API Key (`X-API-Key` + `Agent-ID` headers)

**Request:** `application/json`

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| task_id | string | Yes | ID of the completed task. |
| result | string | Yes | The result / output text. |
| conversation_id | string | Yes | Conversation this task belongs to. |
| sources | object[] | No | Sources of the answer. Carried as-is in the task's `result` event; agents do not send them yet (B-98). |
| agent_id | string | Yes | **Task assignee** UUID (must match `Task.agent_id`). Pooled workers authenticate with their own `X-API-Key` / `Agent-ID` but set this field to the orchestrator-chosen assignee (see task message `assigned_agent_id`). |

**Response 200:**

```json
{
  "message": "Result received from agent 8b9f1a3e-7a2c-4d7c-9b1b-2f4b2e0d2e5a"
}
```

**Errors:**

| Code | Detail |
|------|--------|
| `403` | Body `agent_id` must match the task assignee; authenticated worker must be the assignee or share the same `AgentTypes` pool. |
| `404` | `Task not found` or `TaskResult not found` |
| `422` | Request body validation error. |
| `500` | Processing error (database, WebSocket, or internal). |

---

#### PATCH /tasks/task-cancel/{task_id}

Cancel a queued or running task. Updates its status to CANCELED and sends a high-priority cancellation signal to the assigned agent via RabbitMQ. For a top-level task an `error` event (`status: "cancelled"`) is stored and sent to the conversation. A task cancelled while it is still being routed is never dispatched.

**Auth:** JWT Bearer (requires `task:delete` permission)

**Path parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| task_id | string (UUID) | ID of the task to cancel. |

**Request:** No body.

**Response 200:**

```json
{
  "message": "Task task-uuid-1234 has been canceled successfully."
}
```

**Errors:**

| Code | Detail |
|------|--------|
| `400` | `Cannot interrupt a completed task` |
| `401` | `Authentication Failed` |
| `404` | `Task not found` |
| `500` | `Error Canceling task: ...` |

---

### 5. Conversations

#### POST /conversations/create-conversation/

Create a new conversation channel. Returns the auto-generated conversation ID.

**Auth:** JWT Bearer (requires `task:create` permission)

**Request:** `application/json`

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| name | string | Yes | Title for the conversation (1-255 chars). |

**Response 200:**

```json
{
  "conversation_id": 1
}
```

**Errors:**

| Code | Detail |
|------|--------|
| `400` | `Conversation creation failed` -- integrity error. |
| `401` | `Authentication Failed` |
| `403` | Insufficient permissions. |
| `422` | Request body validation error. |
| `500` | Database error. |

---

#### GET /conversations/get_history/{chat_id}

Retrieve the complete message history for a conversation. Only the owner or an admin can access.

**Auth:** JWT Bearer (requires `task:read` permission)

**Path parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| chat_id | integer | Conversation ID. |

**Request:** No body.

**Response 200:**

```json
[
  {
    "id": 1,
    "role": "user",
    "content": "Hello, can you help me?",
    "created_at": "2025-09-25T10:30:00Z"
  },
  {
    "id": 2,
    "role": "assistant",
    "content": "Hello! How can I help you?",
    "created_at": "2025-09-25T10:30:05Z"
  }
]
```

Returns an empty array `[]` if the conversation has no messages.

**Errors:**

| Code | Detail |
|------|--------|
| `401` | `Authentication Failed` |
| `403` | Insufficient permissions. |
| `404` | `Conversation {chat_id} not found` -- does not exist or not owned by caller. |
| `500` | Database error. |

---

#### GET /conversations/get-conversations/

Retrieve all conversations owned by the authenticated user.

**Auth:** JWT Bearer (requires `user:read` permission)

**Request:** No body.

**Response 200:**

```json
[
  {
    "id": 1,
    "name": "Chat with AI Assistant",
    "created_at": "2025-09-25T10:30:00Z",
    "modified_at": "2025-09-25T10:35:00Z",
    "owner_username": "user123"
  },
  {
    "id": 2,
    "name": "Technical Support Request",
    "created_at": "2025-09-24T15:45:00Z",
    "modified_at": "2025-09-24T16:00:00Z",
    "owner_username": "user123"
  }
]
```

Returns an empty array `[]` if the user has no conversations.

**Errors:**

| Code | Detail |
|------|--------|
| `401` | `Authentication Failed` |
| `403` | Insufficient permissions. |
| `500` | `Error: Failed to retrieve conversations` |

---

#### DELETE /conversations/delete-conversation/{chat_id}

Permanently delete a conversation and all associated messages (cascade). Closes any active WebSocket connections for the conversation. Only the owner or an admin can delete.

**Auth:** JWT Bearer (requires `task:delete` permission)

**Path parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| chat_id | integer | Conversation ID. |

**Request:** No body.

**Response 200:**

```json
{
  "message": "Conversation correctly deleted"
}
```

**Errors:**

| Code | Detail |
|------|--------|
| `401` | `Authentication failed` |
| `403` | Insufficient permissions or not owner. |
| `404` | `Conversation not found` |
| `409` | `Conversation has dependent records` -- foreign key constraint. |
| `500` | Database or WebSocket error. |

---

### 6. Chat (WebSocket)

#### WS /chat/{conversation_id}/

Establish a WebSocket connection for real-time bidirectional communication within a conversation.

**Auth:** JWT token passed as query parameter `?token=<jwt>` or in the `Authorization` WebSocket header.

**Connection URL:**

```
ws://<host>:8000/chat/{conversation_id}/?token=<jwt_token>
```

**Path parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| conversation_id | integer | ID of the conversation to connect to. |

**Query parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| token | string | No | JWT authentication token. Required if not provided in headers. |

**Connection flow:**

1. Client connects with a valid JWT token.
2. Server validates the token, checks `task:read` permission, verifies conversation ownership (owner or admin).
3. Connection is accepted; a session ID is created and stored in Redis.
4. Server keeps the connection open for real-time message delivery (agent responses, task updates).
5. On disconnect, the session is cleaned up from Redis.

**Incoming messages (client to server):**

```json
{
  "type": "message",
  "content": "User query or command"
}
```

**Outgoing messages (server to client):** every frame about a task is one of its stored events (see `GET /tasks/{task_id}/events`), sent as the event's `data` with the event fields added: `task_id`, `seq`, `event` (the event type), `stage` and `ts`. The frame types are listed in the WebSocket API reference below.

**WebSocket close codes:**

| Code | Meaning |
|------|---------|
| `1000` | Normal closure. |
| `1008` | Policy violation -- authentication failed, insufficient permissions, invalid conversation ID, or unauthorized access. |

**Example (JavaScript):**

```javascript
const token = "eyJhbGciOiJIUzI1NiI...";
const ws = new WebSocket(`ws://localhost:8000/chat/1/?token=${token}`);

ws.onopen = () => {
  ws.send(JSON.stringify({ type: "message", content: "Analyze this document" }));
};

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  console.log("Response:", data.content);
};
```

---

### 7. Users

#### POST /users/update_role

Update a user's role. Only admins can change roles.

**Auth:** JWT Bearer (requires `user:update` permission -- admin only)

**Request:** `application/json`

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| user_id | string | Yes | Username of the target user. |
| new_role | string | Yes | New role to assign. One of: `admin`, `user`, `manager`, `system`. |

**Response 200:**

```json
{
  "message": "Operation successfully happened"
}
```

**Errors:**

| Code | Detail |
|------|--------|
| `401` | `Authentication Failed` |
| `403` | `User already has role {role}` or insufficient permissions. |
| `404` | `User not found` |
| `500` | Database error. |

---

#### GET /users/users_list

Retrieve a list of all registered users.

**Auth:** JWT Bearer (requires `user:read` permission)

**Request:** No body.

**Response 200:**

```json
[
  { "id": 1, "username": "admin", "role": "admin" },
  { "id": 2, "username": "user1", "role": "user" }
]
```

**Errors:**

| Code | Detail |
|------|--------|
| `401` | `Authentication Failed` |
| `403` | Insufficient permissions. |

---

#### GET /users/user_details/{user_id}

Retrieve detailed information for a specific user by numeric ID.

**Auth:** JWT Bearer (requires `user:read` permission)

**Path parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| user_id | integer | Numeric user ID. |

**Request:** No body.

**Response 200:**

```json
{
  "id": 2,
  "username": "user1",
  "role": "user"
}
```

**Errors:**

| Code | Detail |
|------|--------|
| `401` | `Authentication Failed` |
| `403` | Insufficient permissions. |
| `404` | `User not found` |

---

#### GET /users/me

Retrieve the profile of the currently authenticated user.

**Auth:** JWT Bearer

**Request:** No body.

**Response 200:**

```json
{
  "id": 1,
  "username": "current_user",
  "role": "user"
}
```

**Errors:**

| Code | Detail |
|------|--------|
| `401` | `Authentication Failed` |

---

#### DELETE /users/{user_id}

Permanently delete a user account. Cannot delete yourself or the main admin account.

**Auth:** JWT Bearer (requires `user:delete` permission -- admin only)

**Path parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| user_id | integer | Numeric ID of the user to delete. |

**Request:** No body.

**Response 200:**

```json
{
  "message": "User successfully deleted",
  "username": "deleted_user"
}
```

**Errors:**

| Code | Detail |
|------|--------|
| `401` | `Authentication Failed` |
| `403` | `Cannot delete your own account` or `Cannot delete the main admin account` or insufficient permissions. |
| `404` | `User not found` |
| `500` | Internal error. |

---

#### POST /users/me/password_modification

Change the password for the currently authenticated user. Requires the old password for verification.

**Auth:** JWT Bearer

**Request:** `application/json`

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| old_password | string | Yes | Current password for verification. |
| new_password | string | Yes | New password (min 6 chars). |

**Response 200:**

```json
{
  "message": "Password successfully changed"
}
```

**Errors:**

| Code | Detail |
|------|--------|
| `400` | `Failed to change password. Please check your old password.` |
| `401` | `Authentication Failed` |
| `409` | Database error during update. |

---

#### POST /users/me/username_modification/{new_username}

Change the username for the currently authenticated user. The new username must be unique.

**Auth:** JWT Bearer

**Path parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| new_username | string | The desired new username. |

**Request:** No body.

**Response 200:**

```json
{
  "message": "Username successfully changed"
}
```

**Errors:**

| Code | Detail |
|------|--------|
| `400` | `Failed to change username. Please check the new username.` |
| `401` | `Authentication Failed` |
| `409` | `Username already exists` |
| `500` | Internal error. |

---

### 8. RabbitMQ / Agent Communication {#rabbitmq-agent-communication}

#### POST /rabbitmq/heartbeat

Verify that the RabbitMQ message broker is accessible and operational.

**Auth:** None

**Request:** No body.

**Response 200:**

```json
{
  "status": "ok"
}
```

**Response 503:**

```json
{
  "status": "unhealthy"
}
```

---

#### POST /rabbitmq/delegate

Delegate a task from one agent to another. The system selects the best target agent by matching skills, routes the work via RabbitMQ, and waits for a result (with timeout).

**Auth:** None (internal agent-to-agent endpoint)

**Request:** `application/json`

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| sender_agent_id | string | Yes | ID of the agent initiating the delegation. |
| to_agent_type | string | Yes | Skill or agent type being requested. |
| request | string | Yes | Natural-language task description. |
| data | object | No | Arbitrary payload forwarded to the delegate (default `{}`). |
| conversation_id | string | No | Conversation context (default empty). |
| delegation_chain | string[] | No | IDs of agents already in the chain, for loop detection (default `[]`). |
| delegation_context | object[] | No | Contextual breadcrumbs from prior delegations (default `[]`). |
| timeout_seconds | number | No | Maximum wait time in seconds (default `30.0`). |

**Response 200:**

```json
{
  "delegation_id": "d1e2f3a4-b5c6-7890-abcd-ef1234567890",
  "status": "completed",
  "result": "The analysis shows a 15% increase in revenue.",
  "error": null,
  "agent_id": "9a8c1d2e-3f4g-5h6i-7j8k-9l0m1n2o3p4q"
}
```

**Response 200 (timeout / error):**

```json
{
  "delegation_id": "d1e2f3a4-b5c6-7890-abcd-ef1234567890",
  "status": "timeout",
  "result": null,
  "error": "Delegation timed out after 30.0 seconds",
  "agent_id": null
}
```

---

#### POST /rabbitmq/delegation-result

Called by a delegate agent to report the result of a delegation back to the orchestrator.

**Auth:** None (internal agent-to-agent endpoint)

**Request:** `application/json`

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| delegation_id | string | Yes | ID of the delegation being resolved. |
| result | string | Yes | Textual result produced by the delegate. |
| agent_id | string | Yes | ID of the delegate agent. |

**Response 200:**

```json
{
  "status": "ok",
  "delegation_id": "d1e2f3a4-b5c6-7890-abcd-ef1234567890"
}
```

**Errors:**

| Code | Detail |
|------|--------|
| `404` | `No pending delegation with this ID` |

---

#### GET /rabbitmq/messages/{agent_id}

Retrieve persisted messages for a specific agent (for debugging and audit purposes).

**Auth:** None (internal agent-to-agent endpoint)

**Path parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| agent_id | string (UUID) | The agent whose message history to return. |

**Request:** No body.

**Response 200:**

```json
[
  {
    "id": "msg-uuid-001",
    "sender_agent_id": "agent-a",
    "receiver_agent_id": "agent-b",
    "message_type": "request",
    "content": { "task": "Summarize the report" },
    "conversation_id": "conv-uuid-001",
    "timestamp": "2025-09-25T15:30:00Z",
    "requires_response": true,
    "status": "delivered",
    "delegation_chain": [],
    "delegation_context": [],
    "parent_message_id": null,
    "timeout_seconds": 30.0
  }
]
```

Returns an empty array `[]` if no messages exist for the agent.

---

### Appendix: Schemas

#### RegistrationForm

```json
{
  "name": "string",
  "skills": ["string"],
  "description": "string",
  "type": "general | researcher | analyst | writer"
}
```

#### TaskForm

```json
{
  "demand": "string",
  "conversation_id": 0,
  "skills_required": ["string"]
}
```

#### TaskResultForm

```json
{
  "task_id": "string",
  "result": "string",
  "conversation_id": "string",
  "agent_id": "string"
}
```

#### CreateUserRequest

```json
{
  "username": "string",
  "password": "string"
}
```

#### Token

```json
{
  "access_token": "string",
  "token_type": "bearer"
}
```

#### ConversationCreation

```json
{
  "name": "string"
}
```

#### UserPasswordModification

```json
{
  "old_password": "string",
  "new_password": "string"
}
```

#### UpdateRole

```json
{
  "user_id": "string",
  "new_role": "admin | user | manager | system"
}
```

#### DelegationRequestBody

```json
{
  "sender_agent_id": "string",
  "to_agent_type": "string",
  "request": "string",
  "data": {},
  "conversation_id": "",
  "delegation_chain": [],
  "delegation_context": [],
  "timeout_seconds": 30.0
}
```

#### DelegationResultBody

```json
{
  "delegation_id": "string",
  "result": "string",
  "agent_id": "string"
}
```

#### DelegationResponse

```json
{
  "delegation_id": "string",
  "status": "completed | timeout | error | not_found",
  "result": "string | null",
  "error": "string | null",
  "agent_id": "string | null"
}
```

---

### Appendix: RBAC Permission Matrix

| Permission | admin | manager | user | system |
|------------|:-----:|:-------:|:----:|:------:|
| `user:create` | x | | | |
| `user:read` | x | x | x | |
| `user:update` | x | | | |
| `user:delete` | x | | | |
| `task:create` | x | x | x | |
| `task:read` | x | x | x | x |
| `task:execute` | x | x | | x |
| `task:delete` | x | x | x | |
| `task:approve` | x | x | | |
| `analytics:view` | x | x | x | |
| `data:export` | x | x | | |
| `system:config` | x | | | |
| `agent:create` | x | | | |
| `agent:read` | x | x | x | x |
| `agent:update` | x | | | |
| `agent:delete` | x | | | |
| `agent:execute` | x | x | x | x |

---

## Horus Knowledge Store API Reference

Vector database and document retrieval service.

**Base URL (Docker Compose default):** `http://<host>:8080` — see service `knowledge_store` in `src/infra/docker-compose.yml` (repository root).

**Path layout:** Store routes are mounted at the application root (`POST /`, `GET /`, and paths such as `/smart-search`). File routes are under `/file/...`. The FastAPI app sets `root_path="/api/knowledge-store"` for use behind a reverse proxy; when you call the container directly on port 8080, use the paths above without an extra prefix unless your gateway adds one.

Prometheus metrics are exposed at **`GET /metrics`** (no trailing slash required).

The service uses ChromaDB with the `BAAI/bge-base-en-v1.5` embedding model (see `main.py`). Every document is stored as passages of at most 1,000 characters (about 200 characters of overlap), one vector each, with the id `{doc_id}:{n}`. `GET /` returns passages; every other route works on documents.

Authentication is not enforced on these endpoints in the default configuration (treat the service as internal to the Docker network).

---

### Table of Contents

- [Health](#health)
- [Store Operations](#store-operations)
- [File Operations](#file-operations)

---

### Health

#### GET /health

Return service health status and the Horus release it runs. The Compose healthcheck of `knowledge_store` probes this route.

**Auth:** None

**Response:** `200 OK`

```json
{
  "status": "healthy",
  "service": "knowledge-store",
  "version": "0.1.2"
}
```

---

### Store Operations

#### POST /

Add a plain text document to the knowledge store. Automatic content analysis is performed (category detection, entity extraction, topic identification, summarization).

**Auth:** None (internal service)

**Request Body:** `application/json`

| Field              | Type     | Required | Description                                |
|--------------------|----------|----------|--------------------------------------------|
| id                 | string   | Yes      | Unique document identifier                 |
| title              | string   | Yes      | Document title                             |
| content            | string   | Yes      | Full text content                          |
| size               | integer  | Yes      | Content size in bytes                      |
| auto_category      | string   | No       | Category override (default: auto-detected) |
| auto_type          | string   | No       | Document type override                     |
| auto_summary       | string   | No       | Summary override                           |
| entities           | object   | No       | Pre-extracted entities (people, companies, amounts, dates) |
| topics             | string[] | No       | Topic keywords                             |
| confidence_score   | float    | No       | Analysis confidence 0--1 (default: `0.0`)  |
| user_category      | string   | No       | User-assigned category                     |
| user_tags          | string[] | No       | User-assigned tags                         |
| is_chunk           | boolean  | No       | Whether this is a chunk of a larger document |
| parent_id          | string   | No       | Parent document ID when `is_chunk` is true |

**Response:** `200 OK`

```json
{
  "status": "document added",
  "id": "123456",
  "auto_analysis": {
    "category": "finance",
    "entities": {
      "people": ["John Doe"],
      "companies": ["Acme Corp"],
      "amounts": ["$1,000,000"],
      "dates": ["2025-01-15"]
    },
    "topics": ["revenue", "growth"],
    "summary": "Quarterly financial results showing growth..."
  }
}
```

---

#### GET /

Query the knowledge store for relevant passages using semantic search with optional metadata filters. `n_results` counts passages, so one document can appear several times. Each passage's id is its chunk id `{doc_id}:{n}`, and its metadata carries:

| Field | Description |
|-------|-------------|
| doc_id | Id of the document the passage belongs to |
| title | Document title (file name) |
| source_path | Corpus path for a scanned file, empty for an upload |
| chunk_index | Position of the passage in the document, from 0 |
| char_start, char_end | Where the passage sits in the extracted text |
| page | PDFs only: the page the passage starts on |
| category | Document category |
| embed_model | Embedder that produced the passage's vector |

The passage with `chunk_index` 0 also carries the document-level data: `date`, `size`, `chunk_count` and the auto-analysis.

**Auth:** None (internal service)

**Query Parameters:**

| Parameter | Type    | Required | Description                                          |
|-----------|---------|----------|------------------------------------------------------|
| query     | string  | Yes      | Search query text                                    |
| n_results | integer | No       | Number of results to return (default: `1`)           |
| filters   | string  | No       | JSON string with ChromaDB where-clause filters       |

**Response:** `200 OK`

```json
{
  "ids": [["3f9a2c:4", "b71e09:0"]],
  "distances": [[0.1, 0.2]],
  "metadatas": [[
    { "doc_id": "3f9a2c", "title": "Doc 1.pdf", "chunk_index": 4, "char_start": 3200, "char_end": 4180, "page": 2, "source_path": "", "category": "finance", "embed_model": "sentence-transformers:BAAI/bge-base-en-v1.5" },
    { "doc_id": "b71e09", "title": "Doc 2.md", "chunk_index": 0, "char_start": 0, "char_end": 950, "source_path": "policies/doc2.md", "category": "hr", "embed_model": "sentence-transformers:BAAI/bge-base-en-v1.5" }
  ]],
  "documents": [[
    "Passage of Doc 1",
    "Passage of Doc 2"
  ]]
}
```

**Errors:**

- `400` -- Invalid filters JSON format
- `404` -- No results found
- `500` -- Query execution failure

---

#### DELETE /{id}

Remove a document from the knowledge store by its ID. This is the call behind the trash icon on the Knowledge Store page. One call removes:

- every entry whose ID is `id`, or whose `doc_id` metadata is `id`: every passage of the document;
- every other entry indexed from the same corpus file (same `source_path`), such as an older version left by a re-scan;
- the uploaded file in `documents/`, unless another entry still points at the same file.

A deleted corpus file goes on the deleted list (`chroma_data/deleted_sources.json`, next to the Chroma index). A later `POST /corpus/scan` skips it with the decision `skipped_deleted`, even after the file is edited, and also skips an identical copy at another path. To index it again, run the scan with `include_deleted=true`, or upload the file from the UI.

**Auth:** None (internal service)

**Path Parameters:**

| Parameter | Type   | Description               |
|-----------|--------|---------------------------|
| id        | string | Unique document identifier |

**Response:** `200 OK`

```json
{
  "status": "Document deleted",
  "deleted_ids": ["123456"],
  "removed_files": ["pdf/report.pdf"]
}
```

`removed_files` is relative to `documents/`.

**Errors:**

- `404` -- Document not found or deletion failed

---

#### POST /smart-search

Search documents with metadata filters including category, entities, and confidence score. Each document appears once, with its best-matching passage; `n_results` counts documents. `categories` filters passages; `entities`, `min_confidence` and `entity_type` filter on the document's analysis, stored on its first passage.

**Auth:** None (internal service)

**Request Body:** `application/json`

| Field          | Type     | Required | Description                                      |
|----------------|----------|----------|--------------------------------------------------|
| query          | string   | Yes      | Search query text                                |
| n_results      | integer  | No       | Max results to return (1--50, default: `5`)      |
| categories     | string[] | No       | Filter by document categories                    |
| entities       | string[] | No       | Filter by entity names                           |
| min_confidence | float    | No       | Minimum confidence score filter (0.0--1.0)       |
| entity_type    | string   | No       | Filter by entity type (e.g., `people`)           |

**Response:** `200 OK`

```json
{
  "query": "financial report",
  "filters": { "category": { "$eq": "finance" } },
  "total": 3,
  "results": {
    "ids": ["q1", "q2", "annual"],
    "chunk_ids": ["q1:2", "q2:0", "annual:5"],
    "documents": ["Best passage of Q1", "Best passage of Q2", "Best passage of the summary"],
    "metadatas": [
      { "doc_id": "q1", "title": "Q1 Report", "chunk_index": 2, "category": "finance", "auto_summary": "..." },
      { "doc_id": "q2", "title": "Q2 Report", "chunk_index": 0, "category": "finance", "auto_summary": "..." },
      { "doc_id": "annual", "title": "Annual Summary", "chunk_index": 5, "category": "finance", "auto_summary": "..." }
    ],
    "distances": [0.12, 0.18, 0.25]
  }
}
```

**Errors:**

- `404` -- No results found or no results within distance threshold
- `500` -- Search execution failure

---

#### GET /search-by-entity

Search for documents containing a specific named entity. Each document appears once, with its best-matching passage; `ids` are document ids and `chunk_ids` the passages.

**Auth:** None (internal service)

**Query Parameters:**

| Parameter   | Type    | Required | Description                                               |
|-------------|---------|----------|-----------------------------------------------------------|
| entity      | string  | Yes      | Entity value to search for (e.g., a person's name)       |
| entity_type | string  | Yes      | One of: `people`, `companies`, `amounts`, `dates`        |
| n_results   | integer | No       | Max results to return (default: `5`)                     |

**Response:** `200 OK`

```json
{
  "entity": "John Doe",
  "entity_type": "people",
  "filter": { "entities_people": { "$contains": "John Doe" } },
  "total": 2,
  "results": {
    "ids": [["contract-a", "report-b"]],
    "chunk_ids": [["contract-a:0", "report-b:3"]],
    "documents": [["Passage of contract A", "Passage of report B"]],
    "metadatas": [[{ "title": "Contract A" }, { "title": "Report B" }]],
    "distances": [[0.05, 0.12]]
  }
}
```

**Errors:**

- `400` -- Invalid entity_type (must be one of: `people`, `companies`, `amounts`, `dates`)
- `404` -- No documents found for this entity
- `500` -- Search execution failure

---

#### GET /categories

Get all document categories in the knowledge store with document counts.

**Auth:** None (internal service)

**Response:** `200 OK`

```json
{
  "total_documents": 42,
  "categories": [
    { "category": "finance", "count": 15 },
    { "category": "technical", "count": 12 },
    { "category": "legal", "count": 8 },
    { "category": "general", "count": 7 }
  ]
}
```

Categories are sorted by count in descending order. Counts are documents, not passages. A document stored without a category is counted as `general`, the same label `GET /file` shows for it.

**Errors:**

- `500` -- Retrieval failure

---

#### GET /corpus-version

Return an opaque version of the indexed corpus. It changes whenever an entry is added to or removed from the index: every upload (`POST /file`, `POST /file/{type}`, `POST /`), every delete (`DELETE /{id}`), and every `POST /corpus/scan` that ingests a file or replaces an older version of one. A scan that skips every file, a dry run, a query or a listing leaves it unchanged. The version lives in memory, so a restart of the service also changes it. `POST /corpus/reindex` (run by `scripts/reindex-knowledge-store.py`) changes it for every document it re-indexes. Restart the service after a re-index done outside it, such as `scripts/migrate-embeddings.py`.

The agent's response cache (`AGENT_RESPONSE_CACHE=1`) puts this version in its cache key, so an answer cached before a change is never served after it. The agent reads the version again after at most `AGENT_RESPONSE_CACHE_VERSION_TTL` seconds (default `5`). When the read fails, the agent answers without the cache.

**Auth:** None (internal service). Unlike the `/corpus` routes, it needs no `X-Corpus-Token`.

**Response:** `200 OK`

```json
{
  "version": "3f9a2c1e7b4d-12",
  "changed_at": "2026-10-05T09:30:12.000000+00:00"
}
```

---

#### POST /upload

Upload a file (PDF, DOCX, TXT), extract its text content, run auto-analysis, and chunk the text for storage.

**Auth:** None (internal service)

**Request Body:** `multipart/form-data`

| Field | Type | Required | Description                               |
|-------|------|----------|-------------------------------------------|
| file  | file | Yes      | File to upload (PDF, DOCX, TXT supported) |

**Response:** `200 OK`

```json
{
  "filename": "example.pdf",
  "auto_analysis": {
    "topics": ["AI", "Technology"],
    "summary": "An example document about AI..."
  },
  "chunks": [
    "Chunk 1 content...",
    "Chunk 2 content..."
  ],
  "total_chunks": 2
}
```

**Errors:**

- `400` -- File processing error (unsupported format, corrupt file, etc.)

---

### File Operations

#### POST /file

Upload multiple files to the knowledge store. Each file is saved to disk, text is extracted, auto-analysis is performed, and the document is indexed in ChromaDB.

**Auth:** None (internal service)

**Request Body:** `multipart/form-data`

| Field | Type   | Required | Description                                    |
|-------|--------|----------|------------------------------------------------|
| files | file[] | Yes      | One or more files (PDF, DOCX, TXT supported)  |

**Response:** `200 OK`

Returns a list of results, one per file. Failed files include an `error` field instead of success fields.

```json
[
  {
    "filename": "doc.pdf",
    "doc_id": "a1b2c3d4e5f6",
    "stored_at": "/path/to/doc.pdf",
    "auto_analysis": {
      "category": "finance",
      "topics": ["revenue"],
      "summary": "Financial report..."
    }
  },
  {
    "filename": "corrupt.pdf",
    "error": "Unable to extract text from PDF"
  }
]
```

---

#### GET /file

List all documents currently indexed in the knowledge store, one entry per document however many passages it was split into. Returns **analysis metadata and short text only** (auto-summary from ingest, category, type, and a capped excerpt). Full document bodies are not included so large files do not blow up the UI or agents listing the store.

**Auth:** None (internal service)

**Response:** `200 OK`

```json
{
  "documents": [
    {
      "id": "123",
      "title": "doc.pdf",
      "date": "2025-01-01",
      "size": 1024,
      "summary": "Auto-generated summary from ContentAnalyzer (or excerpt if empty).",
      "excerpt": "First ~400 characters of extracted text...",
      "category": "general",
      "document_type": "unknown",
      "confidence_score": 0.85
    }
  ]
}
```

**Errors:**

- `404` -- Error retrieving files from the store

---

#### GET /file/{doc_id}/text

Return the full text of one document by its id, rebuilt from its passages. The agent reads an attached knowledge-store file through this route when the task carries the file's `doc_id`, and falls back to `GET /file/resolve` by filename otherwise.

**Auth:** None (internal service)

**Path Parameters:**

| Parameter | Type   | Description  |
|-----------|--------|--------------|
| doc_id    | string | Document id  |

**Response:** `200 OK`

```json
{
  "doc_id": "a1b2c3d4e5f6",
  "title": "doc.pdf",
  "category": "finance",
  "chunk_count": 3,
  "text": "Full document text..."
}
```

**Errors:**

- `404` -- No document with that id
- `500` -- The index could not be read

---

#### DELETE /file/{filename}

Delete a file from the physical storage by its filename. Searches the `documents` directory recursively.

**Auth:** None (internal service)

**Path Parameters:**

| Parameter | Type   | Description           |
|-----------|--------|-----------------------|
| filename  | string | Name of the file      |

**Response:** `200 OK`

```json
{
  "msg": "doc.pdf deleted"
}
```

**Errors:**

- `404` -- File not found

---

#### POST /file/{type}

Upload a single file specifying its type explicitly, convert to text, analyze, and store. Supports type-specific conversion pipelines.

**Auth:** None (internal service)

**Path Parameters:**

| Parameter | Type   | Description                                   |
|-----------|--------|-----------------------------------------------|
| type      | string | File type: `pdf`, `docx`, or `image`          |

**Query Parameters:**

| Parameter | Type   | Required | Description                  |
|-----------|--------|----------|------------------------------|
| doc_id    | string | Yes      | Pre-assigned document ID     |

**Request Body:** `multipart/form-data`

| Field | Type | Required | Description          |
|-------|------|----------|----------------------|
| file  | file | Yes      | File to upload       |

**Response:** `200 OK`

```json
{
  "filename": "document.pdf",
  "stored_at": "/path/to/document.pdf",
  "text": "Extracted text content...",
  "auto_analysis": {
    "category": "legal",
    "topics": ["contract", "terms"],
    "summary": "Legal contract document..."
  }
}
```

**Errors:**

- `400` -- Invalid file type (must be `pdf`, `docx`, or `image`)

---

## Horus WebSocket API Reference

Real-time bidirectional communication between users and the multi-agent system. WebSocket connections are managed through the MAS Chat module.

---

### Table of Contents

- [Connection](#connection)
- [Authentication](#authentication)
- [Message Protocol](#message-protocol)
- [Connection Lifecycle](#connection-lifecycle)
- [Error Handling](#error-handling)
- [Client Examples](#client-examples)

---

### Connection

#### WS /chat/{conversation_id}/

Establish a WebSocket connection for real-time chat within a specific conversation.

**URL Format:**

```
ws://<host>:<port>/chat/{conversation_id}/?token={jwt_token}
```

**Path Parameters:**

| Parameter       | Type    | Description                                   |
|-----------------|---------|-----------------------------------------------|
| conversation_id | integer | ID of the conversation to connect to          |

**Query Parameters:**

| Parameter | Type   | Required | Description                                                    |
|-----------|--------|----------|----------------------------------------------------------------|
| token     | string | No*      | JWT authentication token (*required if not sent via headers)   |

---

### Authentication

Authentication is performed during the WebSocket handshake. There are two methods to provide the JWT token:

1. **Query parameter** (recommended for browser clients):

```
ws://localhost:8000/chat/1/?token=eyJhbGciOiJIUzI1NiI...
```

2. **WebSocket headers** (`Authorization` header):
   If the `token` query parameter is not provided, the server extracts the token from the WebSocket connection headers.

#### Authentication Flow

1. The server extracts the JWT token from query parameter or headers.
2. The token is decoded and validated (signature, expiration, blacklist check).
3. The user's role is checked for `TASK_READ` permission.
4. The conversation is verified to exist in the database.
5. Ownership is verified: the user must be the conversation owner or an admin.
6. If any check fails, the connection is closed with code `1008` (Policy Violation).

#### Required permission

The connection handler checks `Permission.TASK_READ` (see `src/services/mas/auth/permissions.py` in the repository). In the current mapping **`admin`**, **`manager`**, **`user`**, and **`system`** all include `TASK_READ`, so every role can open this WebSocket. Access is still narrowed by the ownership check in step 5: a non-admin may only open conversations they own.

---

### Message Protocol

All messages are exchanged as JSON-encoded text frames.

#### Client to Server (Incoming)

The server listens for text messages from the client via `receive_text()`. The client can send messages in the following format:

```json
{
  "type": "message",
  "content": "User query or command",
  "conversation_id": "1"
}
```

| Field           | Type   | Description                           |
|-----------------|--------|---------------------------------------|
| type            | string | Message type (e.g., `message`)        |
| content         | string | User query text                       |
| conversation_id | string | Conversation context ID               |

> **Note:** In the current implementation, the WebSocket endpoint primarily functions as a notification channel. Task creation is done via the REST API (`POST /tasks/new_task/`), and the WebSocket receives agent responses pushed by the server. The `receive_text()` loop keeps the connection alive.

#### Server to Client (Outgoing)

Every frame about a task is an event of that task. MAS stores the event first (see `GET /tasks/{task_id}/events`) and then sends its `data` to the sockets of the conversation, with these fields added:

| Field | Description |
|-------|-------------|
| `task_id` | The task to follow: the root of a chain, the task itself otherwise. |
| `seq` | Per-task sequence number. `null` only if Redis was down when the event was sent. |
| `event` | `progress`, `token`, `heartbeat`, `result` or `error`. |
| `stage` | `queued`, `routing`, `retrieval`, `generation`, `aggregation` or `null`. |
| `ts` | UTC time of the event. |

**Task status** (`event: progress`): the task was queued, its routing started, it was dispatched to an agent, or a chain is being aggregated.

```json
{
  "type": "task_status",
  "status": "running",
  "detail": "Assigned to Finance-Analyst",
  "agent_id": "8b9f1a3e-7a2c-4d7c-9b1b-2f4b2e0d2e5a",
  "agent_name": "Finance-Analyst",
  "task_id": "3f6c2a9e-1b7d-4c8e-9a51-6e0b2d4f8c13",
  "seq": 3,
  "event": "progress",
  "stage": "retrieval",
  "ts": "2026-10-05T09:30:12Z"
}
```

`status` is `queued`, `routing`, `running` or `aggregating`. Clients should show `detail` for a status they do not know: B-94 adds a "busy, position N" status this way.

**Heartbeat** (`event: heartbeat`): every 5 s for each queued or running top-level task whose conversation has a connected socket, with the current stage and the seconds since the task was created.

```json
{"type": "heartbeat", "elapsed_s": 65.0, "task_id": "3f6c…", "seq": 9, "event": "heartbeat", "stage": "generation", "ts": "2026-10-05T09:31:17Z"}
```

**Thought-process step** (`event: progress`, or `token` for `step_type: "reasoning.delta"`, whose `metadata.chunk` is the next piece of the streamed answer):

```json
{
  "type": "task_step",
  "task_id": "3f6c…",
  "subtask_id": "9d21…",
  "agent_id": "8b9f…",
  "agent_name": "Finance-Analyst",
  "step_type": "retrieval.results",
  "title": "Found 4 passages",
  "detail": null,
  "timestamp": "2026-10-05T09:30:20",
  "metadata": {"chunk_count": 4},
  "seq": 5,
  "event": "progress",
  "stage": "retrieval",
  "ts": "2026-10-05T09:30:20Z"
}
```

**Agent message** (`type: "task_complete"` with attribution, `type: "agent"` without): a Manager message (`event: progress`), the final answer (`event: result`) or the reason the task ended without one (`event: error`). Messages also saved to the conversation history carry their `message_id`, so a client that replays events after loading the history can skip them.

```json
{
  "type": "task_complete",
  "content": "Q4 2025 revenue was $4.2M.",
  "agent_id": "8b9f…",
  "agent_name": "Finance-Analyst",
  "skill_used": "financial_analysis",
  "timestamp": "2026-10-05T09:33:00",
  "status": "completed",
  "route": "agent",
  "message_id": 412,
  "task_id": "3f6c…",
  "seq": 21,
  "event": "result",
  "stage": "generation",
  "ts": "2026-10-05T09:33:00Z"
}
```

| Final frame | `event` | `status` | Other fields |
|-------------|---------|----------|--------------|
| Agent or chain answer | `result` | `completed` | `route: "agent"`, `sources` when the agent sent them |
| Direct answer | `result` | `completed` | `route: "direct_answer"` |
| No agent could take the demand | `error` | `failed` | `route: "none"`; `content` says why |
| Cancelled by a user | `error` | `cancelled` | `reason: "user"` |
| Stopped by `TASK_TIMEOUT` | `error` | `cancelled` | `reason: "timeout"`; the notice is also the task result |

#### Message Types Summary

| Type          | Direction        | Description                                            |
|---------------|------------------|--------------------------------------------------------|
| `task_status` | Server to Client | Queued, routing, dispatched, aggregating               |
| `heartbeat`   | Server to Client | Liveness of a running task, every 5 s                  |
| `task_step`   | Server to Client | Agent thought-process step or streamed answer chunk    |
| `task_complete` | Server to Client | Attributed message: Manager update or final answer   |
| `agent`       | Server to Client | Unattributed message: direct answer or failure reason  |

#### Reconnecting without losing anything

1. Keep the highest `seq` you processed for each task (in the web client: the last unbroken `seq`).
2. When the socket reopens, call `GET /tasks/{task_id}/events?since=<seq>` for the task you are waiting on and process the returned frames with the same handler as live frames, skipping any `seq` you already saw.
3. If the events are gone (more than 24 h, or Redis was down), `GET /tasks/{task_id}` gives the status and the result.

The web client keeps reconnecting with a capped backoff (1 s doubling to 10 s) for as long as a task is running and shows a "reconnecting" notice; it only gives up after five failed attempts when nothing is running.

---

### Connection Lifecycle

#### 1. Connect

The client initiates a WebSocket connection with the JWT token.

```
GET ws://localhost:8000/chat/1/?token=<jwt_token>
Connection: Upgrade
Upgrade: websocket
```

#### 2. Handshake and Authentication

The server:

1. Extracts the JWT token from the query parameter or headers.
2. Decodes and validates the token.
3. Checks that the user has `TASK_READ` permission.
4. Verifies the conversation exists.
5. Confirms the user owns the conversation (or is an admin).

If authentication fails, the connection is **rejected** with WebSocket close code `1008`.

#### 3. Connection Accepted

On successful authentication:

1. The server calls `websocket.accept()`.
2. A new session is created and registered with a unique `session_id`.
3. The session is persisted in Redis with a 1-hour inactivity timeout.
4. The client is added to the active connections pool for the conversation.

#### 4. Active Communication

- The server enters a read loop (`while True: await websocket.receive_text()`), keeping the connection alive.
- Task events (status, heartbeats, steps, Manager messages, answers, failures) are pushed to the client by `publish_task_event()` in `core/task_events.py`, after being stored.
- The client remains connected and receives real-time updates.

#### 5. Disconnect

Disconnection can occur from either side:

- **Client disconnect:** The browser closes the tab, calls `ws.close()`, or loses network.
- **Server-side close:** Conversation deletion, server shutdown, or authentication expiration.

On disconnect:

1. The exception is caught in the `finally` block.
2. The client is removed from the active connections pool.
3. The Redis session is cleaned up.
4. The WebSocket is closed.

---

### Error Handling

#### WebSocket Close Codes

| Code   | Meaning                  | When It Occurs                                        |
|--------|--------------------------|-------------------------------------------------------|
| `1000` | Normal closure           | Client or server closes the connection gracefully     |
| `1001` | Going away               | Server endpoint is shutting down                      |
| `1002` | Protocol error           | Malformed message received                            |
| `1003` | Unsupported data         | Unsupported data type received                        |
| `1008` | Policy violation         | Authentication failed, insufficient permissions, conversation not found, or unauthorized access |
| `1009` | Message too big          | Message exceeds size limit                            |
| `1011` | Server error             | Unexpected server-side error                          |

#### Common Authentication Failures

| Scenario                           | Result                                      |
|------------------------------------|---------------------------------------------|
| Missing or empty token             | Connection closed with code `1008`          |
| Expired JWT token                  | Connection closed with code `1008`          |
| Blacklisted (revoked) token        | Connection closed with code `1008`          |
| User lacks `TASK_READ` permission  | Connection closed with code `1008`          |
| Conversation does not exist        | Connection closed with code `1008`          |
| User is not the conversation owner | Connection closed with code `1008`          |
| Invalid conversation ID format     | Connection closed with code `1008`          |

#### Reconnection Strategy

If a WebSocket connection is lost unexpectedly, the client should implement reconnection with exponential backoff:

```
Attempt 1: wait 1 second
Attempt 2: wait 2 seconds
Attempt 3: wait 4 seconds
Attempt 4: wait 8 seconds
...
Max wait: 30 seconds
```

Ensure the JWT token is still valid before reconnecting. If the token has expired, obtain a new one via `POST /auth/token` before attempting reconnection.

---

### Client Examples

#### JavaScript / Browser

```javascript
const token = "eyJhbGciOiJIUzI1NiI...";
const conversationId = 1;
const ws = new WebSocket(
    `ws://localhost:8000/chat/${conversationId}/?token=${token}`
);

ws.onopen = () => {
    console.log("Connected to conversation", conversationId);
};

ws.onmessage = (event) => {
    const data = JSON.parse(event.data);

    switch (data.type) {
        case "task_status":
            console.log("Task", data.task_id, data.status, data.detail ?? "");
            break;
        case "heartbeat":
            console.log("Still working:", data.stage, data.elapsed_s, "s");
            break;
        case "task_step":
            console.log("Step:", data.step_type, data.title ?? "");
            break;
        case "task_complete":
        case "agent":
            console.log(data.agent_name ?? "Horus", ":", data.content);
            if (data.event === "result" || data.event === "error") {
                console.log("Task finished:", data.status);
            }
            break;
    }
};

ws.onerror = (error) => {
    console.error("WebSocket error:", error);
};

ws.onclose = (event) => {
    console.log("Disconnected:", event.code, event.reason);
    if (event.code === 1008) {
        console.error("Authentication or authorization failure");
    }
};
```

#### Python (websockets library)

```python
import asyncio
import json
import websockets

async def connect():
    token = "eyJhbGciOiJIUzI1NiI..."
    conversation_id = 1
    uri = f"ws://localhost:8000/chat/{conversation_id}/?token={token}"

    async with websockets.connect(uri) as ws:
        print(f"Connected to conversation {conversation_id}")

        async for message in ws:
            data = json.loads(message)
            print(f"Received [{data.get('type')}]: {data.get('content')}")

asyncio.run(connect())
```

#### Python (with reconnection)

```python
import asyncio
import json
import websockets

async def connect_with_retry(conversation_id: int, token: str):
    uri = f"ws://localhost:8000/chat/{conversation_id}/?token={token}"
    backoff = 1

    while True:
        try:
            async with websockets.connect(uri) as ws:
                backoff = 1
                print("Connected")
                async for message in ws:
                    data = json.loads(message)
                    print(f"[{data.get('type')}] {data.get('content')}")
        except websockets.ConnectionClosed as e:
            if e.code == 1008:
                print("Auth failed, not reconnecting")
                break
            print(f"Disconnected ({e.code}), retrying in {backoff}s...")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30)
        except Exception as e:
            print(f"Error: {e}, retrying in {backoff}s...")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30)
```
