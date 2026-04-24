# MAS API Reference

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

## Table of Contents

1. [Health](#1-health)
2. [Authentication](#2-authentication)
3. [Agents](#3-agents)
4. [Tasks](#4-tasks)
5. [Conversations](#5-conversations)
6. [Chat (WebSocket)](#6-chat-websocket)
7. [Users](#7-users)
8. [RabbitMQ / Agent Communication](#rabbitmq-agent-communication)

---

## 1. Health

### GET /

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

## 2. Authentication

### POST /auth/register

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

### POST /auth/token

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

### POST /auth/logout

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

## 3. Agents

### POST /agents/register

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

### DELETE /agents/unregister/{agent_id}

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

### GET /agents/details/{id}

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

### GET /agents/details/

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

### POST /agents/heartbeat/{agent_id}

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

## 4. Tasks

### GET /tasks/list

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

### GET /tasks/stats/queue

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

### POST /tasks/new_task/

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

### POST /tasks/task-result/

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

### PATCH /tasks/task-cancel/{task_id}

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

## 5. Conversations

### POST /conversations/create-conversation/

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

### GET /conversations/get_history/{chat_id}

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

### GET /conversations/get-conversations/

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

### DELETE /conversations/delete-conversation/{chat_id}

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

## 6. Chat (WebSocket)

### WS /chat/{conversation_id}/

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

## 7. Users

### POST /users/update_role

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

### GET /users/users_list

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

### GET /users/user_details/{user_id}

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

### GET /users/me

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

### DELETE /users/{user_id}

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

### POST /users/me/password_modification

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

### POST /users/me/username_modification/{new_username}

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

## 8. RabbitMQ / Agent Communication {#rabbitmq-agent-communication}

### POST /rabbitmq/heartbeat

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

### POST /rabbitmq/delegate

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

### POST /rabbitmq/delegation-result

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

### GET /rabbitmq/messages/{agent_id}

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

## Appendix: Schemas

### RegistrationForm

```json
{
  "name": "string",
  "skills": ["string"],
  "description": "string",
  "type": "general | researcher | analyst | writer"
}
```

### TaskForm

```json
{
  "demand": "string",
  "conversation_id": 0,
  "skills_required": ["string"]
}
```

### TaskResultForm

```json
{
  "task_id": "string",
  "result": "string",
  "conversation_id": "string",
  "agent_id": "string"
}
```

### CreateUserRequest

```json
{
  "username": "string",
  "password": "string"
}
```

### Token

```json
{
  "access_token": "string",
  "token_type": "bearer"
}
```

### ConversationCreation

```json
{
  "name": "string"
}
```

### UserPasswordModification

```json
{
  "old_password": "string",
  "new_password": "string"
}
```

### UpdateRole

```json
{
  "user_id": "string",
  "new_role": "admin | user | manager | system"
}
```

### DelegationRequestBody

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

### DelegationResultBody

```json
{
  "delegation_id": "string",
  "result": "string",
  "agent_id": "string"
}
```

### DelegationResponse

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

## Appendix: RBAC Permission Matrix

| Permission | admin | manager | user | system |
|------------|:-----:|:-------:|:----:|:------:|
| `user:create` | x | | | |
| `user:read` | x | x | x | |
| `user:update` | x | | | |
| `user:delete` | x | | | |
| `task:create` | x | x | x | |
| `task:read` | x | | x | x |
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
