from datetime import datetime, timedelta

from agents.registry_tool_functions import get_all_agents
from core.rabbitmq_tool import channel


def compute_best_agent_for_task(agent):
    agent_id, info = agent
    # Ensure the queue exists and is durable before checking depth
    channel.queue_declare(queue=agent_id, passive=False, durable=True, exclusive=False, auto_delete=False)
    queue = channel.queue_declare(queue=agent_id, passive=True)
    return queue.method.message_count


def _is_agent_recently_alive(agent_info: dict, max_age_seconds: int = 90) -> bool:
    """Return True if agent heartbeat is recent within max_age_seconds."""
    last_heartbeat = agent_info.get("last_heartbeat")
    if not last_heartbeat:
        return False
    try:
        return (datetime.now() - last_heartbeat) <= timedelta(seconds=max_age_seconds)
    except Exception:
        return False


def select_agent_for_task(required_skill: list) -> str:
    suitable_agents = []

    for agent_id, agent_info in get_all_agents().items():
        if (
            all(skill in agent_info.get("skills", []) for skill in required_skill)
            and _is_agent_recently_alive(agent_info)
        ):
            suitable_agents.append((agent_id, agent_info))

    if not suitable_agents:
        print(f"⚠️ No available agent for skill {required_skill}")
        return ""

    best_agent = sorted(suitable_agents, key=compute_best_agent_for_task)[0][0]
    print(f"🎯 Agent {best_agent} selected for the task requiring {required_skill}")
    # Ensure queue exists and is durable to avoid transient queue deprecation
    channel.queue_declare(queue=best_agent, passive=False, durable=True, exclusive=False, auto_delete=False)
    return best_agent
