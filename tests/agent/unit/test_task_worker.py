from __future__ import annotations

import json
import threading
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from agent_server import consumers


def _wait_until(condition, seconds=5.0):
    deadline = time.monotonic() + seconds
    while not condition() and time.monotonic() < deadline:
        time.sleep(0.01)
    return condition()


def test_the_message_is_acknowledged_before_the_task_runs_off_the_consumer_thread():
    server = MagicMock()
    server.claim_task.return_value = consumers.TaskClaim.CLAIMED
    channel = MagicMock()
    started = threading.Event()
    release = threading.Event()
    seen = {}

    async def run(_task):
        seen["acked_first"] = channel.basic_ack.called
        seen["thread"] = threading.current_thread()
        started.set()
        release.wait(5)
        return {"response": "ANSWER"}

    server.get_pipeline_for_type.return_value = SimpleNamespace(process_task=run)
    workers = consumers.TaskWorkerPool(1)
    body = json.dumps({"demand": "q", "task_id": "t1", "conversation_id": "c"}).encode()

    with patch("agent_server.server", server, create=True):
        consumers._handle_delivery(
            channel,
            SimpleNamespace(delivery_tag=5),
            SimpleNamespace(headers=None),
            body,
            "general",
            workers,
        )
        returned_before_the_task_ended = not release.is_set()
        assert started.wait(5)
        slot_taken_while_running = not workers.has_free_slot()
        release.set()
        assert _wait_until(workers.has_free_slot)

    assert returned_before_the_task_ended
    assert slot_taken_while_running
    assert seen["acked_first"] is True
    assert seen["thread"] is not threading.current_thread()
    channel.basic_ack.assert_called_once_with(delivery_tag=5)
    server.send_result.assert_called_once()
    assert server.send_result.call_args.args[:3] == ("ANSWER", "c", "t1")


def test_a_task_this_run_already_started_is_never_started_again():
    server = MagicMock()
    server.claim_task.return_value = consumers.TaskClaim.CLAIMED
    runs = []

    async def run(task):
        runs.append(task["task_id"])
        return {"response": "ANSWER"}

    server.get_pipeline_for_type.return_value = SimpleNamespace(process_task=run)
    workers = consumers.TaskWorkerPool(1)
    body = json.dumps({"demand": "q", "task_id": "t1", "conversation_id": "c"}).encode()
    channel = MagicMock()

    with patch("agent_server.server", server, create=True):
        for tag in (1, 2):
            consumers._handle_delivery(
                channel,
                SimpleNamespace(delivery_tag=tag),
                SimpleNamespace(headers=None),
                body,
                "general",
                workers,
            )
            assert _wait_until(workers.has_free_slot)

    assert runs == ["t1"]
    assert [call.kwargs["delivery_tag"] for call in channel.basic_ack.call_args_list] == [1, 2]
    server.claim_task.assert_called_once_with("t1", None)


def test_the_pool_remembers_only_its_most_recent_task_ids():
    workers = consumers.TaskWorkerPool(1, remembered_tasks=2)
    for task_id in ("t1", "t2", "t3"):
        workers.submit(lambda: None, task_id)

    assert _wait_until(workers.has_free_slot)
    assert not workers.has_started("t1")
    assert workers.has_started("t2")
    assert workers.has_started("t3")


def test_a_redelivered_message_of_a_claimed_task_never_runs_it_twice():
    server = MagicMock()
    server.claim_task.side_effect = [consumers.TaskClaim.CLAIMED, consumers.TaskClaim.REFUSED]
    runs = []

    async def run(task):
        runs.append(task["task_id"])
        return {"response": "ANSWER"}

    server.get_pipeline_for_type.return_value = SimpleNamespace(process_task=run)
    workers = consumers.TaskWorkerPool(1)
    body = json.dumps({"demand": "q", "task_id": "t1", "conversation_id": "c"}).encode()

    with patch("agent_server.server", server, create=True):
        for tag in (1, 2):
            consumers._handle_delivery(
                MagicMock(),
                SimpleNamespace(delivery_tag=tag),
                SimpleNamespace(headers=None),
                body,
                "general",
                workers,
            )
            assert _wait_until(workers.has_free_slot)

    assert runs == ["t1"]
