import asyncio
import datetime

from agents.registry_tool_functions import get_all_agents


async def check_agent_heartbeat(test_mode=False):
    while True:

        current_time = datetime.datetime.now()
        inactivity_period = 30
        for agent_id, info in get_all_agents().items():

            if (
                (current_time - info["last_heartbeat"]).total_seconds()
            ) <= inactivity_period:
                info["status"] = "active"
            else:
                info["status"] = "inactive"

        if test_mode:
            break

        await asyncio.sleep(2)
