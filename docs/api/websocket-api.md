# Horus WebSocket API Reference

Real-time bidirectional communication between users and the multi-agent system. WebSocket connections are managed through the MAS Chat module.

---

## Table of Contents

- [Connection](#connection)
- [Authentication](#authentication)
- [Message Protocol](#message-protocol)
- [Connection Lifecycle](#connection-lifecycle)
- [Error Handling](#error-handling)
- [Client Examples](#client-examples)

---

## Connection

### WS /chat/{conversation_id}/

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

## Authentication

Authentication is performed during the WebSocket handshake. There are two methods to provide the JWT token:

1. **Query parameter** (recommended for browser clients):

```
ws://localhost:8000/chat/1/?token=eyJhbGciOiJIUzI1NiI...
```

2. **WebSocket headers** (`Authorization` header):
   If the `token` query parameter is not provided, the server extracts the token from the WebSocket connection headers.

### Authentication Flow

1. The server extracts the JWT token from query parameter or headers.
2. The token is decoded and validated (signature, expiration, blacklist check).
3. The user's role is checked for `TASK_READ` permission.
4. The conversation is verified to exist in the database.
5. Ownership is verified: the user must be the conversation owner or an admin.
6. If any check fails, the connection is closed with code `1008` (Policy Violation).

### Required permission

The connection handler checks `Permission.TASK_READ` (see `src/services/mas/auth/permissions.py` in the repository). In the current mapping, **`admin`**, **`user`**, and **`system`** roles include `TASK_READ`. The **`manager`** role does **not** include `TASK_READ`, so managers cannot open this WebSocket unless the permission map is changed in code.

---

## Message Protocol

All messages are exchanged as JSON-encoded text frames.

### Client to Server (Incoming)

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

### Server to Client (Outgoing)

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

### Message Types Summary

| Type                  | Direction        | Description                              |
|-----------------------|------------------|------------------------------------------|
| `message`             | Client to Server | User sending a query                     |
| `agent_response`      | Server to Client | Agent returning a processing result      |
| `task_update`         | Server to Client | Task execution status change             |
| `system_notification` | Server to Client | System-level notification                |
| `connection_status`   | Server to Client | Connection health and status messages    |

---

## Connection Lifecycle

### 1. Connect

The client initiates a WebSocket connection with the JWT token.

```
GET ws://localhost:8000/chat/1/?token=<jwt_token>
Connection: Upgrade
Upgrade: websocket
```

### 2. Handshake and Authentication

The server:

1. Extracts the JWT token from the query parameter or headers.
2. Decodes and validates the token.
3. Checks that the user has `TASK_READ` permission.
4. Verifies the conversation exists.
5. Confirms the user owns the conversation (or is an admin).

If authentication fails, the connection is **rejected** with WebSocket close code `1008`.

### 3. Connection Accepted

On successful authentication:

1. The server calls `websocket.accept()`.
2. A new session is created and registered with a unique `session_id`.
3. The session is persisted in Redis with a 1-hour inactivity timeout.
4. The client is added to the active connections pool for the conversation.

### 4. Active Communication

- The server enters a read loop (`while True: await websocket.receive_text()`), keeping the connection alive.
- Agent responses and task updates are pushed to the client asynchronously via `send_messages_via_websockets()` when tasks complete.
- The client remains connected and receives real-time updates.

### 5. Disconnect

Disconnection can occur from either side:

- **Client disconnect:** The browser closes the tab, calls `ws.close()`, or loses network.
- **Server-side close:** Conversation deletion, server shutdown, or authentication expiration.

On disconnect:

1. The exception is caught in the `finally` block.
2. The client is removed from the active connections pool.
3. The Redis session is cleaned up.
4. The WebSocket is closed.

---

## Error Handling

### WebSocket Close Codes

| Code   | Meaning                  | When It Occurs                                        |
|--------|--------------------------|-------------------------------------------------------|
| `1000` | Normal closure           | Client or server closes the connection gracefully     |
| `1001` | Going away               | Server endpoint is shutting down                      |
| `1002` | Protocol error           | Malformed message received                            |
| `1003` | Unsupported data         | Unsupported data type received                        |
| `1008` | Policy violation         | Authentication failed, insufficient permissions, conversation not found, or unauthorized access |
| `1009` | Message too big          | Message exceeds size limit                            |
| `1011` | Server error             | Unexpected server-side error                          |

### Common Authentication Failures

| Scenario                           | Result                                      |
|------------------------------------|---------------------------------------------|
| Missing or empty token             | Connection closed with code `1008`          |
| Expired JWT token                  | Connection closed with code `1008`          |
| Blacklisted (revoked) token        | Connection closed with code `1008`          |
| User lacks `TASK_READ` permission  | Connection closed with code `1008`          |
| Conversation does not exist        | Connection closed with code `1008`          |
| User is not the conversation owner | Connection closed with code `1008`          |
| Invalid conversation ID format     | Connection closed with code `1008`          |

### Reconnection Strategy

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

## Client Examples

### JavaScript / Browser

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

### Python (websockets library)

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

### Python (with reconnection)

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
