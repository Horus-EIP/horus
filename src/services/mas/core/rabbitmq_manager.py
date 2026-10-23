import threading
import time

import pika
from opentelemetry import trace
from opentelemetry.propagate import extract, inject
from pika.exceptions import ChannelClosedByBroker, NackError, UnroutableError

from core.config import settings
from core.logger import get_logger

logger = get_logger("rabbitmq_manager")
tracer = trace.get_tracer(__name__)

PRIORITY_QUEUE_ARGUMENTS = {"x-max-priority": 10}
WORK_QUEUE_OVERFLOW = "reject-publish"
DEFAULT_WORK_QUEUE_MAX_LENGTH = 10
PRECONDITION_FAILED = 406


class WorkQueueFull(Exception):
    def __init__(self, queue: str, depth: int) -> None:
        super().__init__(f"Work queue {queue} is full: {depth} task(s) are waiting in it")
        self.queue = queue
        self.depth = depth


class WorkQueueUnroutable(Exception):
    def __init__(self, queue: str) -> None:
        super().__init__(f"RabbitMQ could not route a task to work queue {queue}")
        self.queue = queue


def work_queue_max_length() -> int:
    return getattr(settings, "work_queue_max_length", None) or DEFAULT_WORK_QUEUE_MAX_LENGTH


def work_queue_arguments(max_length: int) -> dict:
    return {
        **PRIORITY_QUEUE_ARGUMENTS,
        "x-max-length": max_length,
        "x-overflow": WORK_QUEUE_OVERFLOW,
    }


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
        self._lock = threading.RLock()

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
            logger.warning(f"RabbitMQ error {type(e).__name__}: {e}, reconnecting and retrying...")
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
                self._open_channel()
                logger.info(f"Connected to RabbitMQ at {self.host}:{self.port}")
                return True
            except Exception as e:
                last_err = e
                logger.warning(
                    f"RabbitMQ connection attempt failed: {str(e)}. Retrying in {timeout}s..."
                )
                time.sleep(timeout)
                timeout *= 2

        logger.error(f"RabbitMQ connection failed after {self.retries} retries: {last_err}")
        raise last_err

    def _open_channel(self):
        self.channel = self.connection.channel()
        self.channel.confirm_delivery()

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
                arguments=PRIORITY_QUEUE_ARGUMENTS,
            )

        with self._lock:
            self._execute_with_retry(_action)

    def delete_queue(self, queue_name):
        """
        Delete a specified queue.

        Args:
            queue_name (str): The name of the queue to delete.
        """
        with self._lock:
            self._execute_with_retry(lambda: self.channel.queue_delete(queue_name))

    def ensure_work_queue(self, queue_name: str) -> int:
        with self._lock:
            depth, _bounded = self._execute_with_retry(lambda: self._declare_work_queue(queue_name))
        return depth

    def work_queue_depth(self, queue_name: str) -> int:
        with self._lock:
            return self._execute_with_retry(lambda: self._ready_count(queue_name))

    def _ready_count(self, queue_name: str) -> int:
        declared = self.channel.queue_declare(queue=queue_name, passive=True)
        return int(declared.method.message_count)

    def _declare_bounded(self, queue_name: str, max_length: int) -> int:
        declared = self.channel.queue_declare(
            queue=queue_name,
            passive=False,
            durable=True,
            exclusive=False,
            auto_delete=False,
            arguments=work_queue_arguments(max_length),
        )
        return int(declared.method.message_count)

    def _declare_work_queue(self, queue_name: str) -> tuple[int, bool]:
        max_length = work_queue_max_length()
        try:
            return self._declare_bounded(queue_name, max_length), True
        except ChannelClosedByBroker as exc:
            if exc.reply_code != PRECONDITION_FAILED:
                raise
        self._open_channel()
        return self._redeclare_when_empty(queue_name, max_length)

    def _redeclare_when_empty(self, queue_name: str, max_length: int) -> tuple[int, bool]:
        depth = self._ready_count(queue_name)
        if depth == 0:
            try:
                self.channel.queue_delete(queue=queue_name, if_empty=True)
                depth = self._declare_bounded(queue_name, max_length)
            except ChannelClosedByBroker as exc:
                if exc.reply_code != PRECONDITION_FAILED:
                    raise
                self._open_channel()
                depth = self._ready_count(queue_name)
            else:
                logger.info(
                    "Work queue %s re-declared with x-max-length=%s and x-overflow=%s",
                    queue_name,
                    max_length,
                    WORK_QUEUE_OVERFLOW,
                )
                return depth, True
        logger.warning(
            "Work queue %s was declared with other arguments and still holds %s "
            "task(s); MAS keeps it to %s waiting tasks itself and re-declares it "
            "with x-max-length and x-overflow=%s once it is empty",
            queue_name,
            depth,
            max_length,
            WORK_QUEUE_OVERFLOW,
        )
        return depth, False

    def _publish_confirmed(self, queue_name: str, message, priority_value: int) -> None:
        depth, bounded = self._declare_work_queue(queue_name)
        if not bounded and depth >= work_queue_max_length():
            raise WorkQueueFull(queue_name, depth)
        headers = {}
        inject(headers)
        try:
            self.channel.basic_publish(
                exchange="",
                routing_key=queue_name,
                body=message,
                properties=pika.BasicProperties(
                    delivery_mode=2, headers=headers, priority=priority_value
                ),
                mandatory=True,
            )
        except NackError:
            raise WorkQueueFull(queue_name, self._ready_count(queue_name)) from None

    def publish_task(self, queue_name: str, message, priority_value: int = 1) -> None:
        def _action():
            try:
                self._publish_confirmed(queue_name, message, priority_value)
            except UnroutableError:
                logger.warning(
                    "RabbitMQ returned a task sent to %s as unroutable; declaring the "
                    "queue and sending the task again",
                    queue_name,
                )
                try:
                    self._publish_confirmed(queue_name, message, priority_value)
                except UnroutableError:
                    raise WorkQueueUnroutable(queue_name) from None
            logger.info(f"Sent task to work queue {queue_name}")

        with (
            tracer.start_as_current_span(
                f"publish {queue_name}",
                kind=trace.SpanKind.PRODUCER,
                attributes={
                    "messaging.system": "rabbitmq",
                    "messaging.destination.name": queue_name,
                },
            ),
            self._lock,
        ):
            self._execute_with_retry(_action)

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

        with (
            tracer.start_as_current_span(
                f"publish {queue_name}",
                kind=trace.SpanKind.PRODUCER,
                attributes={
                    "messaging.system": "rabbitmq",
                    "messaging.destination.name": queue_name,
                },
            ),
            self._lock,
        ):
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
