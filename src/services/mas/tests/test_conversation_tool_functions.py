import uuid

import pytest

import conversations.conversation_tool_functions as conv

# ---------- Fixtures ----------


@pytest.fixture(autouse=True)
def clean_state(monkeypatch):
    conv.conversation_history.clear()
    monkeypatch.setattr(conv, "active_connections", {}, raising=True)
    yield
    conv.conversation_history.clear()


# ---------- Helpers ----------


def _is_valid_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
        return True
    except Exception:
        return False


# ---------- Tests: create_conversation ----------


def test_create_conversation_returns_uuid_and_initializes_structures():
    conv_id = conv.create_conversation()
    assert _is_valid_uuid(conv_id)
    # conversation_history contient une liste vide
    assert conv_id in conv.conversation_history
    assert conv.conversation_history[conv_id] == []
    # active_connections contient une liste vide
    assert conv_id in conv.active_connections
    assert conv.active_connections[conv_id] == []


def test_create_conversation_unique_ids():
    ids = {conv.create_conversation() for _ in range(20)}
    assert len(ids) == 20
    assert all(_is_valid_uuid(i) for i in ids)


# ---------- Tests: get_history ----------


def test_get_history_returns_empty_list_for_new_conversation():
    conv_id = conv.create_conversation()
    history = conv.get_history(conv_id)
    assert isinstance(history, list)
    assert history == []


def test_get_history_returns_none_if_conversation_unknown():
    history = conv.get_history("00000000-0000-0000-0000-000000000000")
    assert history is None


# ---------- Tests: add_messages ----------


def test_add_messages_appends_message_and_preserves_order():
    conv_id = conv.create_conversation()
    conv.add_messages("user", "Bonjour", conv_id)
    conv.add_messages("assistant", "Salut !", conv_id)
    history = conv.get_history(conv_id)
    assert history == [
        {"role": "user", "message": "Bonjour"},
        {"role": "assistant", "message": "Salut !"},
    ]


def test_add_messages_supports_various_roles_and_unicode():
    conv_id = conv.create_conversation()
    conv.add_messages("system", "⚙️ règles", conv_id)
    conv.add_messages("user", "Résumé : « À l’aube… »", conv_id)
    h = conv.get_history(conv_id)
    assert h[0]["role"] == "system" and "règles" in h[0]["message"]
    assert h[1]["role"] == "user" and "Résumé" in h[1]["message"]


def test_add_messages_raises_keyerror_if_conversation_missing():
    with pytest.raises(KeyError):
        conv.add_messages("user", "Hello", "00000000-0000-0000-0000-000000000000")


def test_histories_are_isolated_between_conversations():
    c1 = conv.create_conversation()
    c2 = conv.create_conversation()
    conv.add_messages("user", "A", c1)
    conv.add_messages("user", "B", c2)
    assert conv.get_history(c1) == [{"role": "user", "message": "A"}]
    assert conv.get_history(c2) == [{"role": "user", "message": "B"}]


# ---------- Tests: active_connections behavior ----------


def test_active_connections_initialized_as_empty_list_for_new_conversation():
    conv_id = conv.create_conversation()
    assert conv.active_connections[conv_id] == []


def test_active_connections_is_independent_of_history():
    conv_id = conv.create_conversation()
    conv.add_messages("user", "Msg", conv_id)
    assert conv.active_connections[conv_id] == []
