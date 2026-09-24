import datetime
import json
import uuid

from fastapi import WebSocket, WebSocketException, status
from fastapi.security.utils import get_authorization_scheme_param

from core.logger import get_logger
from db.redis_client import redis_db

logger = get_logger("chat")

# Global registry of active WebSocket connections
# Structure: {conversation_id: [WebSocket1, WebSocket2, ...]}
active_connections: dict[str, list[WebSocket]] = {}


async def send_messages_via_websockets(
    conversation_id: str,
    message: str,
    *,
    agent_id: str | None = None,
    agent_name: str | None = None,
    skill_used: str | None = None,
):
    """Broadcast a message to all WebSocket clients on this conversation.

    When agent metadata is provided, emits ``type=task_complete`` so the chat
    UI can render an attribution chip; otherwise falls back to the legacy
    ``type=agent`` shape used by direct-answer / pre-attribution paths.

    Args:
        conversation_id: Target conversation.
        message: Text content to broadcast.
        agent_id: Originating agent's UUID (optional).
        agent_name: Human-readable agent name for the chip (optional).
        skill_used: Skill that produced the answer (optional).
    """
    conv_key = str(conversation_id)
    conns = active_connections.get(conv_key, [])
    if not conns:
        return

    has_attribution = bool(agent_id or agent_name or skill_used)
    msg_type = "task_complete" if has_attribution else "agent"

    payload: dict = {
        "type": msg_type,
        "content": message,
        "timestamp": datetime.datetime.now().isoformat(),
    }
    if has_attribution:
        payload["agent_id"] = agent_id
        payload["agent_name"] = agent_name
        payload["skill_used"] = skill_used

    for ws in list(conns):
        try:
            await ws.send_json(payload)
        except Exception:
            try:
                conns.remove(ws)
            except ValueError:
                pass


async def send_task_step_via_websockets(
    conversation_id: str,
    step: dict,
) -> None:
    """Broadcast a ``task_step`` "thought process" event to the conversation.

    Older chat clients ignore unknown WS message types, so this is safe to
    fan out without coordination. Drops dead sockets the same way the
    ``agent_message`` path does.
    """
    conv_key = str(conversation_id)
    conns = active_connections.get(conv_key, [])
    if not conns:
        return

    payload = {
        "type": "task_step",
        "task_id": step.get("task_id"),
        "agent_id": step.get("agent_id"),
        "agent_name": step.get("agent_name"),
        "step_type": step.get("step_type"),
        "title": step.get("title"),
        "detail": step.get("detail"),
        "timestamp": step.get("timestamp") or datetime.datetime.now().isoformat(),
        "metadata": step.get("metadata") or {},
    }

    for ws in list(conns):
        try:
            await ws.send_json(payload)
        except Exception:
            try:
                conns.remove(ws)
            except ValueError:
                pass


def save_new_client(
    conv_id: str,
    websocket: WebSocket,
    user_id: str,
    token: str,
    username: str = None,
    role: str = None,
):
    """Track a new WS client and persist its session in Redis. Returns session UUID."""
    conv_id = str(conv_id)
    conns = active_connections.setdefault(conv_id, [])
    if websocket not in conns:
        conns.append(websocket)

    session_id = str(uuid.uuid4())
    session_data = {
        "conversation_id": conv_id,
        "user_id": user_id,
        "username": username,
        "role": role,
        "token": token,
        "connected_at": datetime.datetime.now().isoformat(),
        "session_id": session_id,
    }
    redis_db.setex(
        f"ws_session:{session_id}",
        3600,
        json.dumps(session_data),
    )

    redis_db.sadd(f"conversation_sessions:{conv_id}", session_id)

    logger.info(
        f"WebSocket connected for conversation: {conv_id} (session={session_id}, total={len(conns)})"
    )
    return session_id


def delete_client(conv_id: str, websocket: WebSocket, session_id: str):
    """
    Remove a WebSocket client and clean up session data.

    Deregisters the WebSocket from active_connections and removes associated
    session data from Redis. Use this on connection close or error.

    Args:
        conv_id (str): Conversation ID
        websocket (WebSocket): The WebSocket object to remove
        session_id (str): The session ID associated with this connection

    Returns:
        None
    """
    conv_id = str(conv_id)
    conns = active_connections.get(conv_id)
    if not conns:
        logger.debug(f"WebSocket disconnected (no list) for conversation: {conv_id}")
        return

    if websocket in conns:
        conns.remove(websocket)

    redis_db.delete(f"ws_session:{session_id}")
    redis_db.srem(f"conversation_sessions:{conv_id}", session_id)

    if not conns:
        active_connections.pop(conv_id, None)

    logger.info(
        f"WebSocket disconnected for conversation: {conv_id} (session={session_id}, remaining={len(active_connections.get(conv_id, []))})"
    )


def get_active_sessions(conv_id: str) -> list[dict]:
    """
    Retrieve all active session metadata for a conversation from Redis.

    Args:
        conv_id (str): Conversation ID to query

    Returns:
        list[dict]: List of session data dictionaries for all active clients
    """
    conv_id = str(conv_id)
    session_ids = redis_db.smembers(f"conversation_sessions:{conv_id}")
    sessions = []

    for session_id in session_ids:
        session_data = redis_db.get(f"ws_session:{session_id}")
        if session_data:
            sessions.append(json.loads(session_data))

    return sessions


def _extract_token_from_ws(websocket: WebSocket, token_qs: str | None) -> str:
    if token_qs:
        return token_qs
    auth = websocket.headers.get("Authorization")
    if auth:
        scheme, param = get_authorization_scheme_param(auth)
        if scheme.lower() == "bearer" and param:
            return param
    raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION)
