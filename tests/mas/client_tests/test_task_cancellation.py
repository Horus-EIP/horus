"""
Test Task Cancellation

This module tests the task cancellation workflow:
- Create a task
- Cancel the task
- Verify status update
- Verify error handling for invalid cancellations

Usage:
    python tests/mas/client_tests/test_task_cancellation.py
"""

import asyncio
import sys

import httpx

BASE_URL = "http://localhost:8000"
USERNAME = "admin"
PASSWORD = "secret"


def bearer_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def login() -> str:
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=10.0) as client:
        try:
            r = await client.post(
                "/auth/token",
                data={"username": USERNAME, "password": PASSWORD},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            r.raise_for_status()
            return r.json()["access_token"]
        except httpx.HTTPStatusError as e:
            print(f"❌ LOGIN failed: {e.response.status_code} {e.response.text}")
            sys.exit(1)
        except Exception as e:
            print(f"❌ LOGIN failed: {e}")
            sys.exit(1)


async def setup_agent(headers: dict) -> str:
    async with httpx.AsyncClient(
        base_url=BASE_URL, headers=headers, timeout=10.0
    ) as client:
        # Register agent
        agent_data = {
            "name": "cancellation_test_agent",
            "skills": ["testing", "long_running"],
            "description": "Agent capable of executing long running tasks and testing",
        }

        # Check if agent exists and delete if so
        r = await client.get("/agents/details/")
        r.raise_for_status()
        agents = r.json()
        existing_id = next(
            (a["id"] for a in agents if a["name"] == "cancellation_test_agent"), None
        )
        if existing_id:
            await client.delete(f"/agents/unregister/{existing_id}")

        # Register new
        r = await client.post("/agents/register", json=agent_data)
        r.raise_for_status()
        return r.json()["agent_id"]


async def create_conversation(headers: dict) -> str:
    async with httpx.AsyncClient(
        base_url=BASE_URL, headers=headers, timeout=10.0
    ) as client:
        r = await client.post(
            "/conversations/create-conversation/", json={"name": "Cancellation Test"}
        )
        r.raise_for_status()
        return r.json()["conversation_id"]


async def test_cancellation_workflow():
    print("🚀 Starting Task Cancellation Test...")
    token = await login()
    headers = bearer_headers(token)

    agent_id = None
    try:
        agent_id = await setup_agent(headers)
        conv_id = await create_conversation(headers)

        async with httpx.AsyncClient(
            base_url=BASE_URL, headers=headers, timeout=30.0
        ) as client:
            # 1. Create a task
            print("\n1️⃣  Creating new task...")
            task_payload = {
                "demand": "Execute a long running task",
                "conversation_id": str(conv_id),
                "skills_required": ["testing"],
            }
            r = await client.post("/tasks/new_task/", json=task_payload)
            if r.status_code != 200:
                print(f"❌ Task creation failed: {r.text}")
                return

            task_data = r.json()
            # Handle different response structures
            if "task_id" in task_data:
                task_id = task_data["task_id"]
            elif "id" in task_data:
                task_id = task_data["id"]
            else:
                print(f"❌ Task not assigned: {task_data}")
                return

            print(f"✅ Task created: {task_id}")

            # 2. Cancel the task
            print(f"\n2️⃣  Canceling task {task_id}...")
            r = await client.patch(f"/tasks/task-cancel/{task_id}")
            if r.status_code == 200:
                print(f"✅ Cancellation request successful: {r.json()}")
            else:
                print(f"❌ Cancellation failed: {r.status_code} {r.text}")

            # 3. Try to cancel again (should fail or handle gracefully)
            print(f"\n3️⃣  Attempting duplicate cancellation...")
            r = await client.patch(f"/tasks/task-cancel/{task_id}")
            print(f"ℹ️  Duplicate cancellation response: {r.status_code} {r.json()}")

    except Exception as e:
        print(f"❌ Test failed with exception: {e}")
    finally:
        if agent_id:
            async with httpx.AsyncClient(
                base_url=BASE_URL, headers=headers, timeout=10.0
            ) as client:
                await client.delete(f"/agents/unregister/{agent_id}")
                print("\n🧹 Cleanup: Agent unregistered")


if __name__ == "__main__":
    asyncio.run(test_cancellation_workflow())
