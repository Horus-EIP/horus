from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from pika.exceptions import ChannelClosedByBroker, NackError, UnroutableError

from core import rabbitmq_manager
from core.rabbitmq_manager import (
    RabbitMQ,
    WorkQueueFull,
    WorkQueueUnroutable,
    work_queue_arguments,
)
from tasks.work_queue_line import WorkQueueLine

QUEUE = "horus.work.general"
INEQUIVALENT_ARG = ChannelClosedByBroker(
    406, "PRECONDITION_FAILED - inequivalent arg 'x-max-length' for queue 'horus.work.general'"
)


def _declared(count: int):
    return SimpleNamespace(method=SimpleNamespace(message_count=count))


def _connected():
    channel = MagicMock(name="channel")
    channel.is_closed = False
    connection = MagicMock(name="connection")
    connection.is_closed = False
    connection.channel.return_value = channel
    rabbitmq = RabbitMQ(retries=1, delay=0)
    with patch("core.rabbitmq_manager.pika.BlockingConnection", return_value=connection):
        rabbitmq.connect()
    return rabbitmq, channel


def _declare_calls(channel):
    return [call.kwargs for call in channel.queue_declare.call_args_list]


@pytest.fixture
def max_length(monkeypatch):
    monkeypatch.setattr(rabbitmq_manager.settings, "work_queue_max_length", 3, raising=False)
    return 3


def test_the_publisher_channel_asks_the_broker_to_confirm_every_message():
    _rabbitmq, channel = _connected()

    channel.confirm_delivery.assert_called_once_with()


def test_a_work_queue_is_declared_bounded_with_reject_publish(max_length):
    rabbitmq, channel = _connected()
    channel.queue_declare.return_value = _declared(0)

    rabbitmq.publish_task(QUEUE, '{"task_id": "t1"}')

    (declared,) = _declare_calls(channel)
    assert declared["queue"] == QUEUE
    assert declared["durable"] is True
    assert declared["arguments"] == {
        "x-max-priority": 10,
        "x-max-length": max_length,
        "x-overflow": "reject-publish",
    }


def test_a_task_is_published_persistent_and_mandatory():
    rabbitmq, channel = _connected()
    channel.queue_declare.return_value = _declared(0)

    rabbitmq.publish_task(QUEUE, '{"task_id": "t1"}')

    kwargs = channel.basic_publish.call_args.kwargs
    assert kwargs["routing_key"] == QUEUE
    assert kwargs["mandatory"] is True
    assert kwargs["properties"].delivery_mode == 2


def test_a_rejected_publish_reports_the_full_queue_with_its_depth(max_length):
    rabbitmq, channel = _connected()
    channel.queue_declare.side_effect = [_declared(max_length), _declared(max_length)]
    channel.basic_publish.side_effect = NackError([])

    with pytest.raises(WorkQueueFull) as full:
        rabbitmq.publish_task(QUEUE, '{"task_id": "t1"}')

    assert full.value.queue == QUEUE
    assert full.value.depth == max_length
    assert _declare_calls(channel)[-1] == {"queue": QUEUE, "passive": True}


def test_an_unroutable_task_is_declared_again_and_published_once_more():
    rabbitmq, channel = _connected()
    channel.queue_declare.return_value = _declared(0)
    channel.basic_publish.side_effect = [UnroutableError([]), None]

    with patch("core.rabbitmq_manager.pika.BlockingConnection") as reconnect:
        rabbitmq.publish_task(QUEUE, '{"task_id": "t1"}')

    reconnect.assert_not_called()
    assert channel.basic_publish.call_count == 2
    assert len(_declare_calls(channel)) == 2


def test_a_task_that_stays_unroutable_fails_without_reconnecting():
    rabbitmq, channel = _connected()
    channel.queue_declare.return_value = _declared(0)
    channel.basic_publish.side_effect = UnroutableError([])

    with (
        patch("core.rabbitmq_manager.pika.BlockingConnection") as reconnect,
        pytest.raises(WorkQueueUnroutable) as unroutable,
    ):
        rabbitmq.publish_task(QUEUE, '{"task_id": "t1"}')

    reconnect.assert_not_called()
    assert unroutable.value.queue == QUEUE
    assert channel.basic_publish.call_count == 2
    assert not isinstance(unroutable.value, WorkQueueFull)


