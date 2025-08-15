import uuid

from chat.chat_tool_functions import active_connections

conversation_history: dict[str, list[dict]] = {}


def create_conversation():
    global conversation_history
    conv_id = str(uuid.uuid4())
    conversation_history[conv_id] = []
    active_connections[conv_id] = []
    return conv_id


def get_history(conv_id: str):
    if conv_id in conversation_history:
        return conversation_history[conv_id]
    return None


def add_messages(role: str, message: str, conversation_id: str):
    global conversation_history
    conversation_history[conversation_id].append(
        {
            "role": role,
            "message": message,
        }
    )
