import datetime
import uuid

agent_registry: dict[str, dict] = {}


def create_agent(name: str, skills: list):
    agent_id = str(uuid.uuid4())
    agent_registry[agent_id] = {
        "name": name,
        "skills": skills,
        "status": "active",
        "last_heartbeat": datetime.datetime.now(),
    }
    return agent_id


def delete_agent(agent_id: str):
    global agent_registry
    if agent_id in agent_registry:
        agent_info = agent_registry[agent_id]
        agent_info.clear()
        del agent_registry[agent_id]
        return True
    else:
        return False


def get_agent_details(agent_id: str):
    if agent_id in agent_registry:
        agent_info = agent_registry[agent_id]
        agent_name = agent_info.get("name")
        agent_skills = agent_info.get("skills")
        agent_status = agent_info.get("status")
        agent_heartbeat = agent_info.get("last_heartbeat")
        return agent_id, agent_name, agent_skills, agent_status, agent_heartbeat
    else:
        return None, None, None, None, None


def get_all_agents():
    return agent_registry


def update_alive_agent_status(agent_id: str):
    global agent_registry
    if agent_id in agent_registry:
        agent_info = agent_registry[agent_id]
        agent_info.update(
            {"last_heartbeat": datetime.datetime.now(), "status": "active"}
        )
        return True
    else:
        return False
