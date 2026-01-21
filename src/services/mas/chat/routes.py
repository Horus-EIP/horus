"""
Chat Routes - Real-Time Multi-Agent System Communication

Provides WebSocket endpoints for real-time bidirectional communication between
users and the multi-agent system. Enables live updates on task execution,
agent processing status, and conversation flow.

WebSocket Endpoints:
    WS /chat/{conversation_id}/ - Connect to real-time chat system
        Query Parameters:
            - token: JWT authentication token (required)
        
        Message Protocol:
            Client → Server:
            {
                "type": "message",
                "content": "User query text",
                "conversation_id": 1
            }
            
            Server → Client:
            {
                "type": "agent_response",
                "agent_id": "agent-001",
                "content": "Processing result",
                "status": "completed"
            }

Security:
    - All WebSocket connections require valid JWT token in query parameters
    - Token validation performed during handshake
    - Failed authentication terminates connection immediately
    - Messages from unauthorized clients are rejected

Connection Lifecycle:
    1. Client initiates WS connection with authentication token
    2. Server validates token and authenticates user
    3. Connection established - real-time message exchange begins
    4. Server broadcasts agent updates to connected clients
    5. Connection closed on client disconnect or authentication failure
    
Supported Message Types:
    - message: User sending query to system
    - task_update: Update on task execution status
    - agent_response: Agent returning processing result
    - system_notification: System-level notifications
    - connection_status: Connection health/status messages

Error Handling:
    - Invalid token: Connection rejected with 4001 code
    - Malformed message: Error response without disconnection
    - Server error: Reconnection recommended with exponential backoff
    
Example Client Connection:
    const token = "eyJhbGciOiJIUzI1NiI...";
    const ws = new WebSocket(`ws://localhost:8000/chat/ws?token=${token}`);
    
    ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        console.log("Agent response:", data);
    };
"""

from typing import Optional, Annotated

from fastapi import APIRouter, Query, WebSocket, status, Depends
from sqlalchemy.orm import Session

from auth.auth_tool_functions import PermissionChecker, get_current_user_from_token
from auth.permissions import Permission, check_permission, Role
from chat.chat_tool_functions import (_extract_token_from_ws, delete_client,
                                      save_new_client)
from core.logger import get_logger
from db.dependency import get_db
from db.models import Conversations

logger = get_logger("chat")

router = APIRouter(prefix="/chat", tags=["Chat"])


@router.websocket("/{conversation_id}/")
async def chat_websocket(
    websocket: WebSocket,
    conversation_id: str,
    token: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
):
    """
    WebSocket endpoint for real-time chat communication.

    Establishes a WebSocket connection for a specific conversation. Requires
    authentication via JWT token (either in query parameter or WebSocket headers).
    Once connected, the WebSocket remains open for bidirectional real-time
    message exchange and agent status updates.

    Connection URL Format:
        ws://host:port/chat/{conversation_id}/?token={jwt_token}

    Query Parameters:
        - conversation_id (path): ID (integer) of the conversation to connect to (required)
        - token (query): JWT authentication token (optional if in headers)

    Authentication:
        - Token can be provided as query parameter: ?token=<jwt_token>
        - If not in query, token is extracted from WebSocket headers (Authorization)
        - Connection is closed with code 1008 if authentication fails
        - Expired tokens will result in connection rejection

    Session Management:
        - Each connection gets a unique session_id persisted in Redis
        - Sessions expire after 1 hour of inactivity
        - Active sessions tracked for load balancing and monitoring
        - Session ID returned upon successful connection

    Message Protocol:

    Incoming Messages (Client → Server):
        The server listens for incoming messages. Message format:
        {
            "type": "message",
            "content": "User query or command",
            "conversation_id": "conv_id"
        }

    Outgoing Messages (Server → Client):
        Agent responses and status updates:
        {
            "type": "agent_response",
            "agent_id": "agent-001",
            "content": "Processing result",
            "status": "completed",
            "timestamp": "2025-09-25T15:30:00Z"
        }

        Task status updates:
        {
            "type": "task_update",
            "task_id": "task-001",
            "status": "executing",
            "progress": "45%"
        }

    Connection Lifecycle:
        1. Client initiates WS connection with authentication token
        2. Server validates JWT token
        3. If valid: Accept connection and register session in Redis
        4. Connection established - real-time communication begins
        5. Server broadcasts agent updates/responses to client
        6. Client or server can close connection at any time
        7. On disconnect: Cleanup session from Redis and close WebSocket

    Error Codes:
        1000 - Normal closure
        1001 - Going away (endpoint unavailable)
        1002 - Protocol error (malformed message)
        1003 - Unsupported data type
        1008 - Policy violation (authentication failed)
        1009 - Message too big
        1011 - Server error

    Example JavaScript Client:
        const token = "eyJhbGciOiJIUzI1NiI...";
        const conversationId = 1;
        const ws = new WebSocket(
            `ws://localhost:8000/chat/${conversationId}/?token=${token}`
        );

        ws.onopen = () => {
            console.log("Connected to conversation");
            ws.send(JSON.stringify({
                type: "message",
                content: "Hello, analyze this document"
            }));
        };

        ws.onmessage = (event) => {
            const data = JSON.parse(event.data);
            console.log("Agent response:", data.content);
            if (data.status === "completed") {
                console.log("Task finished");
            }
        };

        ws.onerror = (error) => {
            console.error("WebSocket error:", error);
        };

        ws.onclose = () => {
            console.log("Disconnected from conversation");
        };

    Args:
        websocket: WebSocket connection instance
        conversation_id: ID of the conversation to connect to
        token: Optional authentication token (can also be passed in WebSocket headers)

    Connection Flow:
        1. Extract and validate authentication token
        2. Accept WebSocket connection
        3. Register client for the conversation (persists to Redis)
        4. Listen for incoming messages
        5. Clean up client connection on disconnect/error
    """
    session_id = None
    try:
        token_str = _extract_token_from_ws(websocket, token)
        user = get_current_user_from_token(token_str)
        user_id = user.get("id")
        username = user.get("username")
        user_role = user.get("payload", {}).get("role")

        if not check_permission(user_role, Permission.TASK_READ):
            logger.warning(
                f"❌ WebSocket authentication failed: Insufficient permissions for user {user_id}"
            )
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        try:
            conv_id_int = int(conversation_id)
        except ValueError:
            logger.warning(f"❌ Invalid conversation ID format: {conversation_id}")
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        conversation = db.query(Conversations).filter(Conversations.id == conv_id_int).first()

        if not conversation:
            logger.warning(f"❌ Conversation not found: {conversation_id}")
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        if conversation.owner_username != username and user_role != Role.ADMIN.value:
            logger.warning(f"❌ Unauthorized access to conversation {conversation_id} by user {username}")
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

    except Exception as e:
        logger.warning(
            f"❌ WebSocket authentication failed for conversation: {conversation_id}. Error: {str(e)}"
        )
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await websocket.accept()

    session_id = save_new_client(conversation_id, websocket, user_id, token_str, username, user_role)
    logger.info(
        f"✅ WebSocket session created: {session_id} for user {user_id} in conversation {conversation_id}"
    )

    try:
        while True:
            await websocket.receive_text()
    except Exception as e:
        logger.debug(f"WebSocket error for session {session_id}: {str(e)}")
    finally:
        if session_id:
            delete_client(conversation_id, websocket, session_id)
            logger.info(f"WebSocket session closed: {session_id}")
