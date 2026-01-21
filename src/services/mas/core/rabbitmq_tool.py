from fastapi import APIRouter, Response, status

from core.logger import get_logger
from core.rabbitmq_manager import RabbitMQ

router = APIRouter(prefix="/rabbitmq", tags=["RabbitMQ"])
logger = get_logger("rabbitmq")

rabbitmq_instance = RabbitMQ()


def check_rabbit_mq():
    try:
        instance = RabbitMQ(retries=1, delay=0.1)
        instance.connect()
        if instance.connection and instance.connection.is_open:
            instance.close()
            return True
        return False
    except Exception:
        return False


@router.post("/heartbeat")
def test_rabbitmq_connectivity():
    if check_rabbit_mq():
        return {"status": "ok"}
    return Response(
        content='{"status"}: "unhealthy"',
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        media_type="application/json",
    )
