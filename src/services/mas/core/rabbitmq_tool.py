
from fastapi import APIRouter, Response, status
from pydantic import BaseModel

from core.logger import get_logger
from core.rabbitmq_manager import RabbitMQ

router = APIRouter(prefix="/rabbitmq", tags=["RabbitMQ"])
logger = get_logger("rabbitmq")

rabbitmq_instance = RabbitMQ()

# Lazy-initialised communicator (set up after RabbitMQ connects)
_agent_communicator = None


def get_agent_communicator():
    """Return the singleton AgentCommunicator, creating it on first access."""
    global _agent_communicator
    if _agent_communicator is None:
        from core.agent_communication import AgentCommunicator
        _agent_communicator = AgentCommunicator(rabbitmq_instance)
    return _agent_communicator


def check_rabbit_mq():
    try:
        instance = RabbitMQ(retries=1, delay=0.1)
        instance.connect()
        if instance.connection and instance.connection.is_open:
            instance.close()
            return True
        return False
    except Exception as e:
        logger.warning("RabbitMQ health check failed", error=str(e))
        return False


@router.post(
    "/heartbeat",
    summary="Test RabbitMQ connectivity",
    description="Verifies that the RabbitMQ message broker is accessible and operational. Used for system health checks and monitoring. Returns status 200 if RabbitMQ is healthy, 503 if unreachable.",
    status_code=200,
    tags=["RabbitMQ"],
    responses={
        200: {
            "description": "RabbitMQ is healthy and responsive",
            "content": {
                "application/json": {
                    "examples": {
                        "healthy": {
                            "summary": "RabbitMQ connection successful",
                            "value": {"status": "ok"},
                        }
                    }
                }
            },
        },
        503: {
            "description": "RabbitMQ is unavailable or unreachable",
            "content": {
                "application/json": {
                    "examples": {
                        "unhealthy": {
                            "summary": "RabbitMQ connection failed",
                            "value": {"status": "unhealthy"},
                        }
                    }
                }
            },
        },
    },
)
def test_rabbitmq_connectivity():
    if check_rabbit_mq():
        return {"status": "ok"}
    return Response(
        content='{"status": "unhealthy"}',
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        media_type="application/json",
    )


# ------------------------------------------------------------------
# Agent-to-agent communication & delegation endpoints
# ------------------------------------------------------------------


class DelegationRequestBody(BaseModel):
    sender_agent_id: str
    to_agent_type: str
    request: str
    data: dict = {}
    conversation_id: str = ""
    delegation_chain: list = []
    delegation_context: list = []
    timeout_seconds: float = 30.0


class DelegationResultBody(BaseModel):
    delegation_id: str
    result: str
    agent_id: str


@router.post(
    "/delegate",
    summary="Delegate work to another agent",
    description=(
        "Accepts a delegation request from an agent, selects the best target "
        "agent, routes the work, and waits for a result (with timeout)."
    ),
    tags=["Agent Communication"],
)
async def delegate_to_agent(body: DelegationRequestBody):
    from agents.registry_tool_functions import _get_all_agents_internal
    from db.database import SessionLocal
    from schemas.agent_message import DelegationRequest

    communicator = get_agent_communicator()

    def select_agent(agent_type: str) -> str | None:
        db = SessionLocal()
        try:
            agents = _get_all_agents_internal(db)
            for agent in agents:
                skills = agent.skills if isinstance(agent.skills, list) else []
                if (
                    agent.status == "active"
                    and agent.id != body.sender_agent_id
                    and (
                        agent_type in skills
                        or agent_type.lower() in agent.name.lower()
                        or agent_type.lower() in (agent.description or "").lower()
                    )
                ):
                    return agent.id
            return None
        finally:
            db.close()

    req = DelegationRequest(
        sender_agent_id=body.sender_agent_id,
        to_agent_type=body.to_agent_type,
        request=body.request,
        data=body.data,
        conversation_id=body.conversation_id,
        delegation_chain=body.delegation_chain,
        delegation_context=body.delegation_context,
        timeout_seconds=body.timeout_seconds,
    )

    response = await communicator.handle_delegation(req, select_agent)
    return response.model_dump()


@router.post(
    "/delegation-result",
    summary="Submit delegation result",
    description="Called by the delegate agent to report the result of a delegation.",
    tags=["Agent Communication"],
)
def receive_delegation_result(body: DelegationResultBody):
    communicator = get_agent_communicator()
    resolved = communicator.receive_delegation_result(
        delegation_id=body.delegation_id,
        result=body.result,
        agent_id=body.agent_id,
    )
    if resolved:
        return {"status": "ok", "delegation_id": body.delegation_id}
    return Response(
        content='{"status": "not_found", "detail": "No pending delegation with this ID"}',
        status_code=status.HTTP_404_NOT_FOUND,
        media_type="application/json",
    )


@router.get(
    "/messages/{agent_id}",
    summary="Get messages for an agent",
    description="Returns persisted messages for debugging and audit.",
    tags=["Agent Communication"],
)
def get_agent_messages(agent_id: str):
    communicator = get_agent_communicator()
    return communicator.get_messages_for_agent(agent_id)
