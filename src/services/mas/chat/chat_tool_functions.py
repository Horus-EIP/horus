import datetime
import json
import uuid
from typing import Optional

from fastapi import WebSocket, WebSocketException, status
from fastapi.security.utils import get_authorization_scheme_param

from core.logger import get_logger
from db.redis_client import redis_db

logger = get_logger("chat")

active_connections: dict[str, list[WebSocket]] = {}


async def send_messages_via_websockets(conversation_id: str, message: str):
    conns = active_connections.get(conversation_id, [])
    if not conns:
        return

    for ws in list(conns):
        try:
            formatted = {
                "type": "agent",
                "content": message,
                "timestamp": datetime.datetime.now().isoformat(),
            }
            await ws.send_json(formatted)
        except Exception:
            try:
                conns.remove(ws)
            except ValueError:
                pass


def save_new_client(conv_id: str, websocket: WebSocket, user_id: str, token: str, username: str = None, role: str = None):
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
    session_ids = redis_db.smembers(f"conversation_sessions:{conv_id}")
    sessions = []

    for session_id in session_ids:
        session_data = redis_db.get(f"ws_session:{session_id}")
        if session_data:
            sessions.append(json.loads(session_data))

    return sessions


def _extract_token_from_ws(websocket: WebSocket, token_qs: Optional[str]) -> str:
    if token_qs:
        return token_qs
    auth = websocket.headers.get("Authorization")
    if auth:
        scheme, param = get_authorization_scheme_param(auth)
        if scheme.lower() == "bearer" and param:
            return param
    raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION)
