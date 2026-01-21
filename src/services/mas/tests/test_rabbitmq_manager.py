from unittest.mock import MagicMock, patch

import pika
import pytest

from core.rabbitmq_manager import RabbitMQ


class TestRabbitMQManager:

    @pytest.fixture
    def rabbitmq(self):
        return RabbitMQ(retries=1, delay=0.1)

    @patch("core.rabbitmq_manager.pika.BlockingConnection")
    def test_connect_success(self, mock_connection, rabbitmq):
        # Setup mock
        mock_conn_instance = MagicMock()
        mock_channel = MagicMock()
        mock_connection.return_value = mock_conn_instance
        mock_conn_instance.channel.return_value = mock_channel

        # Execute
        result = rabbitmq.connect()

        # Verify
        assert result is True
        assert rabbitmq.connection == mock_conn_instance
        assert rabbitmq.channel == mock_channel
        mock_connection.assert_called_once()

    @patch("core.rabbitmq_manager.pika.BlockingConnection")
    @patch("core.rabbitmq_manager.time.sleep")
    def test_connect_failure_retry(self, mock_sleep, mock_connection, rabbitmq):
        # Setup mock to raise exception
        mock_connection.side_effect = Exception("Connection failed")

        # Execute
        with pytest.raises(Exception) as excinfo:
            rabbitmq.connect()

        # Verify
        assert str(excinfo.value) == "Connection failed"
        assert mock_connection.call_count == 1  # retries=1

    @patch("core.rabbitmq_manager.pika.BlockingConnection")
    @patch("core.rabbitmq_manager.time.sleep")
    def test_connect_retry_logic(self, mock_sleep, mock_connection):
        # Test with more retries
        rabbitmq = RabbitMQ(retries=3, delay=0.1)
        mock_connection.side_effect = [
            Exception("Fail 1"),
            Exception("Fail 2"),
            MagicMock(),
        ]

        rabbitmq.connect()

        assert mock_connection.call_count == 3

    def test_publish_without_connection(self, rabbitmq):
        with pytest.raises(Exception) as excinfo:
            rabbitmq.publish("test_queue", "message")
        assert "Connection is not established" in str(excinfo.value)

    def test_consume_without_connection(self, rabbitmq):
        with pytest.raises(Exception) as excinfo:
            rabbitmq.consume("test_queue", lambda x: x)
        assert "Connection is not established" in str(excinfo.value)

    def test_create_queue_without_connection(self, rabbitmq):
        with pytest.raises(Exception) as excinfo:
            rabbitmq.create_queue("test_queue")
        assert "Connection is not established" in str(excinfo.value)

    @patch("core.rabbitmq_manager.pika.BlockingConnection")
    def test_publish_success(self, mock_connection, rabbitmq):
        # Setup connection
        mock_conn_instance = MagicMock()
        mock_channel = MagicMock()
        mock_connection.return_value = mock_conn_instance
        mock_conn_instance.channel.return_value = mock_channel

        rabbitmq.connect()

        # Execute
        rabbitmq.publish("test_queue", "message")

        # Verify
        mock_channel.basic_publish.assert_called_once()
        args, kwargs = mock_channel.basic_publish.call_args
        assert kwargs["routing_key"] == "test_queue"
        assert kwargs["body"] == "message"

    @patch("core.rabbitmq_manager.pika.BlockingConnection")
    def test_close(self, mock_connection, rabbitmq):
        # Setup connection
        mock_conn_instance = MagicMock()
        mock_connection.return_value = mock_conn_instance
        mock_conn_instance.is_closed = False

        rabbitmq.connect()
        rabbitmq.close()

        mock_conn_instance.close.assert_called_once()

    @patch("core.rabbitmq_manager.pika.BlockingConnection")
    def test_create_queue_success(self, mock_connection, rabbitmq):
        # Setup connection
        mock_conn_instance = MagicMock()
        mock_channel = MagicMock()
        mock_connection.return_value = mock_conn_instance
        mock_conn_instance.channel.return_value = mock_channel

        rabbitmq.connect()

        # Execute
        rabbitmq.create_queue("test_queue")

        # Verify
        mock_channel.queue_declare.assert_called_once_with(
            queue="test_queue",
            passive=False,
            durable=True,
            exclusive=False,
            auto_delete=False,
        )

    @patch("core.rabbitmq_manager.pika.BlockingConnection")
    def test_delete_queue_success(self, mock_connection, rabbitmq):
        # Setup connection
        mock_conn_instance = MagicMock()
        mock_channel = MagicMock()
        mock_connection.return_value = mock_conn_instance
        mock_conn_instance.channel.return_value = mock_channel

        rabbitmq.connect()

        # Execute
        rabbitmq.delete_queue("test_queue")

        # Verify
        mock_channel.queue_delete.assert_called_once_with("test_queue")

    @patch("core.rabbitmq_manager.pika.BlockingConnection")
    def test_consume_success(self, mock_connection, rabbitmq):
        # Setup connection
        mock_conn_instance = MagicMock()
        mock_channel = MagicMock()
        mock_connection.return_value = mock_conn_instance
        mock_conn_instance.channel.return_value = mock_channel

        rabbitmq.connect()
        callback = MagicMock()

        # Execute
        rabbitmq.consume("test_queue", callback)

        # Verify
        mock_channel.basic_consume.assert_called_once_with(
            queue="test_queue", on_message_callback=callback, auto_ack=True
        )
        mock_channel.start_consuming.assert_called_once()
