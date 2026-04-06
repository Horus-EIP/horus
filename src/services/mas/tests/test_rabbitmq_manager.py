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
        # Mock connect to verify behavior when connection fails
        with patch.object(rabbitmq, 'connect', side_effect=Exception("Connection is not established")):
            with pytest.raises(Exception) as excinfo:
                rabbitmq.publish("test_queue", "message")
            assert "Connection is not established" in str(excinfo.value)

    def test_consume_without_connection(self, rabbitmq):
        with patch.object(rabbitmq, 'connect', side_effect=Exception("Connection is not established")):
            with pytest.raises(Exception) as excinfo:
                rabbitmq.consume("test_queue", lambda x: x)
            assert "Connection is not established" in str(excinfo.value)

    def test_create_queue_without_connection(self, rabbitmq):
        with patch.object(rabbitmq, 'connect', side_effect=Exception("Connection is not established")):
            with pytest.raises(Exception) as excinfo:
                rabbitmq.create_queue("test_queue")
            assert "Connection is not established" in str(excinfo.value)

    @patch("core.rabbitmq_manager.pika.BlockingConnection")
    @patch("core.rabbitmq_manager.inject")
    def test_publish_success(self, mock_inject, mock_connection, rabbitmq):
        # Setup connection
        mock_conn_instance = MagicMock()
        mock_channel = MagicMock()
        mock_connection.return_value = mock_conn_instance
        mock_conn_instance.channel.return_value = mock_channel

        rabbitmq.connect()

        # Execute
        rabbitmq.publish("test_queue", "message")

        # Verify
        mock_inject.assert_called_once()
        mock_channel.basic_publish.assert_called_once()
        args, kwargs = mock_channel.basic_publish.call_args
        assert kwargs["routing_key"] == "test_queue"
        assert kwargs["body"] == "message"
        assert kwargs["properties"].delivery_mode == 2
        assert kwargs["properties"].headers is not None

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
            arguments={"x-max-priority": 10},
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
    @patch("core.rabbitmq_manager.tracer")
    @patch("core.rabbitmq_manager.extract")
    def test_consume_success(
        self, mock_extract, mock_tracer, mock_connection, rabbitmq
    ):
        # Setup connection
        mock_conn_instance = MagicMock()
        mock_channel = MagicMock()
        mock_connection.return_value = mock_conn_instance
        mock_conn_instance.channel.return_value = mock_channel

        rabbitmq.connect()
        original_callback = MagicMock()

        # Execute
        rabbitmq.consume("test_queue", original_callback)

        # Verify basic_consume called with a wrapper
        mock_channel.basic_consume.assert_called_once()
        call_args = mock_channel.basic_consume.call_args
        assert call_args.kwargs["queue"] == "test_queue"
        assert call_args.kwargs["auto_ack"] is True

        # Get the wrapper function
        traced_callback = call_args.kwargs["on_message_callback"]
        assert callable(traced_callback)

        # Test the wrapper function
        mock_ch = MagicMock()
        mock_method = MagicMock()
        mock_properties = MagicMock()
        mock_properties.headers = {"trace-id": "123"}
        mock_body = b"test"

        mock_extract.return_value = "context"
        mock_span = MagicMock()
        mock_tracer.start_as_current_span.return_value.__enter__.return_value = (
            mock_span
        )

        # Call the wrapper
        traced_callback(mock_ch, mock_method, mock_properties, mock_body)

        # Verify tracing calls
        mock_extract.assert_called_once_with({"trace-id": "123"})
        mock_tracer.start_as_current_span.assert_called_once()
        assert mock_tracer.start_as_current_span.call_args[0][0] == "test_queue process"
        assert mock_tracer.start_as_current_span.call_args[1]["context"] == "context"

        # Verify original callback called
        original_callback.assert_called_once_with(
            mock_ch, mock_method, mock_properties, mock_body
        )
        mock_channel.start_consuming.assert_called_once()
