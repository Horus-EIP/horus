import os
import time
import pika


def _connect_with_retry(host: str, retries: int = 20, delay_seconds: float = 1.0):
    last_err = None
    for _ in range(retries):
        try:
            return pika.BlockingConnection(
                pika.ConnectionParameters(
                    host=host,
                    heartbeat=600,  # increase heartbeat interval to tolerate long tasks
                    blocked_connection_timeout=300,
                )
            )
        except Exception as e:
            last_err = e
            time.sleep(delay_seconds)
    raise last_err


RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "localhost")
connection = _connect_with_retry(RABBITMQ_HOST)
channel = connection.channel()
