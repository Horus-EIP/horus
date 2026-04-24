"""Agent registry CRUD and heartbeat helpers.

Functions prefixed with ``_`` take an explicit ``Session`` and are safe to
call from background tasks. Public variants are used by FastAPI routes.
"""

import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import Depends
from passlib.context import CryptContext
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session

from core.logger import get_logger
from core.rabbitmq_tool import rabbitmq_instance
from db.database import SessionLocal, get_db
from db.models import Agents, AgentTypes

logger = get_logger("registry_tool_functions")

bcrypt_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# ============================================================================
# INTERNAL FUNCTIONS - Without Depends (used by controller.py and other non-route code)
# These functions take explicit Session parameter
# ============================================================================


def _get_all_agents_internal(db: Session) -> list:
    """Return all ``Agents`` rows; empty list if the table is missing."""
    try:
        agents = db.query(Agents).all()

        for agent in agents:
            _ = agent.skills
            _ = agent.status
        return agents
    except ProgrammingError as e:
        if 'relation "agents" does not exist' in str(e):
            logger.debug("Agents table does not exist yet. Skipping agent retrieval.")
            return []
        logger.error(
            f"Database programming error in _get_all_agents_internal: {str(e)}"
        )
        return []
    except Exception as e:
        logger.error(f"Failed to retrieve available agents: {str(e)}")
        return []


def _update_alive_agent_status_internal(agent_id: str, db: Session) -> bool:
    """Mark agent ``active`` and bump ``last_heartbeat``."""
    try:
        agent = db.query(Agents).filter(Agents.id == agent_id).first()
        if agent is None:
            logger.warning(
                f"Agent not found for heartbeat update - Agent ID: {agent_id}"
            )
            return False

        agent.status = "active"
        agent.last_heartbeat = datetime.now(timezone.utc)
        db.commit()
        logger.info(f"Agent heartbeat updated successfully - Agent ID: {agent_id}")
        return True
    except Exception as e:
        db.rollback()
        logger.error(f"Error updating agent heartbeat: {str(e)}")
        return False


def _update_dead_agent_status_internal(agent_id: str, db: Session) -> bool:
    """Mark agent ``dead`` (heartbeat timeout)."""
    try:
        agent = db.query(Agents).filter(Agents.id == agent_id).first()
        if agent is None:
            logger.warning(f"Agent not found for marking dead - Agent ID: {agent_id}")
            return False

        agent.status = "dead"
        db.commit()
        last_heartbeat = agent.last_heartbeat
        if last_heartbeat.tzinfo is None:
            last_heartbeat = last_heartbeat.replace(tzinfo=timezone.utc)

        logger.warning(
            f"Agent marked as dead - Agent ID: {agent_id}, Last heartbeat was {(datetime.now(timezone.utc) - last_heartbeat).total_seconds():.1f}s ago"
        )
        return True
    except Exception as e:
        db.rollback()
        logger.error(f"Error updating agent status: {str(e)}")
        return False


def _batch_update_agent_status_internal(agent_statuses: dict, db: Session) -> bool:
    """Apply ``{agent_id: status}`` in a single commit."""
    try:
        for agent_id, status in agent_statuses.items():
            agent = db.query(Agents).filter(Agents.id == agent_id).first()
            if agent:
                agent.status = status
        db.commit()
        logger.info(
            f"Batch updated {len(agent_statuses)} agents - Status changes: {agent_statuses}"
        )
        return True
    except Exception as e:
        db.rollback()
        logger.error(f"Error batch updating agents: {str(e)}")
        return False


# ============================================================================
# PUBLIC FUNCTIONS - With Depends (used by FastAPI routes)
# Can be called from routes and internally from controller via wrappers
# ============================================================================


def create_agent(
    name: str, skills: list, description: str, db: Session, Agent_type: AgentTypes
) -> tuple[str, str]:
    """Register a new agent and return ``(agent_id, plaintext_api_key)``.

    The API key is bcrypt-hashed before storage; the plaintext is shown to
    the caller exactly once. Also creates the agent's RabbitMQ queue.
    """
    agent_id = str(uuid.uuid4())
    api_key = secrets.token_urlsafe(32)
    hash_api_key = bcrypt_context.hash(api_key)
    try:
        new_agent = Agents(
            id=agent_id,
            name=name,
            skills=skills,
            description=description,
            status="active",
            last_heartbeat=datetime.now(timezone.utc),
            api_key=hash_api_key,
            type=Agent_type,
        )

        db.add(new_agent)
        db.commit()
        db.refresh(new_agent)
        logger.info(f"Agent created successfully: {agent_id} ({name})")

        # Strategic placement: Ensure queue exists immediately upon agent creation
        rabbitmq_instance.create_queue(agent_id)

        return agent_id, api_key
    except Exception as e:
        db.rollback()
        logger.error(f"Error creating agent: {str(e)}")
        return None, None


def delete_agent(agent_id: str, db: Session) -> bool:
    """Permanently delete an agent. Returns ``False`` if not found."""
    try:
        agent = db.get(Agents, agent_id)
        if agent is None:
            return False
        db.delete(agent)
        db.commit()
        return True
    except Exception as e:
        db.rollback()
        logger.error(f"Failed to delete agent - Agent ID: {agent_id}, Error: {str(e)}")
        return False


