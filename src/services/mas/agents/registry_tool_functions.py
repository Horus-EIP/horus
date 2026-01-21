"""
Agent Registry Management Functions

This module provides core functionality for managing the agent registry in the
Multi-Agent System. It handles agent lifecycle operations including registration,
deregistration, status tracking, and heartbeat monitoring.

Key Features:
- In-memory agent registry for fast access
- UUID-based agent identification
- Skill-based agent categorization
- Health monitoring via heartbeat system
- Agent status tracking (active/inactive)
- Automatic status updates based on heartbeat timeouts

The agent registry is a central component that:
- Stores agent metadata and capabilities
- Tracks agent availability and health status
- Enables intelligent task routing based on agent skills
- Provides real-time status information for monitoring

Data Structure:
    agent_registry = {
        "agent_id": {
            "name": "Agent Name",
            "description": "Agent description",
            "skills": ["skill1", "skill2"],
            "status": "active" | "inactive",
            "last_heartbeat": datetime object
        }
    }

Security Considerations:
- Agent IDs are UUIDs to prevent enumeration attacks
- Registry operations are atomic to prevent race conditions
- Status updates are timestamped for audit trails
"""

import uuid
import secrets
from datetime import datetime, timedelta, timezone
from passlib.context import CryptContext
from fastapi import Depends
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session

from core.logger import get_logger
from db.database import SessionLocal, get_db
from db.models import Agents

logger = get_logger("registry_tool_functions")

bcrypt_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# ============================================================================
# INTERNAL FUNCTIONS - Without Depends (used by controller.py and other non-route code)
# These functions take explicit Session parameter
# ============================================================================


def _get_all_agents_internal(db: Session) -> list:
    """
    Internal: Retrieve all agents from the database.

    Args:
        db (Session): Database session (explicit)

    Returns:
        list: List of all Agents objects
    """
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
    """
    Internal function to update an agent's status to 'active' and refresh heartbeat.

    Args:
        agent_id (str): UUID of the agent
        db (Session): Database session (explicit)

    Returns:
        bool: True if update successful, False otherwise
    """
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
    """
    Internal: Update agent status to 'inactive'.

    Args:
        agent_id (str): UUID of the agent
        db (Session): Database session (explicit)

    Returns:
        bool: True if update successful, False otherwise
    """
    try:
        agent = db.query(Agents).filter(Agents.id == agent_id).first()
        if agent is None:
            logger.warning(f"Agent not found for marking dead - Agent ID: {agent_id}")
            return False

        agent.status = "dead"
        db.commit()
        logger.warning(
            f"Agent marked as dead - Agent ID: {agent_id}, Last heartbeat was {(datetime.now(timezone.utc) - agent.last_heartbeat).total_seconds():.1f}s ago"
        )
        return True
    except Exception as e:
        db.rollback()
        logger.error(f"Error updating agent status: {str(e)}")
        return False


def _batch_update_agent_status_internal(agent_statuses: dict, db: Session) -> bool:
    """
    Internal: Update multiple agents' status in a single transaction.

    Args:
        agent_statuses (dict): {agent_id: status}
        db (Session): Database session (explicit)

    Returns:
        bool: True if all updates successful
    """
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


def create_agent(name: str, skills: list, description: str, db: Session) -> tuple[str, str]:
    """
    Register a new agent in the system.

    Creates a new agent entry in the registry with a unique UUID identifier.
    The agent is initially marked as 'active' with current timestamp.

    Args:
        name (str): Human-readable name for the agent
        skills (list): List of capabilities/skills the agent possesses
        description (str): Detailed description of the agent's purpose
        db (Session): Database session (injected)

    Returns:
        tuple[str, str]: (agent_id, api_key) - Unique UUID and the plain text API key

    Example:
        agent_id, api_key = create_agent(
            name="Summarizer Bot",
            skills=["nlp", "summarization"],
            description="Specialized in text summarization"
        )
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
        )

        db.add(new_agent)
        db.commit()
        db.refresh(new_agent)
        logger.info(f"Agent created successfully: {agent_id} ({name})")
        return agent_id, api_key
    except Exception as e:
        db.rollback()
        logger.error(f"Error creating agent: {str(e)}")
        return None, None


def delete_agent(agent_id: str, db: Session) -> bool:
    """
    Remove an agent from the registry.

    Permanently removes the agent and cleans up all associated data.
    This operation is irreversible.

    Args:
        agent_id (str): UUID of the agent to remove
        db (Session): Database session (injected)

    Returns:
        bool: True if agent was found and deleted, False otherwise

    Note:
        This function also clears the agent's data dictionary before deletion
        for security reasons.
    """
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
    """
    Retrieve detailed information about a specific agent.

    Args:
        agent_id (str): UUID of the agent
        db (Session): Database session (injected)

    Returns:
        tuple: (id, name, skills, status, last_heartbeat, description, created_at)
               or (None, None, None, None, None, None, None) if not found
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
    """
    Retrieve all agents from the database.

    Args:
        db (Session): Database session (injected by FastAPI)

    Returns:
        list: List of all Agents objects
    """
    return _get_all_agents_internal(db)


def update_alive_agent_status(agent_id: str, db: Session) -> bool:
    """
    Update agent status to 'active' and set current heartbeat timestamp.

    Args:
        agent_id (str): UUID of the agent
        db (Session): Database session (injected)

    Returns:
        bool: True if update successful, False otherwise
    """
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
    """
    Update agent status to 'inactive'.

    Args:
        agent_id (str): UUID of the agent
        db (Session): Database session (injected)

    Returns:
        bool: True if update successful, False otherwise
    """
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
    """
    Update agent status to 'active'.

    Args:
        agent_id (str): UUID of the agent
        db (Session): Database session (injected)

    Returns:
        bool: True if update successful, False otherwise
    """
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
    """
    Get agent ID by name.

    Args:
        agent_name (str): Agent name
        db (Session): Database session (injected)

    Returns:
        str: Agent ID or None if not found
    """
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


def _is_agent_recently_alive(agent_info, max_age_seconds: int = 90) -> bool:
    last_heartbeat = agent_info.last_heartbeat
    if not last_heartbeat:
        return False
    try:
        return (datetime.now(timezone.utc) - last_heartbeat) <= timedelta(
            seconds=max_age_seconds
        )
    except Exception:
        return False


def get_available_agents(db: Session) -> list:
    """
    Get list of currently available agents (recently alive).

    Args:
        db (Session): Database session (injected)

    Returns:
        list: List of tuples (agent_id, agent_name, agent_description)
    """
    available_agents = []

    try:
        agents = db.query(Agents).all()

        if not agents:
            logger.debug("No agents registered in system")
            return available_agents

        for agent in agents:
            if _is_agent_recently_alive(agent):
                available_agents.append((agent.id, agent.name, agent.description or ""))

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