def test_an_empty_queue_from_an_older_install_is_redeclared_bounded(max_length):
    rabbitmq, channel = _connected()
    channel.queue_declare.side_effect = [INEQUIVALENT_ARG, _declared(0), _declared(0)]

    rabbitmq.publish_task(QUEUE, '{"task_id": "t1"}')

    channel.queue_delete.assert_called_once_with(queue=QUEUE, if_empty=True)
    calls = _declare_calls(channel)
    assert calls[1] == {"queue": QUEUE, "passive": True}
    assert calls[2]["arguments"] == work_queue_arguments(max_length)
    assert channel.confirm_delivery.call_count == 2
    channel.basic_publish.assert_called_once()


def test_a_busy_queue_from_an_older_install_is_kept_and_held_to_the_limit(max_length):
    rabbitmq, channel = _connected()
    channel.queue_declare.side_effect = [INEQUIVALENT_ARG, _declared(max_length - 1)]

    rabbitmq.publish_task(QUEUE, '{"task_id": "t1"}')

    channel.queue_delete.assert_not_called()
    channel.basic_publish.assert_called_once()

    channel.queue_declare.side_effect = [INEQUIVALENT_ARG, _declared(max_length)]
    channel.basic_publish.reset_mock()
    with pytest.raises(WorkQueueFull) as full:
        rabbitmq.publish_task(QUEUE, '{"task_id": "t2"}')

    assert full.value.depth == max_length
    channel.basic_publish.assert_not_called()
    channel.queue_delete.assert_not_called()


def test_a_queue_that_filled_while_being_upgraded_is_kept():
    rabbitmq, channel = _connected()
    channel.queue_declare.side_effect = [INEQUIVALENT_ARG, _declared(0), _declared(1)]
    channel.queue_delete.side_effect = ChannelClosedByBroker(
        406, "PRECONDITION_FAILED - queue 'horus.work.general' in vhost '/' is not empty"
    )

    rabbitmq.publish_task(QUEUE, '{"task_id": "t1"}')

    assert _declare_calls(channel)[-1] == {"queue": QUEUE, "passive": True}
    channel.basic_publish.assert_called_once()


def test_ensure_work_queue_returns_the_waiting_count():
    rabbitmq, channel = _connected()
    channel.queue_declare.return_value = _declared(4)

    assert rabbitmq.ensure_work_queue(QUEUE) == 4


def test_the_depth_is_read_without_declaring_the_queue():
    rabbitmq, channel = _connected()
    channel.queue_declare.return_value = _declared(7)

    assert rabbitmq.work_queue_depth(QUEUE) == 7
    assert _declare_calls(channel) == [{"queue": QUEUE, "passive": True}]


def test_the_limit_defaults_to_ten_without_settings(monkeypatch):
    monkeypatch.setattr(rabbitmq_manager.settings, "work_queue_max_length", None, raising=False)

    assert rabbitmq_manager.work_queue_max_length() == 10


class TestWorkQueueLine:
    def test_position_counts_the_queue_and_everyone_ahead(self):
        line = WorkQueueLine()
        line.join(QUEUE, "first", 10)
        line.join(QUEUE, "second", 10)

        assert line.position(QUEUE, "first") == 11
        assert line.position(QUEUE, "second") == 12

    def test_leaving_moves_everyone_behind_up(self):
        line = WorkQueueLine()
        line.join(QUEUE, "first", 10)
        line.join(QUEUE, "second", 10)
        line.leave(QUEUE, "first")
        line.record_depth(QUEUE, 9)

        assert line.ahead_of(QUEUE, "second") == 0
        assert line.position(QUEUE, "second") == 10

    def test_an_empty_line_forgets_its_queue(self):
        line = WorkQueueLine()
        line.join(QUEUE, "only", 10)
        line.leave(QUEUE, "only")
        line.record_depth(QUEUE, 4)

        assert line.has_waiting(QUEUE) is False
        assert line.depth(QUEUE) == 0

    def test_joining_twice_keeps_one_place(self):
        line = WorkQueueLine()
        line.join(QUEUE, "first", 10)
        line.join(QUEUE, "first", 10)

        assert line.position(QUEUE, "first") == 11
