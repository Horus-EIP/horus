from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from core.rabbitmq_tool import router

client = TestClient(router)


def test_heartbeat_success():
    with patch("core.rabbitmq_tool.RabbitMQ") as MockRabbitMQ:
        # Setup mock to simulate successful connection
        mock_instance = MockRabbitMQ.return_value
        mock_instance.connection.is_open = True

        response = client.post("/rabbitmq/heartbeat")

        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
        mock_instance.connect.assert_called_once()
        mock_instance.close.assert_called_once()


def test_heartbeat_failure_connection_closed():
    with patch("core.rabbitmq_tool.RabbitMQ") as MockRabbitMQ:
        # Setup mock to simulate failed connection (closed)
        mock_instance = MockRabbitMQ.return_value
        mock_instance.connection.is_open = False

        response = client.post("/rabbitmq/heartbeat")

        assert response.status_code == 503
        # Note: The current implementation returns a stringified JSON in content,
        # so we check the status code primarily.
        # If we want to check the body, we need to match the implementation's specific return format.


def test_heartbeat_failure_exception():
    with patch("core.rabbitmq_tool.RabbitMQ") as MockRabbitMQ:
        # Setup mock to raise exception during connect
        mock_instance = MockRabbitMQ.return_value
        mock_instance.connect.side_effect = Exception("Connection failed")

        response = client.post("/rabbitmq/heartbeat")

        assert response.status_code == 503
