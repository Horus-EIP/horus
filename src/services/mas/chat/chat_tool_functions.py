import datetime

from fastapi import WebSocket

active_connections: dict[str, list[WebSocket]] = {}


async def send_messages_via_websockets(conversation_id: str, message: str):
    for websocket_id in active_connections[conversation_id]:
        formatted = {
            "type": "agent",
            "content": message,
            "timestamp": datetime.datetime.now().isoformat(),
        }
        await websocket_id.send_json(formatted)


def save_new_client(conv_id: str, websocket: WebSocket):
    global active_connections
    active_connections[conv_id].append(websocket)
    print(f"🔌 WS connecté pour la conversation: {conv_id}")


def delete_client(conv_id: str, websocket: WebSocket):
    global active_connections
    if conv_id in active_connections:
        if websocket in active_connections[conv_id]:
            active_connections[conv_id].remove(websocket)
    print(f"🔌 WS déconnecté pour la conversation: {conv_id}")
