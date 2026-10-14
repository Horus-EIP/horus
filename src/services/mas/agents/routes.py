"""HTTP routes for agent registration, heartbeat, and lookup.

All endpoints are RBAC-gated; heartbeats additionally require the agent's
``X-API-Key`` + ``Agent-ID`` headers. See
``docs/architecture.md`` for full payloads and error codes.
"""

from typing import Annotated

from agents.openapi_docs import (AGENT_DETAILS_RESPONSES, HEARTBEAT_RESPONSES,
                                 LIST_AGENTS_RESPONSES,
                                 REGENERATE_KEY_RESPONSES,
                                 REGISTER_AGENT_OPENAPI_EXTRA,
                                 REGISTER_AGENT_RESPONSES,
                                 UNREGISTER_AGENT_RESPONSES)
from agents.registry_tool_functions import (create_agent, delete_agent,
                                            get_agent_details, get_agent_id,
                                            get_all_agents,
                                            regenerate_agent_api_key,
                                            update_alive_agent_status)
from auth.auth_tool_functions import PermissionChecker, verify_agent_api_key
from auth.permissions import Permission
from core.logger import log_agent_operation, log_error
from core.metrics import AGENT_COUNT
from db.database import get_db
from db.models import AgentTypes
from fastapi import APIRouter, Depends, HTTPException
from schemas.schemas import RegistrationForm
from sqlalchemy.orm import Session

router = APIRouter(prefix="/agents", tags=["Agents"])


@router.post(
    "/register",
    summary="Register a new agent",
    description="Register a new agent with specified skills and capabilities. Agent name must be unique. Ensures the shared RabbitMQ work queue for this agent type exists for pooled workers.",
    status_code=200,
    dependencies=[Depends(PermissionChecker(Permission.AGENT_CREATE))],
    tags=["Agents"],
    responses=REGISTER_AGENT_RESPONSES,
    openapi_extra=REGISTER_AGENT_OPENAPI_EXTRA,
)
async def handle_agent_creation(
    agent: RegistrationForm,
    user: Annotated[dict, Depends(PermissionChecker(Permission.AGENT_CREATE))],
    db: Session = Depends(get_db),
):
    """Register a new agent and provision its RabbitMQ queue.

    This function:
    1. Checks if an agent with the same name already exists.
    2. Creates a new agent record in the database with an API key.
    3. Ensures the shared RabbitMQ work queue for the agent's type exists.
    4. Logs the registration event.

    Args:
        agent (RegistrationForm): The agent registration details (name, skills, description).
        user (dict): The authenticated user performing the registration.
        db (Session): Database session.

    Returns:
        dict: detailed response containing the new agent ID and API Key.

    Raises:
        HTTPException:
            - 409: If agent name already exists.
            - 500: If database or message queue provisioning fails.
    """
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication Failed")

    agent_id, api_key, alive = await create_agent(
        agent.name,
        agent.skills,
        agent.description,
        db,
        agent.type or AgentTypes.GENERAL,
    )

    if alive:
        log_error("AGENT", f"An agent already has the name {agent.name} and is active")
        raise HTTPException(status_code=409, detail="Failed to create agent")

    if agent_id is None:
        log_error("AGENT", f"Failed to create agent {agent.name}")
        raise HTTPException(status_code=500, detail="Failed to create agent")

    log_agent_operation(
        agent.name, "REGISTER", f"ID: {agent_id}, Skills: {agent.skills}"
    )

    AGENT_COUNT.labels(status="active").inc()

    return {
        "message": f"agent with name {agent.name} successfully created",
        "agent_id": agent_id,
        "api_key": api_key,
    }


@router.post(
    "/regenerate-key/{agent_id}",
    summary="Regenerate an agent's API key",
    description=(
        "Issue a fresh API key for an existing agent, invalidating the old one. "
        "Use this when a key is lost: stored keys are hashed and can never be "
        "retrieved, only replaced. The new key is returned exactly once and must "
        "be saved immediately — the agent has to be reconfigured with it to keep "
        "sending heartbeats. Requires AGENT_UPDATE permission (admin only)."
    ),
    status_code=200,
    dependencies=[Depends(PermissionChecker(Permission.AGENT_UPDATE))],
    tags=["Agents"],
    responses=REGENERATE_KEY_RESPONSES,
)
async def regenerate_agent_key(
    agent_id: str,
    user: Annotated[dict, Depends(PermissionChecker(Permission.AGENT_UPDATE))],
    db: Session = Depends(get_db),
):
    """Rotate an agent's API key and return the new plaintext once.

    The previous key stops working immediately. Raises 401 if unauthenticated
    and 404 if the agent does not exist.
    """
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication Failed")

    api_key = regenerate_agent_api_key(agent_id, db)

    if api_key is None:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")

    log_agent_operation(agent_id, "REGENERATE_KEY", "API key rotated")

    return {
        "message": f"API key regenerated for agent {agent_id}",
        "agent_id": agent_id,
        "api_key": api_key,
    }


