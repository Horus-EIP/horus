from fastapi import APIRouter, HTTPException

from conversations.conversation_tool_functions import (create_conversation,
                                                       get_history)

router = APIRouter(prefix="/conversations", tags=["Conversations"])


@router.post(
    "/create-conversation/",
    summary="Create a new conversation",
    description="Create a new conversation channel and return the id of this conversation (`conversation_id`).",
    status_code=200,
    tags=["Conversations"],
    responses={
        200: {
            "description": "Conversation created",
            "content": {
                "application/json": {
                    "example": {
                        "conversation_id": "8b9f1a3e-7a2c-4d7c-9b1b-2f4b2e0d2e5a"
                    }
                }
            },
        }
    },
)
async def create_new_conversation():
    conv_id = create_conversation()
    return {
        "conversation_id": conv_id,
    }


@router.get(
    "/get_history/{chat_id}",
    summary="Get conversation history",
    description="Collect the history of a specific conversation. Each entry contains `role` and `message` keys.",
    status_code=200,
    tags=["Conversations"],
    responses={
        200: {
            "description": "History's conversation",
            "content": {
                "application/json": {
                    "example": [
                        {"role": "user", "message": "Hello"},
                        {
                            "role": "assistant",
                            "message": "Hello ! How can i help you ?",
                        },
                    ]
                }
            },
        },
        404: {
            "description": "Conversation not found",
            "content": {
                "application/json": {
                    "example": [
                        {
                            "message": "Conversation 8b9f1a3e-7a2c-4d7c-9b1b-2f4b2e0d2e5a not found"
                        },
                    ]
                }
            },
        },
    },
)
async def get_conversation_history(chat_id: str):
    history = get_history(chat_id)
    if history is None:
        raise HTTPException(status_code=404, detail=f"Conversation {chat_id} not found")
    else:
        return history
