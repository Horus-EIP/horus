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

Retrieve current task queue statistics (pending, running, completed, failed counts).

**Auth:** JWT Bearer (requires `analytics:view` permission)

**Request:** No body.

**Response 200:**

```json
{
  "pending": 5,
  "running": 2,
  "completed": 150,
  "failed": 1,
  "cancelled": 0,
  "timeout": 0,
  "total": 158
}
```

**Errors:**

| Code | Detail |
|------|--------|
| `403` | `Insufficient permissions` |

---

#### POST /tasks/new_task/

Create a new task and dispatch it to the best matching agent based on required skills. Uses LLM-based agent selection. If no single agent matches, the system attempts to decompose the task into sub-tasks.

**Auth:** JWT Bearer (requires `task:create` permission)

**Request:** `application/json`

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| demand | string | Yes | The task description / user question. |
| conversation_id | integer | Yes | ID of the conversation this task belongs to. |
| skills_required | string[] | Yes | Skill tags for agent matching (min 1). |

**Response 200 (assigned):**

```json
{
  "message": "Task 'Summarize this text' assigned to agent 8b9f1a3e-7a2c-4d7c-9b1b-2f4b2e0d2e5a",
  "conversation_id": 1,
  "task_id": "task-uuid-1234"
}
```

**Response 200 (direct answer from LLM):**

```json
{
  "message": "Processing complete",
  "conversation_id": 1,
  "result": "The answer is 42."
}
```

**Response 200 (no agent available):**

```json
{
  "message": "No agent registered to assign a task"
}
```

**Errors:**

| Code | Detail |
|------|--------|
| `401` | `Authentication Failed` |
| `404` | `Conversation not found` |
| `422` | Request body validation error. |
| `500` | Database or RabbitMQ error. |

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

Cancel a running task. Updates its status to CANCELED and sends a high-priority cancellation signal to the assigned agent via RabbitMQ.

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

**Outgoing messages (server to client):**

Agent response:

```json
{
  "type": "agent_response",
  "agent_id": "agent-001",
  "content": "Processing result",
  "status": "completed",
  "timestamp": "2025-09-25T15:30:00Z"
}
```

Task status update:

```json
{
  "type": "task_update",
  "task_id": "task-001",
  "status": "executing",
  "progress": "45%"
}
```

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

The service uses ChromaDB with the `BAAI/bge-base-en-v1.5` embedding model (see `main.py`).

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

Query the knowledge store for relevant documents using semantic search with optional metadata filters.

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
  "ids": [["id1", "id2"]],
  "distances": [[0.1, 0.2]],
  "metadatas": [[
    { "title": "Doc 1" },
    { "title": "Doc 2" }
  ]],
  "documents": [[
    "Content 1",
    "Content 2"
  ]]
}
```

**Errors:**

- `400` -- Invalid filters JSON format
- `404` -- No results found
- `500` -- Query execution failure

---

#### DELETE /{id}

Remove a document from the knowledge store by its ID.

**Auth:** None (internal service)

**Path Parameters:**

| Parameter | Type   | Description               |
|-----------|--------|---------------------------|
| id        | string | Unique document identifier |

**Response:** `200 OK`

```json
{
  "status": "Document deleted"
}
```

**Errors:**

- `404` -- Document not found or deletion failed

---

#### POST /smart-search

Perform an advanced search with metadata filters including category, entities, and confidence score.

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
  "filters": { "auto_category": "finance" },
  "total": 3,
  "results": {
    "documents": ["Content 1", "Content 2", "Content 3"],
    "metadatas": [
      { "title": "Q1 Report", "auto_category": "finance" },
      { "title": "Q2 Report", "auto_category": "finance" },
      { "title": "Annual Summary", "auto_category": "finance" }
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

Search for documents containing a specific named entity.

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
    "ids": [["id1", "id2"]],
    "documents": [["Doc content 1", "Doc content 2"]],
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
    { "category": "uncategorized", "count": 7 }
  ]
}
```

Categories are sorted by count in descending order.

**Errors:**

- `500` -- Retrieval failure

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

List all files currently indexed in the knowledge store. Returns **analysis metadata and short text only** (auto-summary from ingest, category, type, and a capped excerpt). Full document bodies are not included so large files do not blow up the UI or agents listing the store.

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

The server pushes messages to connected clients when agents complete tasks. Messages are broadcast to all WebSocket clients connected to the relevant conversation.

**Agent response:**

```json
{
  "type": "agent_response",
  "agent_id": "8b9f1a3e-7a2c-4d7c-9b1b-2f4b2e0d2e5a",
  "content": "Here is the analysis result...",
  "status": "completed",
  "timestamp": "2025-09-25T15:30:00Z"
}
```

**Task status update:**

```json
{
  "type": "task_update",
  "task_id": "task-001",
  "status": "executing",
  "progress": "45%"
}
```

**System notification:**

```json
{
  "type": "system_notification",
  "content": "Agent DocumentAnalyzer is now processing your request"
}
```

**Connection status:**

```json
{
  "type": "connection_status",
  "status": "connected",
  "session_id": "sess-uuid-1234"
}
```

#### Message Types Summary

| Type                  | Direction        | Description                              |
|-----------------------|------------------|------------------------------------------|
| `message`             | Client to Server | User sending a query                     |
| `agent_response`      | Server to Client | Agent returning a processing result      |
| `task_update`         | Server to Client | Task execution status change             |
| `system_notification` | Server to Client | System-level notification                |
| `connection_status`   | Server to Client | Connection health and status messages    |

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
- Agent responses and task updates are pushed to the client asynchronously via `send_messages_via_websockets()` when tasks complete.
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
        case "agent_response":
            console.log("Agent response:", data.content);
            if (data.status === "completed") {
                console.log("Task finished");
            }
            break;
        case "task_update":
            console.log("Task status:", data.status, data.progress);
            break;
        case "system_notification":
            console.log("System:", data.content);
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