def get_agent_details(agent_id: str, db: Session):
    """Return ``(id, name, skills, status, last_heartbeat, description, created_at)``.

    All elements are ``None`` if the agent does not exist.
    """
    try:
        agent = db.query(Agents).filter(Agents.id == agent_id).first()
        if agent is None:
            logger.debug(f"Agent details not found - Agent ID: {agent_id}")
            return None, None, None, None, None, None, None

        logger.debug(
            f"Agent details retrieved - Agent ID: {agent_id}, Name: {agent.name}, Status: {agent.status}"
        )
        return (
            agent_id,
            agent.name,
            agent.skills,
            agent.status,
            agent.last_heartbeat,
            agent.description,
            agent.created_at,
        )
    except Exception as e:
        logger.error(
            f"Failed to retrieve agent details - Agent ID: {agent_id}, Error: {str(e)}"
        )
        return None, None, None, None, None, None, None


def get_all_agents(db: Session) -> list:
    """Return all ``Agents`` rows (route-friendly wrapper)."""
    return _get_all_agents_internal(db)


def update_alive_agent_status(agent_id: str, db: Session) -> bool:
    """Mark agent ``active`` and refresh heartbeat."""
    try:
        agent = db.query(Agents).filter(Agents.id == agent_id).first()
        if agent is None:
            return False

        agent.status = "active"
        agent.last_heartbeat = datetime.now(timezone.utc)
        db.commit()
        return True
    except Exception as e:
        db.rollback()
        logger.error(f"Error updating agent heartbeat: {str(e)}")
        return False


def update_dead_agent_status(agent_id: str, db: Session) -> bool:
    """Mark agent ``inactive``."""
    try:
        agent = db.query(Agents).filter(Agents.id == agent_id).first()
        if agent is None:
            logger.debug(
                f"Agent not found for dead status update - Agent ID: {agent_id}"
            )
            return False

        agent.status = "inactive"
        db.commit()
        logger.warning(f"Agent marked inactive - Agent ID: {agent_id}")
        return True
    except Exception as e:
        db.rollback()
        logger.error(f"Error updating agent status: {str(e)}")
        return False


def update_active_status(agent_id: str, db: Session) -> bool:
    """Mark agent ``active`` and refresh heartbeat (route wrapper)."""
    try:
        agent = db.query(Agents).filter(Agents.id == agent_id).first()
        if agent is None:
            return False

        agent.status = "active"
        agent.last_heartbeat = datetime.now(timezone.utc)
        db.commit()
        return True
    except Exception as e:
        db.rollback()
        logger.error(f"Error updating agent status: {str(e)}")
        return False


def get_agent_id(agent_name: str, db: Session) -> str:
    """Return the agent's ID by name, or ``None``."""
    try:
        agent = db.query(Agents).filter(Agents.name == agent_name).first()
        if agent is None:
            return None
        return agent.id
    except Exception as e:
        logger.error(
            f"Failed to retrieve agent ID - Agent Name: {agent_name}, Error: {str(e)}"
        )
        return None


def get_agent_by_type(agent_type: str, db: Session) -> str:
    try:
        if not agent_type:
            return None

        # Clean up common LLM hallucinations like "AgentTypes.RESEARCHER" -> "researcher"
        if "." in agent_type:
            agent_type = agent_type.split(".")[-1]

        target = str(agent_type).lower()

        # simple python filter on active agents
        agents = db.query(Agents).filter(Agents.status == "active").all()
        # Sort by created_at descending (newest first)
        agents.sort(key=lambda x: str(x.created_at or ""), reverse=True)

        for a in agents:
            val = a.type.value if hasattr(a.type, "value") else a.type
            if str(val).lower() == target:
                return a.id

        # Fallback to any agent (case insensitive)
        all_agents = db.query(Agents).all()
        for a in all_agents:
            val = a.type.value if hasattr(a.type, "value") else a.type
            if str(val).lower() == target:
                return a.id

        return None
    except Exception as e:
        logger.error(f"Error in get_agent_by_type: {e}")
        return None


def _is_agent_recently_alive(agent_info, max_age_seconds: int = 90) -> bool:
    last_heartbeat = agent_info.last_heartbeat
    if not last_heartbeat:
        return False
    try:
        current_time = datetime.now(timezone.utc)
        if last_heartbeat.tzinfo is None:
            last_heartbeat = last_heartbeat.replace(tzinfo=timezone.utc)
        return (current_time - last_heartbeat) <= timedelta(seconds=max_age_seconds)
    except Exception as e:
        logger.error(f"Error checking agent liveness: {e}")
        return False


def get_available_agents(db: Session) -> list:
    """Return agents with a recent heartbeat as ``(id, name, desc, type)`` tuples."""
    available_agents = []

    try:
        agents = db.query(Agents).all()

        if not agents:
            logger.debug("No agents registered in system")
            return available_agents

        for agent in agents:
            if _is_agent_recently_alive(agent):
                available_agents.append(
                    (agent.id, agent.name, agent.description or "", agent.type)
                )

        logger.info(
            f"Agent availability check - Available: {len(available_agents)}/{len(agents)}"
        )
        return available_agents
    except ProgrammingError as e:
        if 'relation "agents" does not exist' in str(e):
            logger.debug(
                "Agents table does not exist yet. Skipping availability check."
            )
            return available_agents
        logger.error(f"Database programming error in get_available_agents: {str(e)}")
        return available_agents
    except Exception as e:
        logger.error(f"Error getting available agents: {str(e)}")
        return available_agents
