import time

import pika

from core.config import (settings)
from core.logger import get_logger

logger = get_logger("rabbitmq_manager")


class RabbitMQ:
    def __init__(self, retries=500, delay=1.0):
        self.user = settings.rabbitmq_user
        self.password = settings.rabbitmq_password
        self.host = settings.rabbitmq_host
        self.port = settings.rabbitmq_port
        self.connection = None
        self.channel = None
        self.retries = retries
        self.delay_with_seconds = delay

    def connect(self):
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
                return True
            except Exception as e:
                last_err = e
                logger.warning(
                    f"RabbitMQ connection attempt failed: {str(e)}. Retrying in {timeout}s..."
                )
                time.sleep(timeout)
                timeout *= 2
        raise last_err

    def close(self):
        if self.connection and not self.connection.is_closed:
            self.connection.close()

    def consume(self, queue_name, callback):
        if not self.channel:
            raise Exception("Connection is not established.")
        self.channel.basic_consume(
            queue=queue_name, on_message_callback=callback, auto_ack=True
        )
        self.channel.start_consuming()

    def publish(self, queue_name, message):
        if not self.channel:
            raise Exception("Connection is not established.")
        self.channel.basic_publish(
            exchange="",
            routing_key=queue_name,
            body=message,
            properties=pika.BasicProperties(
                delivery_mode=2,
            ),
        )
        logger.info(f"Sent message to queue {queue_name}: {message}")

    def create_queue(self, queue_name):
        if not self.channel:
            raise Exception("Connection is not established.")
        self.channel.queue_declare(
            queue=queue_name,
            passive=False,
            durable=True,
            exclusive=False,
            auto_delete=False,
        )

    def delete_queue(self, queue_name):
        self.channel.queue_delete(queue_name)
