import datetime as dt

import pytest

import chat.chat_tool_functions as wsmod


# --------- Dummy WebSocket ---------
class DummyWebSocket:
    def __init__(self, name="ws"):
        self.name = name
        self.sent = []

    async def send_json(self, payload):
        self.sent.append(payload)


# --------- Fixtures ---------
@pytest.fixture(autouse=True)
def clean_state(monkeypatch):
    monkeypatch.setattr(wsmod, "active_connections", {}, raising=True)
    yield
    wsmod.active_connections.clear()


# --------- Tests: save_new_client ---------
def test_save_new_client_appends_to_active_connections(capsys):
    conv_id = "conv-1"
    wsmod.active_connections[conv_id] = []
    ws = DummyWebSocket("ws1")

    wsmod.save_new_client(conv_id, ws)

    assert wsmod.active_connections[conv_id] == [ws]
    out = capsys.readouterr().out
    assert "WS connecté" in out and conv_id in out


def test_save_new_client_raises_keyerror_if_conversation_not_initialized():
    with pytest.raises(KeyError):
        wsmod.save_new_client("unknown-conv", DummyWebSocket())


# --------- Tests: delete_client ---------
def test_delete_client_removes_when_present(capsys):
    conv_id = "conv-2"
    ws1, ws2 = DummyWebSocket("ws1"), DummyWebSocket("ws2")
    wsmod.active_connections[conv_id] = [ws1, ws2]

    wsmod.delete_client(conv_id, ws1)

    assert ws1 not in wsmod.active_connections[conv_id]
    assert ws2 in wsmod.active_connections[conv_id]
    out = capsys.readouterr().out
    assert "WS déconnecté" in out and conv_id in out


def test_delete_client_is_noop_when_not_present():
    conv_id = "conv-3"
    ws = DummyWebSocket("ws")
    wsmod.active_connections[conv_id] = []

    wsmod.delete_client(conv_id, ws)
    assert wsmod.active_connections[conv_id] == []


def test_delete_client_is_noop_when_conv_absent():
    wsmod.delete_client("no-such-conv", DummyWebSocket())


# --------- Tests: send_messages_via_websockets ---------
@pytest.mark.asyncio
async def test_send_messages_sends_to_all_clients_and_formats_payload():
    conv_id = "conv-4"
    ws1, ws2 = DummyWebSocket("ws1"), DummyWebSocket("ws2")
    wsmod.active_connections[conv_id] = [ws1, ws2]

    msg = "Hello, world!"
    await wsmod.send_messages_via_websockets(conv_id, msg)

    assert len(ws1.sent) == 1 and len(ws2.sent) == 1

    for payload in (ws1.sent[0], ws2.sent[0]):
        assert payload["type"] == "agent"
        assert payload["content"] == msg
        # timestamp ISO valide
        ts = dt.datetime.fromisoformat(payload["timestamp"])
        assert isinstance(ts, dt.datetime)


@pytest.mark.asyncio
async def test_send_messages_raises_keyerror_if_conv_unknown():
    with pytest.raises(KeyError):
        await wsmod.send_messages_via_websockets("unknown", "msg")


@pytest.mark.asyncio
async def test_send_messages_with_no_clients_listed():
    conv_id = "conv-5"
    wsmod.active_connections[conv_id] = []
    await wsmod.send_messages_via_websockets(conv_id, "msg")
