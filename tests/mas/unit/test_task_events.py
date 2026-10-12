from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

import chat.chat_tool_functions as chat_functions
import core.task_events as task_events
from core.task_events import (
    TASK_EVENTS_TTL_SECONDS,
    publish_agent_message,
    publish_task_event,
    publish_task_status,
    publish_task_step,
    read_task_events,
    task_events_key,
    task_seq_key,
    task_stage_key,
)


@pytest.fixture(autouse=True)
def no_sockets():
    chat_functions.active_connections.clear()
    yield
    chat_functions.active_connections.clear()


def _socket(conversation_id="7"):
    ws = MagicMock()
    ws.send_json = AsyncMock()
    chat_functions.active_connections.setdefault(conversation_id, []).append(ws)
    return ws


def _sent(ws):
    return [call.args[0] for call in ws.send_json.await_args_list]


class TestPublishTaskEvent:
    async def test_each_event_gets_the_next_seq_of_its_task(self):
        first = await publish_agent_message("t-1", None, "one")
        second = await publish_agent_message("t-1", None, "two")
        other = await publish_agent_message("t-2", None, "elsewhere")

        assert (first["seq"], second["seq"], other["seq"]) == (1, 2, 1)

    async def test_events_are_stored_while_nobody_is_connected(self):
        await publish_agent_message("t-1", 7, "Revenue was $4.2M", event_type="result")

        (stored,) = read_task_events("t-1")
        assert stored["type"] == "result"
        assert stored["data"]["content"] == "Revenue was $4.2M"
        assert stored["task_id"] == "t-1"
        assert stored["ts"].endswith("Z")

    async def test_stream_and_seq_expire_after_24_hours(self, task_event_store):
        await publish_task_status("t-1", 7, "queued", stage="queued")

        stream_ttl = task_event_store.ttl(task_events_key("t-1"))
        assert TASK_EVENTS_TTL_SECONDS - 5 < stream_ttl <= TASK_EVENTS_TTL_SECONDS
        assert task_event_store.ttl(task_seq_key("t-1")) > stream_ttl
        assert TASK_EVENTS_TTL_SECONDS == 24 * 60 * 60

    async def test_the_frame_sent_over_the_socket_carries_the_event_envelope(self):
        ws = _socket("7")

        await publish_agent_message(
            "t-1",
            7,
            "Revenue was $4.2M",
            event_type="result",
            stage="generation",
            agent_id="agent-finance",
            agent_name="Finance-Analyst",
            skill_used="analysis",
            route="agent",
        )

        (frame,) = _sent(ws)
        assert frame["type"] == "task_complete"
        assert frame["content"] == "Revenue was $4.2M"
        assert frame["agent_name"] == "Finance-Analyst"
        assert frame["task_id"] == "t-1"
        assert frame["seq"] == 1
        assert frame["event"] == "result"
        assert frame["stage"] == "generation"
        assert frame["route"] == "agent"

    async def test_only_the_tasks_conversation_receives_the_frame(self):
        mine = _socket("7")
        other = _socket("8")

        await publish_agent_message("t-1", 7, "hello")

        assert len(_sent(mine)) == 1
        assert _sent(other) == []

    async def test_frames_of_one_task_go_out_in_seq_order(self):
        ws = _socket("7")

        await asyncio.gather(
            *(publish_agent_message("t-1", 7, f"message {index}") for index in range(20))
        )

        assert [frame["seq"] for frame in _sent(ws)] == list(range(1, 21))

    async def test_a_store_outage_still_delivers_the_frame_live(self, monkeypatch):
        broken = MagicMock()
        broken.incr.side_effect = ConnectionError("redis down")
        monkeypatch.setattr(task_events, "redis_db", broken)
        ws = _socket("7")

        event = await publish_agent_message("t-1", 7, "still delivered")

        assert event["seq"] is None
        assert _sent(ws)[0]["content"] == "still delivered"

    async def test_a_dead_socket_is_dropped(self):
        dead = _socket("7")
        dead.send_json.side_effect = RuntimeError("closed")
        alive = _socket("7")

        await publish_agent_message("t-1", 7, "hello")

        assert chat_functions.active_connections["7"] == [alive]

    async def test_unknown_event_type_is_rejected(self):
        with pytest.raises(ValueError):
            await publish_task_event("t-1", "bogus", conversation_id=None, data={})


class TestEventReplay:
    async def test_read_since_skips_the_events_already_seen(self):
        for index in range(5):
            await publish_agent_message("t-1", None, f"message {index}")

        assert [event["seq"] for event in read_task_events("t-1", since=3)] == [4, 5]
        assert [event["seq"] for event in read_task_events("t-1", since=0, limit=2)] == [1, 2]
        assert read_task_events("t-1", since=5) == []

    async def test_unknown_task_has_no_events(self):
        assert read_task_events("ghost") == []


class TestTaskStepEvents:
    async def test_token_deltas_are_stored_as_token_events_in_the_generation_stage(self):
        await publish_task_step(
            "root-1",
            7,
            {
                "subtask_id": "sub-1",
                "step_type": "reasoning.delta",
                "metadata": {"chunk": "Revenue", "index": 0},
            },
        )

        (event,) = read_task_events("root-1")
        assert event["type"] == "token"
        assert event["stage"] == "generation"
        assert event["data"]["metadata"]["chunk"] == "Revenue"
        assert event["data"]["task_id"] == "root-1"

    async def test_retrieval_steps_move_the_task_to_the_retrieval_stage(self, task_event_store):
        await publish_task_step("root-1", 7, {"step_type": "retrieval.start"})

        assert read_task_events("root-1")[0]["type"] == "progress"
        assert task_event_store.get(task_stage_key("root-1")) == "retrieval"

    async def test_an_error_step_keeps_the_current_stage(self, task_event_store):
        await publish_task_step("root-1", 7, {"step_type": "reasoning.start"})
        await publish_task_step("root-1", 7, {"step_type": "error"})

        assert task_event_store.get(task_stage_key("root-1")) == "generation"
        assert read_task_events("root-1")[-1]["stage"] is None
