"""
Sprint 2 Execution Test - Collaborative Agents
Tests the multi-agent collaboration flow (Decomposition -> Execution -> Handoff -> Aggregation).

Usage:
    python tests/mas/client_tests/client_test_sprint2.py
"""

import asyncio
import json
import time
from typing import Dict, List, Optional

import httpx

BASE_URL = "http://localhost:8000"
LOGIN_PATH = "/auth/token"
USERNAME = "admin"
PASSWORD = "secret"
TIMEOUT = 300.0


# Colors for output
class Colors:
    HEADER = "\033[95m"
    OKBLUE = "\033[94m"
    OKGREEN = "\033[92m"
    WARNING = "\033[93m"
    FAIL = "\033[91m"
    ENDC = "\033[0m"
    BOLD = "\033[1m"


def log(msg, color=Colors.OKBLUE):
    print(f"{color}{msg}{Colors.ENDC}")


async def login() -> str:
    log("🔑 Authenticating...", Colors.HEADER)
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=TIMEOUT) as client:
        resp = await client.post(
            LOGIN_PATH,
            data={"username": USERNAME, "password": PASSWORD},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if resp.status_code != 200:
            log(f"Login failed: {resp.text}", Colors.FAIL)
            raise Exception("Login failed")
        token = resp.json().get("access_token")
        log("✅ Authenticated", Colors.OKGREEN)
        return token


async def register_agent(
    client: httpx.AsyncClient, name: str, skills: list[str], type: str
) -> dict:
    log(f"🤖 Registering specialized agent {name} ({type})...", Colors.HEADER)

    # Check if exists
    try:
        resp = await client.get("/agents/details/")
        if resp.status_code == 200:
            agents = resp.json()
            for a in agents:
                if a["name"] == name:
                    log(f"ℹ️  Agent {name} exists, deleting...", Colors.WARNING)
                    await client.delete(f"/agents/unregister/{a['id']}")
    except Exception:
        pass

    payload = {
        "name": name,
        "skills": skills,
        "description": f"Specialized {type} agent",
        "type": type,
    }
    resp = await client.post("/agents/register", json=payload)
    if resp.status_code != 200:
        log(f"Registration failed: {resp.text}", Colors.FAIL)
        raise Exception(f"Agent {name} registration failed")

    data = resp.json()
    log(f"✅ Registered {name} (ID: {data['agent_id']})", Colors.OKGREEN)

    auth_header = {
        "X-API-Key": f"{data['agent_id']}:{data['api_key']}",
        "Agent-ID": data["agent_id"],
    }

    return {
        "id": data["agent_id"],
        "key": data["api_key"],
        "auth_header": auth_header,
        "name": name,
        "type": type,
    }


async def run_scenario():
    token = await login()
    headers = {"Authorization": f"Bearer {token}"}

    async with httpx.AsyncClient(
        base_url=BASE_URL, headers=headers, timeout=TIMEOUT
    ) as client:
        # 1. Register specialized agents
        researcher = await register_agent(
            client, "Sprint2Researcher", ["research"], "researcher"
        )
        analyst = await register_agent(
            client, "Sprint2Analyst", ["analysis"], "analyst"
        )
        writer = await register_agent(client, "Sprint2Writer", ["writing"], "writer")

        agents_map = {"researcher": researcher, "analyst": analyst, "writer": writer}

        # 1.5 Create Conversation
        log("Creating conversation...", Colors.HEADER)
        resp = await client.post(
            "/conversations/create-conversation/", json={"name": "Sprint 2 Demo"}
        )
        if resp.status_code != 200:
            log(f"Failed to create conversation: {resp.text}", Colors.FAIL)
            return
        conv_data = resp.json()
        conv_id = conv_data["conversation_id"]
        log(f"✅ Conversation Created: {conv_id}", Colors.OKGREEN)

        # 2. Start Collaborative Task
        prompt = "Fais une recherche sur l'informatique quantique, analyse les impacts économiques, et écris un article de synthèse."

        log(f"\n🚀 Creating Collaborative Task: '{prompt}'", Colors.HEADER)

        resp = await client.post(
            "/tasks/new_task/",
            json={
                "demand": prompt,
                "conversation_id": conv_id,
                "skills_required": ["collaboration"],
            },
            timeout=TIMEOUT,
        )
        if resp.status_code != 200:
            log(f"Task creation failed: {resp.text}", Colors.FAIL)
            return

        data = resp.json()
        initial_task_id = data.get("task_id")
        log(f"✅ Initial Task Created: {initial_task_id}", Colors.OKGREEN)

        # 3. Dynamic Execution Loop
        log("\n--- Entering Dynamic Execution Loop (Max 300s) ---", Colors.HEADER)

        start_time = time.time()
        processed_tasks = set()
        tasks_found_count = 0

        while time.time() - start_time < 300:
            resp = await client.get("/tasks/list")

            if resp.status_code != 200:
                log(
                    f"Failed to list tasks: {resp.status_code} {resp.text}", Colors.FAIL
                )
                await asyncio.sleep(2)
                continue

            all_tasks = resp.json()
            if not isinstance(all_tasks, list):
                log(
                    f"Unexpected response format: {type(all_tasks)} - {all_tasks}",
                    Colors.FAIL,
                )
                await asyncio.sleep(2)
                continue

            # Filter for our conversation and tasks not yet processed
            relevant_tasks = [
                t
                for t in all_tasks
                if str(t.get("conversation_id")) == str(conv_id)
                and t["id"] not in processed_tasks
                and t["status"] != "COMPLETED"
                and t["status"] != "CANCELED"
            ]

            if not relevant_tasks:
                print(".", end="", flush=True)
                await asyncio.sleep(2)
                continue

            print()  # Newline after dots

            for t in relevant_tasks:
                t_id = t["id"]
                a_id = t["agent_id"]

                # Identify which agent owns this task
                assigned_agent_type = None
                assigned_agent_info = None

                for type_name, info in agents_map.items():
                    if info["id"] == a_id:
                        assigned_agent_type = type_name
                        assigned_agent_info = info
                        break

                if assigned_agent_info:
                    log(
                        f"\n⚡ Task {t_id} assigned to {assigned_agent_info['name']} ({assigned_agent_type})",
                        Colors.BOLD,
                    )
                    log(f"   Instruction: {t.get('query', 'No query')}", Colors.OKBLUE)

                    # Simulate processing time
                    await asyncio.sleep(1)

                    result_text = f"Analyzed/Researched/Written result for task {t_id} by {assigned_agent_type}"

                    payload = {
                        "task_id": t_id,
                        "result": result_text,
                        "conversation_id": str(conv_id),
                        "agent_id": a_id,
                    }

                    # Submit result
                    async with httpx.AsyncClient(
                        base_url=BASE_URL, timeout=TIMEOUT
                    ) as agent_client:
                        resp = await agent_client.post(
                            "/tasks/task-result/",
                            json=payload,
                            headers=assigned_agent_info["auth_header"],
                        )

                    if resp.status_code == 200:
                        log(f"✅ Result submitted for {t_id}", Colors.OKGREEN)
                        processed_tasks.add(t_id)
                        tasks_found_count += 1

                        log(f"   Server response: {resp.json()}", Colors.WARNING)
                    else:
                        log(f"❌ Failed to submit result: {resp.text}", Colors.FAIL)

                else:
                    # Task assigned to an agent we don't control (or maybe the orchestrator itself if that's a thing)
                    # For Sprint 2 execute, we generally control all agents.
                    pass

            # If we have processed enough tasks, maybe we can stop?
            if tasks_found_count >= 3:
                log(
                    f"\n✅ Processed {tasks_found_count} tasks. Assuming workflow complete.",
                    Colors.OKGREEN,
                )
                break

        if tasks_found_count == 0:
            log("\n❌ No tasks processed in time window.", Colors.FAIL)

        # 4. Verify Final Aggregation

        log("\n🏁 Checking Final Result...", Colors.HEADER)
        await asyncio.sleep(2)
        resp = await client.get(f"/conversations/get_history/{conv_id}")
        if resp.status_code == 200:
            history = resp.json()
            last_msg = history[-1]
            log(f"Final Message Role: {last_msg['role']}", Colors.OKBLUE)
            log(f"Final Message Content: {last_msg['content']}", Colors.OKGREEN)

            if (
                "Success!" in last_msg["content"]
                or "Article de synthèse" in last_msg["content"]
            ):
                log("\n🎉 SPRINT 2 SCENARIO COMPLETED SUCCESSFULLY! 🎉", Colors.BOLD)
            else:
                log(
                    "\n⚠️ Scenario finished but final content check failed.",
                    Colors.WARNING,
                )


if __name__ == "__main__":
    asyncio.run(run_scenario())