@router.delete(
    "/unregister/{agent_id}",
    summary="Unregister an agent",
    description="Remove an agent from the registry. Shared type work queues (e.g. horus.work.general) are not deleted because other pool workers may still use them. Only admin users can perform this operation.",
    status_code=200,
    dependencies=[Depends(PermissionChecker(Permission.AGENT_DELETE))],
    tags=["Agents"],
    responses=UNREGISTER_AGENT_RESPONSES,
)
async def unregister_agent(
    agent_id: str,
    user: Annotated[dict, Depends(PermissionChecker(Permission.AGENT_DELETE))],
    db: Session = Depends(get_db),
):
    """
    Unregister an agent and clean up its resources.

    1. Removes the agent record from the database.
    2. Does not remove shared type work queues used by other pool members.
    3. Logs the deletion event.

    Args:
        agent_id (str): The UUID of the agent to unregister.
        user (dict): The authenticated user performing the deletion.
        db (Session): Database session.

    Returns:
        dict: Confirmation message.

    Raises:
        HTTPException:
            - 404: If the agent is not found.
    """
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication Failed")
    if delete_agent(agent_id, db):
        log_agent_operation(agent_id, "UNREGISTER", "Agent deleted")
        AGENT_COUNT.labels(status="active").dec()
        return {"message": f"Agent {agent_id} successfully unregistered"}
    else:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")


@router.get(
    "/details/{id}",
    summary="Get agent details",
    description="Retrieve detailed information about a specific agent including name, skills, current status (active/inactive), and last heartbeat timestamp. Requires AGENT_READ permission.",
    status_code=200,
    tags=["Agents"],
    dependencies=[Depends(PermissionChecker(Permission.AGENT_READ))],
    responses=AGENT_DETAILS_RESPONSES,
)
async def agent_details(
    id: str,
    user: Annotated[dict, Depends(PermissionChecker(Permission.AGENT_READ))],
    db: Session = Depends(get_db),
):
    """Return an agent's metadata and last heartbeat. Raises 404 if unknown."""
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication Failed")
    (
        agent_id,
        agent_name,
        agent_skills,
        agent_status,
        agent_heartbeat,
        agent_description,
        agent_creation_date,
    ) = get_agent_details(id, db)
    if agent_id is not None:
        log_agent_operation(agent_name, "READ", "Details viewed")
        return {
            "name": agent_name,
            "skills": agent_skills,
            "status": agent_status,
            "last_heartbeat": agent_heartbeat,
            "description": agent_description,
            "created_at": agent_creation_date,
        }
    else:
        raise HTTPException(status_code=404, detail=f"Agent {id} not found")


@router.get("/details", include_in_schema=False)
@router.get(
    "/details/",
    summary="List all agents",
    description="Returned informations of all of the agents registered: agent id, name, skills, status, last heartbeat. Requires AGENT_READ permission.",
    status_code=200,
    dependencies=[Depends(PermissionChecker(Permission.AGENT_READ))],
    tags=["Agents"],
    responses=LIST_AGENTS_RESPONSES,
)
async def get_all_agents_details(
    user: Annotated[dict, Depends(PermissionChecker(Permission.AGENT_READ))],
    db: Session = Depends(get_db),
):
    """List every registered agent with current status + last heartbeat."""
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication Failed")
    agents = get_all_agents(db)
    log_agent_operation("ALL", "LIST", f"Retrieved {len(agents)} agents")
    return agents


@router.post(
    "/heartbeat/{agent_id}",
    summary="Send agent heartbeat",
    description=(
        "Updates the agent status to 'active' and refreshes the 'last_heartbeat' field. "
        "Used by agents to signal that they are alive and operational. Requires AGENT_EXECUTE permission. "
        "Requires 'X-API-Key' and 'Agent-ID' headers for authentication."
    ),
    status_code=200,
    dependencies=[Depends(PermissionChecker(Permission.AGENT_EXECUTE))],
    tags=["Agents"],
    responses=HEARTBEAT_RESPONSES,
)
async def detect_alive_agents(
    agent_id: str,
    verified_agent: Annotated[tuple[str, str], Depends(verify_agent_api_key)],
    db: Session = Depends(get_db),
):
    """Record a heartbeat from an authenticated agent.

    Raises 403 on ID/key mismatch, 404 if the agent is unknown.
    """
    verified_agent_id, _ = verified_agent
    if verified_agent_id != agent_id:
        raise HTTPException(status_code=403, detail="Agent ID mismatch")

    update = update_alive_agent_status(agent_id, db)
    if update:
        return {"message": f"Heartbeat received for the agent {agent_id}"}
    else:
        raise HTTPException(status_code=404, detail=f"Agent {agent_id} not found")
