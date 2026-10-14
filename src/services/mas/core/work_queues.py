"""
Shared RabbitMQ work queues for pooled agent workers.

Tasks are published to ``{prefix}.{agent_type}`` (e.g. ``horus.work.general``) so
multiple containerized workers of the same specialization compete fairly. Registry
rows still identify each instance for heartbeats, API keys, and orchestration;
``Task.agent_id`` remains the orchestrator-chosen assignee.
"""

from sqlalchemy.orm import Session

from core.config import settings
from db.models import Agents


def work_queue_name_for_agent_type(agent_type) -> str:
    """Return the durable queue name used for all workers of this agent type."""
    prefix = getattr(settings, "agent_work_queue_prefix", None) or "horus.work"
    if hasattr(agent_type, "value"):
        agent_type = agent_type.value
    t = str(agent_type).lower()
    if "." in t:
        t = t.split(".")[-1]
    return f"{prefix}.{t}"


def resolve_work_queue_for_agent_id(db: Session, agent_id: str) -> str | None:
    """Look up an agent's type and return its shared work queue name."""
    agent = db.query(Agents).filter(Agents.id == agent_id).first()
    if agent is None:
        return None
    return work_queue_name_for_agent_type(agent.type)


def agent_may_submit_task_result(
    executor_agent_id: str, assigned_agent_id: str, db: Session
) -> bool:
    """
    True if ``executor_agent_id`` may POST /tasks/task-result/ for a task assigned
    to ``assigned_agent_id``: same id, or same AgentTypes pool (specialization).
    """
    if executor_agent_id == assigned_agent_id:
        return True
    ex = db.query(Agents).filter(Agents.id == executor_agent_id).first()
    asg = db.query(Agents).filter(Agents.id == assigned_agent_id).first()
    if not ex or not asg:
        return False
    t1 = ex.type.value if hasattr(ex.type, "value") else ex.type
    t2 = asg.type.value if hasattr(asg.type, "value") else asg.type
    return str(t1).lower() == str(t2).lower()
