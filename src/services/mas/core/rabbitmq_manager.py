import time

import pika
from opentelemetry import trace
from opentelemetry.propagate import extract, inject

from core.config import settings
from core.logger import get_logger

logger = get_logger("rabbitmq_manager")
tracer = trace.get_tracer(__name__)


class RabbitMQ:
    """
    A robust RabbitMQ client wrapper handling connection management, retries, and OpenTelemetry tracing.

    This class provides methods to connect, publish, and consume messages with built-in
    connection recovery and error handling. It supports durable queues with priority
    arguments and integrates distributed tracing context propagation.
    """

    def __init__(self, retries=500, delay=1.0):
        """
        Initialize the RabbitMQ manager.

        Args:
            retries (int, optional): Maximum number of connection retry attempts. Defaults to 500.
            delay (float, optional): Initial delay between retries in seconds. Defaults to 1.0.
        """
        self.user = settings.rabbitmq_user
        self.password = settings.rabbitmq_password
        self.host = settings.rabbitmq_host
        self.port = settings.rabbitmq_port
        self.connection = None
        self.channel = None
        self.retries = retries
        self.delay_with_seconds = delay

    def _ensure_connection(self):
        """
        Verify that the RabbitMQ connection and channel are active.

        If the connection or channel is closed or missing, this method triggers
        a reconnection attempt.
        """
        if (
            not self.connection
            or self.connection.is_closed
            or not self.channel
            or self.channel.is_closed
        ):
            logger.info("RabbitMQ connection lost or closed, reconnecting...")
            self.connect()

    def _execute_with_retry(self, func):
        """
        Execute a function with automatic connection recovery and retry logic.

        Args:
            func (callable): The function to execute.

        Returns:
            Any: The result of the executed function.

        Raises:
            pika.exceptions.AMQPError: If the operation fails after reconnection attempts.
        """
        try:
            self._ensure_connection()
            return func()
        except pika.exceptions.AMQPError as e:
            logger.warning(
                f"RabbitMQ error {type(e).__name__}: {e}, reconnecting and retrying..."
            )
            try:
                self.connect()
            except Exception as conn_err:
                logger.error(f"Failed to reconnect: {conn_err}")
                raise e

            return func()

    def connect(self):
        """
        Establish a blocking connection to the RabbitMQ server.

        Attempts to connect using the configured credentials and host settings.
        Implements an exponential backoff strategy for retries upon failure.

        Returns:
            bool: True if connection is successful.

        Raises:
            Exception: The last exception encountered if all retry attempts fail.
        """
        last_err = None
        timeout = self.delay_with_seconds
        for _ in range(self.retries):
            try:
                credentials = pika.PlainCredentials(self.user, self.password)
                parameters = pika.ConnectionParameters(
                    host=self.host,
                    port=self.port,
                    credentials=credentials,
                    heartbeat=600,
                    blocked_connection_timeout=300,
                )
                self.connection = pika.BlockingConnection(parameters)
                self.channel = self.connection.channel()
                logger.info(f"Connected to RabbitMQ at {self.host}:{self.port}")
                return True
            except Exception as e:
                last_err = e
                logger.warning(
                    f"RabbitMQ connection attempt failed: {str(e)}. Retrying in {timeout}s..."
                )
                time.sleep(timeout)
                timeout *= 2

        logger.error(
            f"RabbitMQ connection failed after {self.retries} retries: {last_err}"
        )
        raise last_err

    def close(self):
        """
        Close the active RabbitMQ connection if it exists and is open.
        """
        if self.connection and not self.connection.is_closed:
            self.connection.close()

    def create_queue(self, queue_name):
        """
        Declare a durable queue with priority support.

        Args:
            queue_name (str): The name of the queue to create.
        """

        def _action():
            self.channel.queue_declare(
                queue=queue_name,
                passive=False,
                durable=True,
                exclusive=False,
                auto_delete=False,
                arguments={"x-max-priority": 10},
            )

        self._execute_with_retry(_action)

    def delete_queue(self, queue_name):
        """
        Delete a specified queue.

        Args:
            queue_name (str): The name of the queue to delete.
        """
        self._execute_with_retry(lambda: self.channel.queue_delete(queue_name))

    def consume(self, queue_name, callback):
        """
        Start consuming messages from a specific queue.

        Starts a blocking consumption loop. The callback is wrapped with OpenTelemetry
        tracing to propagate context from message headers.

        Args:
            queue_name (str): The name of the queue to consume from.
            callback (callable): The function to call when a message is received.
                                 Signature: (ch, method, properties, body)
        """

        def _action():
            # Strategically ensure queue exists before consuming
            self.channel.queue_declare(
                queue=queue_name,
                passive=False,
                durable=True,
                exclusive=False,
                auto_delete=False,
                arguments={"x-max-priority": 10},
            )

            def traced_callback(ch, method, properties, body):
                ctx = extract(properties.headers or {})
                with tracer.start_as_current_span(
                    f"{queue_name} process",
                    context=ctx,
                    kind=trace.SpanKind.CONSUMER,
                ):
                    callback(ch, method, properties, body)

            self.channel.basic_consume(
                queue=queue_name, on_message_callback=traced_callback, auto_ack=True
            )
            self.channel.start_consuming()

        self._execute_with_retry(_action)

    def publish(self, queue_name, message, priority_value=1):
        """
        Publish a message to a specific queue.

        Ensures the queue exists before publishing. Injects OpenTelemetry tracing
        context into the message headers for distributed tracing.

        Args:
            queue_name (str): The target queue name.
            message (str or bytes): The message body to publish.
            priority_value (int, optional): The priority of the message (0-10). Defaults to 1.
        """

        def _action():
            # Strategically ensure queue exists before publishing
            self.channel.queue_declare(
                queue=queue_name,
                passive=False,
                durable=True,
                exclusive=False,
                auto_delete=False,
                arguments={"x-max-priority": 10},
            )

            headers = {}
            inject(headers)

            self.channel.basic_publish(
                exchange="",
                routing_key=queue_name,
                body=message,
                properties=pika.BasicProperties(
                    delivery_mode=2, headers=headers, priority=priority_value
                ),
            )
            logger.info(f"Sent message to queue {queue_name}: {message}")

        self._execute_with_retry(_action)

    # ------------------------------------------------------------------
    # Agent-to-agent communication helpers
    # ------------------------------------------------------------------

    def ensure_agent_comm_queue(self, agent_id: str) -> str:
        """Declare a durable communication queue for an agent and return its name."""
        queue_name = f"agent_comm_{agent_id}"
        self.create_queue(queue_name)
        return queue_name

    def publish_agent_message(self, receiver_agent_id: str, message_json: str) -> None:
        """Publish a JSON-encoded AgentMessage to the receiver's comm queue."""
        queue_name = f"agent_comm_{receiver_agent_id}"
        self.publish(queue_name, message_json)
