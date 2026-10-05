"""Agent registry CRUD and heartbeat helpers.

Functions prefixed with ``_`` take an explicit ``Session`` and are safe to
call from background tasks. Public variants are used by FastAPI routes.
"""

import secrets
import uuid
from datetime import UTC, datetime, timedelta

from passlib.context import CryptContext
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session

from core.logger import get_logger
from core.rabbitmq_tool import rabbitmq_instance
from core.work_queues import work_queue_name_for_agent_type
from db.models import Agents, AgentTypes


def _skill_cache_upsert(agent_id: str, name: str, skills: list, description: str) -> None:
    """Best-effort skill-cache update; never let it crash the registry path."""
    try:
        from core.skill_cache import upsert_agent

        upsert_agent(agent_id, name, list(skills or []), description or "")
    except Exception:
        logger.exception("Skill cache upsert failed for agent %s", agent_id)


def _skill_cache_evict(agent_id: str) -> None:
    try:
        from core.skill_cache import evict_agent

        evict_agent(agent_id)
    except Exception:
        logger.exception("Skill cache evict failed for agent %s", agent_id)

logger = get_logger("registry_tool_functions")

bcrypt_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

MANAGER_AGENT_NAME = "Manager"


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
        agent.last_heartbeat = datetime.now(UTC)
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
            last_heartbeat = last_heartbeat.replace(tzinfo=UTC)

        logger.warning(
            f"Agent marked as dead - Agent ID: {agent_id}, Last heartbeat was {(datetime.now(UTC) - last_heartbeat).total_seconds():.1f}s ago"
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
            last_heartbeat=datetime.now(UTC),
            api_key=hash_api_key,
            type=Agent_type,
        )

        db.add(new_agent)
        db.commit()
        db.refresh(new_agent)
        logger.info(f"Agent created successfully: {agent_id} ({name})")

        # Shared pool queue for this specialization (all workers of this type consume it).
        rabbitmq_instance.create_queue(work_queue_name_for_agent_type(Agent_type))

        _skill_cache_upsert(agent_id, name, skills, description)
        return agent_id, api_key
    except Exception as e:
        db.rollback()
        logger.error(f"Error creating agent: {str(e)}")
        return None, None


def regenerate_agent_api_key(agent_id: str, db: Session) -> str | None:
    """Rotate an agent's API key and return the new plaintext (shown once).

    Stored keys are bcrypt-hashed and therefore unrecoverable, so a forgotten
    key cannot be displayed again — it can only be replaced. This generates a
    fresh token, hashes it for storage, and returns the plaintext so the caller
    can surface it a single time. The previous key stops working immediately.

    Returns ``None`` if the agent does not exist or the update fails (on
    failure the old key is left untouched by the rollback).
    """
    try:
        agent = db.query(Agents).filter(Agents.id == agent_id).first()
        if agent is None:
            logger.warning(f"Cannot regenerate API key - agent not found: {agent_id}")
            return None

        api_key = secrets.token_urlsafe(32)
        agent.api_key = bcrypt_context.hash(api_key)
        db.commit()
        # Drop any cached verifications of the OLD key so it stops working
        # immediately (otherwise the positive-cache TTL would keep honouring it).
        try:
            from auth.auth_tool_functions import invalidate_agent_api_key_cache

            invalidate_agent_api_key_cache(agent_id)
        except Exception:  # noqa: BLE001 - invalidation is best-effort
            logger.debug("Auth cache invalidation skipped for %s", agent_id)
        logger.info(f"API key regenerated successfully - Agent ID: {agent_id}")
        return api_key
    except Exception as e:
        db.rollback()
        logger.error(
            f"Error regenerating API key - Agent ID: {agent_id}, Error: {str(e)}"
        )
        return None


def delete_agent(agent_id: str, db: Session) -> bool:
    """Permanently delete an agent. Returns ``False`` if not found."""
    try:
        agent = db.get(Agents, agent_id)
        if agent is None:
            return False
        db.delete(agent)
        db.commit()
        _skill_cache_evict(agent_id)
        try:
            from auth.auth_tool_functions import invalidate_agent_api_key_cache

            invalidate_agent_api_key_cache(agent_id)
        except Exception:  # noqa: BLE001 - invalidation is best-effort
            logger.debug("Auth cache invalidation skipped for %s", agent_id)
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
        agent.last_heartbeat = datetime.now(UTC)
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
        agent.last_heartbeat = datetime.now(UTC)
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

        # Lenient resolution: the planner routes by SEMANTIC role ('compliance',
        # 'finance', 'hr', 'communication') but only 4 enum types exist
        # (researcher/analyst/writer/general). Without this, those plans fail
        # validation and fall back to the heuristic — which can't slice the work,
        # so one agent answers everything. Match the requested role against each
        # agent's NAME and SKILLS (plus a few synonyms) so a multi-step plan
        # routes to the right distinct specialists.
        _syn = {
            "finance": "analyst", "financial": "analyst", "budget": "analyst",
            "accounting": "analyst", "analysis": "analyst",
            "compliance": "compliance", "legal": "compliance", "policy": "compliance",
            "audit": "compliance", "risk": "compliance", "security": "compliance",
            "hr": "hr", "people": "hr", "human": "hr",
            "communication": "writer", "writer": "writer", "write": "writer",
            "draft": "writer", "messaging": "writer", "memo": "writer",
        }
        mapped = _syn.get(target)

        def _role_matches(a) -> bool:
            name = (a.name or "").lower()
            sk = a.skills or []
            skills = " ".join(sk).lower() if isinstance(sk, list) else str(sk).lower()
            hay = f"{name} {skills}"
            return target in hay or bool(mapped and mapped in hay)

        for a in agents:  # prefer active
            if _role_matches(a):
                return a.id
        for a in all_agents:
            if _role_matches(a):
                return a.id

        # Last resort: any active non-Manager agent, so one unmappable role in an
        # otherwise-good plan doesn't fail validation and collapse to the heuristic.
        for a in agents:
            if (a.name or "").lower() != "manager":
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
        current_time = datetime.now(UTC)
        if last_heartbeat.tzinfo is None:
            last_heartbeat = last_heartbeat.replace(tzinfo=UTC)
        return (current_time - last_heartbeat) <= timedelta(seconds=max_age_seconds)
    except Exception as e:
        logger.error(f"Error checking agent liveness: {e}")
        return False


def is_available_worker(agent_info) -> bool:
    return agent_info.name != MANAGER_AGENT_NAME and _is_agent_recently_alive(agent_info)


def get_available_agents(db: Session) -> list:
    """Return agents with a recent heartbeat as ``(id, name, desc, type)`` tuples.

    The Manager agent is intentionally excluded — it orchestrates work but
    never executes it itself, so neither the LLM router nor the planner
    should see it as an option for SINGLE_AGENT routing or for subtask
    assignment. The Manager's presence in those prompts caused the planner
    to occasionally assign subtasks to "manager", which then has no worker
    consumer on its queue and stalls the chain.
    """
    available_agents = []

    try:
        agents = db.query(Agents).all()

        if not agents:
            logger.debug("No agents registered in system")
            return available_agents

        for agent in agents:
            if is_available_worker(agent):
                available_agents.append(
                    (agent.id, agent.name, agent.description or "", agent.type)
                )

        logger.info(
            f"Agent availability check - Available: {len(available_agents)}/{len(agents)} (Manager excluded)"
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
