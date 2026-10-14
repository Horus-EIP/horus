import asyncio
import datetime
import os

from agents.registry_tool_functions import (
    _batch_update_agent_status_internal, _get_all_agents_internal)
from core.logger import get_logger, log_agent_operation
from db.database import SessionLocal

logger = get_logger("agent_controller")

# An agent is marked inactive after this many seconds without a heartbeat. It
# MUST be a multiple of the agent's heartbeat interval (30s) — when it equals
# the interval, normal jitter trips it every cycle and agents flap
# active<->inactive. 90s (3x) matches the liveness window already used by
# _is_agent_recently_alive in the registry.
_INACTIVITY_PERIOD_SECONDS = int(os.getenv("AGENT_INACTIVITY_TIMEOUT", "90"))


def get_all_agents():
    """Wrapper for tests - get all agents from database."""
    db = SessionLocal()
    try:
        agents = _get_all_agents_internal(db)
        # Convert to dict for test compatibility
        result = {}
        for agent in agents:
            result[agent.id] = {
                "name": agent.name,
                "skills": agent.skills,
                "status": agent.status,
                "last_heartbeat": agent.last_heartbeat,
                "description": agent.description,
            }
        return result
    finally:
        db.close()


async def check_agent_heartbeat(test_mode=False):
    """Monitor agent heartbeats and update their status"""
    logger.info("Starting agent heartbeat monitoring...")

    while True:
        try:
            db = SessionLocal()
            try:
                current_time = datetime.datetime.now(datetime.UTC)
                inactivity_period = _INACTIVITY_PERIOD_SECONDS
                agents = _get_all_agents_internal(db)

                if not agents:
                    logger.debug("No agents registered for heartbeat monitoring")
                    await asyncio.sleep(2)
                    continue

                status_updates = {}

                for agent in agents:
                    if agent.last_heartbeat is None:
                        time_since_last_heartbeat = float("inf")
                    else:
                        time_since_last_heartbeat = (
                            current_time - agent.last_heartbeat
                        ).total_seconds()

                    is_active = time_since_last_heartbeat <= inactivity_period
                    expected_status = "active" if is_active else "inactive"

                    if agent.status != expected_status:
                        status_updates[agent.id] = expected_status

                        if is_active:
                            log_agent_operation(
                                agent.id, "HEARTBEAT", "Agent became active"
                            )
                        else:
                            log_agent_operation(
                                agent.id,
                                "HEARTBEAT",
                                f"Agent inactive for {time_since_last_heartbeat:.1f}s",
                            )

                if status_updates:
                    _batch_update_agent_status_internal(status_updates, db)

                if test_mode:
                    logger.info("Test mode: breaking heartbeat monitoring loop")
                    break

                await asyncio.sleep(2)
            finally:
                db.close()

        except Exception as e:
            logger.error(f"Error in heartbeat monitoring: {str(e)}", exc_info=True)
            await asyncio.sleep(5)
