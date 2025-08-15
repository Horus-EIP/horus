from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from chat.chat_tool_functions import delete_client, save_new_client

router = APIRouter(prefix="/chat", tags=["Chat"])


@router.websocket("/{conversation_id}/")
async def chat_websocket(websocket: WebSocket, conversation_id: str):
    await websocket.accept()
    save_new_client(conversation_id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:

        delete_client(conversation_id, websocket)
