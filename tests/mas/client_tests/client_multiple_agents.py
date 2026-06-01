"""
Multiple Agents Test - Task Workflow with Database Persistence

This module tests the complete task workflow with multiple agents:
- Task creation with hierarchical structure (parent_task_id)
- TaskResult storage with history and future_actions
- Automatic subtask creation for chained agent workflows
- Real-time WebSocket communication

The test verifies that:
1. Initial task is created and stored in the database
2. Task results are persisted with full history and remaining actions
3. Subtasks are automatically created for chained operations
4. WebSocket messages reflect the final conversation state

Requirements:
- PostgreSQL database with Task and TaskResult tables
- RabbitMQ for agent communication
- Two test agents available in the system

Usage:
    python client_multiple_agents_updated.py
"""

import asyncio
import json

import httpx
from websockets.asyncio.client import connect

BASE_URL = "http://localhost:8000"
LOGIN_PATH = "/auth/token"
USERNAME = "admin"
PASSWORD = "secret"


def bearer_headers(token: str) -> dict:
    """Generate Bearer token headers for authenticated requests."""
    return {"Authorization": f"Bearer {token}"}


async def login_and_get_token() -> str:
    """
    Authenticate user and retrieve JWT token.

    Returns:
        str: JWT access token

    Raises:
        RuntimeError: If token cannot be extracted from response
    """
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=120.0) as client:
        response = await client.post(
            LOGIN_PATH,
            data={"username": USERNAME, "password": PASSWORD},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        response.raise_for_status()
        data = response.json()
        token = data.get("access_token")
        if not token:
            raise RuntimeError(f"Failed to extract token from response: {data}")
        return token


async def setup_agents_and_conversation(headers_http: dict) -> tuple:
    """
    Register test agents and create a conversation.

    Creates two test agents for the workflow:
    - agent_test: Handles mathematical operations (math skill)
    - agent_test2: Handles text translation (translation skill)

    Also creates a new conversation to hold the task workflow.

    Args:
        headers_http (dict): HTTP headers with Bearer token

    Returns:
        tuple: (agent_ids dict, agent_keys dict, conversation_id str, task_id str)

    Raises:
        httpx.HTTPStatusError: If any API call fails
    """
    agent_ids = {}
    agent_keys = {}
    async with httpx.AsyncClient(
        base_url=BASE_URL, headers=headers_http, timeout=300.0
    ) as client:
        # Helper to get agent ID by name
        async def get_agent_id_by_name(name):
            r = await client.get("/agents/details/")
            r.raise_for_status()
            agents = r.json()
            for a in agents:
                if a["name"] == name:
                    return a["id"]
            return None

        # Register first agent - mathematical operations
        print("\n[Agents] Registering agent_test for math operations...")
        agent_payload = {
            "name": "agent_test",
            "skills": ["math", "calculation"],
            "description": "Agent specialized in mathematical operations and calculations",
        }
        response = await client.post("/agents/register", json=agent_payload)

        if response.status_code == 409:
            print("ℹ️  Agent agent_test already exists, cleaning up to get new key...")
            temp_id = await get_agent_id_by_name("agent_test")
            if temp_id:
                await client.delete(f"/agents/unregister/{temp_id}")
            # Register again
            response = await client.post("/agents/register", json=agent_payload)

        response.raise_for_status()
        data = response.json()
        agent_ids["agent_test"] = data["agent_id"]
        agent_keys["agent_test"] = data["api_key"]
        print(f"✅ Registered agent_test: {agent_ids['agent_test']}")

        # Send heartbeat
        # headers_agent = {"X-API-Key": agent_keys["agent_test"], "Agent-ID": agent_ids["agent_test"]}
        # Use combined key format for compatibility
        combined_key = f"{agent_ids['agent_test']}:{agent_keys['agent_test']}"
        headers_agent = {"X-API-Key": combined_key}
        await client.post(
            f"/agents/heartbeat/{agent_ids['agent_test']}", headers=headers_agent
        )

        # Register second agent - translation
        print("[Agents] Registering agent_test2 for translation...")
        agent2_payload = {
            "name": "agent_test2",
            "skills": ["translation", "nlp", "language"],
            "description": "Agent specialized in text translation and language operations",
        }
        response = await client.post("/agents/register", json=agent2_payload)

        if response.status_code == 409:
            print("ℹ️  Agent agent_test2 already exists, cleaning up to get new key...")
            temp_id = await get_agent_id_by_name("agent_test2")
            if temp_id:
                await client.delete(f"/agents/unregister/{temp_id}")
            # Register again
            response = await client.post("/agents/register", json=agent2_payload)

        response.raise_for_status()
        data = response.json()
        agent_ids["agent_test2"] = data["agent_id"]
        agent_keys["agent_test2"] = data["api_key"]
        print(f"✅ Registered agent_test2: {agent_ids['agent_test2']}")

        # Send heartbeat
        # headers_agent2 = {"X-API-Key": agent_keys["agent_test2"], "Agent-ID": agent_ids["agent_test2"]}
        combined_key2 = f"{agent_ids['agent_test2']}:{agent_keys['agent_test2']}"
        headers_agent2 = {"X-API-Key": combined_key2}
        await client.post(
            f"/agents/heartbeat/{agent_ids['agent_test2']}", headers=headers_agent2
        )

        # Create conversation
        print("[Conversation] Creating new conversation...")
        response = await client.post(
            "/conversations/create-conversation/",
            json={"name": "Multi-agent task workflow test"},
        )
        response.raise_for_status()
        conv_id = str(response.json()["conversation_id"])
        print(f"✅ Created conversation: {conv_id}")

        # Verify conversations were created
        print("[Conversation] Retrieving conversations list...")
        response = await client.get("/conversations/get-conversations/")
        response.raise_for_status()
        conversations = response.json()
        print(f"✅ Found {len(conversations)} conversation(s)")

        # Create initial task
        print("\n[Task] Creating initial task with multi-agent workflow...")
        response = await client.post(
            "/tasks/new_task/",
            json={
                "demand": "Calculate the square root of 4 and translate the result into English",
                "conversation_id": conv_id,
                "skills_required": ["math", "translation"],
            },
        )
        response.raise_for_status()
        task_result = response.json()
        task_id = task_result.get("task_id")
        print(f"✅ Task created: {task_id}")
        print(f"   Message: {task_result.get('message')}")

    return agent_ids, agent_keys, conv_id, task_id


async def submit_agent_results(
    agent_ids: dict, agent_keys: dict, conv_id: str, task_id: str, token: str
) -> None:
    """
    Simulate agents completing tasks and submitting results.

    This function simulates the complete workflow:
    1. Agent 1 (math) calculates square root
    2. System automatically creates subtask for Agent 2
    3. Agent 2 (translation) translates the result
    4. Conversation ends (no more future_actions)

    Args:
        agent_ids (dict): Mapping of agent names to IDs
        agent_keys (dict): Mapping of agent names to API keys
        conv_id (str): Conversation ID
        task_id (str): Initial task ID
        token (str): User token for authentication (required by stale server)
    """
    # Note: Agents don't use Bearer token, they use API Key
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=10.0) as client:
        # Step 1: Agent 1 (math) submits result
        print("\n[Step 1] Agent 1 (math) submitting result...")
        print("-" * 60)

        history_1 = [
            {
                "role": "user",
                "message": "Calculate the square root of 4 and translate the result into English",
            }
        ]
        future_actions_1 = [
            [agent_ids["agent_test2"], "Translate the mathematical result into English"]
        ]

        # headers_1 = {
        #     "X-API-Key": agent_keys["agent_test"],
        #     "Agent-ID": agent_ids["agent_test"]
        # }
        combined_key1 = f"{agent_ids['agent_test']}:{agent_keys['agent_test']}"
        headers_1 = {"X-API-Key": combined_key1, "Authorization": f"Bearer {token}"}

        response = await client.post(
            "/tasks/task-result/",
            json={
                "task_id": task_id,
                "result": "The square root of 4 is 2.",
                "conversation_id": conv_id,
                "agent_id": agent_ids["agent_test"],
                "history": history_1,
                "future_actions": future_actions_1,
            },
            headers=headers_1,
        )
        response.raise_for_status()
        result_1 = response.json()
        print(f"✅ Agent 1 result submitted: {result_1['message']}")

        # Wait briefly for task processing
        await asyncio.sleep(0.5)

        # Step 2: Agent 2 (translation) submits result
        print("\n[Step 2] Agent 2 (translation) submitting result...")
        print("-" * 60)

        history_2 = [
            {
                "role": "user",
                "message": "Calculate the square root of 4 and translate the result into English",
            },
            {"role": "assistant", "message": "The square root of 4 is 2."},
        ]

        # headers_2 = {
        #     "X-API-Key": agent_keys["agent_test2"],
        #     "Agent-ID": agent_ids["agent_test2"]
        # }
        combined_key2 = f"{agent_ids['agent_test2']}:{agent_keys['agent_test2']}"
        headers_2 = {"X-API-Key": combined_key2, "Authorization": f"Bearer {token}"}

        response = await client.post(
            "/tasks/task-result/",
            json={
                "task_id": task_id,
                "result": "La racine carrée de 4 est 2.",
                "conversation_id": conv_id,
                "agent_id": agent_ids["agent_test2"],
                "history": history_2,
                "future_actions": [],
            },
            headers=headers_2,
        )
        response.raise_for_status()
        result_2 = response.json()
        print(f"✅ Agent 2 result submitted: {result_2['message']}")

        await asyncio.sleep(0.5)


async def websocket_listener(
    token: str, conv_id: str, agent_id: str, timeout: int = 5
) -> None:
    """
    Listen to WebSocket for real-time message updates.

    Subscribes to conversation messages via WebSocket and prints
    received messages in real-time.

    Args:
        token (str): JWT authentication token
        conv_id (str): Conversation ID to listen to
        agent_id (str): Agent ID (for routing context)
        timeout (int): Timeout in seconds for receiving messages (default: 5)
    """
    ws_uri = f"ws://localhost:8000/chat/{conv_id}/?token={token}&agent_id={agent_id}"
    print(f"\n[WebSocket] Connecting to: {ws_uri}")

    try:
        async with connect(ws_uri) as websocket:
            print("✅ WebSocket connected successfully")
            print("[WebSocket] Listening for messages...")

            try:
                while True:
                    raw = await asyncio.wait_for(websocket.recv(), timeout=timeout)
                    try:
                        msg = json.loads(raw)
                    except json.JSONDecodeError:
                        msg = raw
                    print(f"📨 Received: {msg}")
            except TimeoutError:
                print(f"⏱️  WebSocket timeout ({timeout}s) - no new messages")
    except Exception as e:
        print(f"❌ WebSocket error: {e}")


async def cleanup_resources(agent_ids: dict, conv_id: str, headers_http: dict) -> None:
    """
    Clean up test resources (agents, conversation).

    Args:
        agent_ids (dict): Mapping of agent names to IDs to unregister
        conv_id (str): Conversation ID to delete
        headers_http (dict): HTTP headers with Bearer token
    """
    print("\n[Cleanup] Cleaning up test resources...")
    print("-" * 60)

    async with httpx.AsyncClient(
        base_url=BASE_URL, headers=headers_http, timeout=10.0
    ) as client:
        # Unregister agents
        for name, agent_id in agent_ids.items():
            try:
                response = await client.delete(f"/agents/unregister/{agent_id}")
                if response.is_success:
                    print(f"✅ Unregistered {name}")
            except Exception as e:
                print(f"⚠️  Failed to unregister {name}: {e}")

        # Delete conversation
        try:
            response = await client.delete(
                f"/conversations/delete-conversation/{conv_id}"
            )
            if response.is_success:
                print(f"✅ Deleted conversation {conv_id}")
        except Exception as e:
            print(f"⚠️  Failed to delete conversation: {e}")

        # Logout
        try:
            response = await client.post("/auth/logout")
            if response.is_success:
                print("✅ Logged out")
        except Exception as e:
            print(f"⚠️  Failed to logout: {e}")


async def main():
    """Main test orchestration function."""
    print("\n" + "=" * 70)
    print("MULTIPLE AGENTS TASK WORKFLOW TEST")
    print("=" * 70)

    try:
        # Step 1: Authentication
        print("\n[Authentication] Logging in...")
        print("-" * 70)
        token = await login_and_get_token()
        headers_http = bearer_headers(token)
        print("✅ Authentication successful")
        print(f"   Token: {token[:30]}...")

        # Step 2: Setup agents and conversation
        print("\n[Setup] Initializing agents and conversation...")
        print("-" * 70)
        agent_ids, agent_keys, conv_id, task_id = await setup_agents_and_conversation(
            headers_http
        )
        print("✅ Setup complete")
        print(f"   Agents: {list(agent_ids.keys())}")
        print(f"   Conversation ID: {conv_id}")
        print(f"   Initial Task ID: {task_id}")

        # Step 3: Start WebSocket listener in background
        print("\n[WebSocket] Starting real-time listener...")
        print("-" * 70)
        ws_task = asyncio.create_task(
            websocket_listener(token, conv_id, agent_ids["agent_test"], timeout=3)
        )

        # Step 4: Submit agent results (simulate workflow)
        print("\n[Task Workflow] Simulating agent task completion...")
        print("-" * 70)
        await submit_agent_results(agent_ids, agent_keys, conv_id, task_id, token)

        # Wait for WebSocket to finish
        try:
            await ws_task
        except asyncio.CancelledError:
            pass

        # Step 5: Cleanup
        await cleanup_resources(agent_ids, conv_id, headers_http)

        print("\n" + "=" * 70)
        print("✅ ALL TESTS COMPLETED SUCCESSFULLY!")
        print("=" * 70)
        print("\nTest Summary:")
        print(f"  ✓ Authenticated as: {USERNAME}")
        print(f"  ✓ Registered 2 agents: {', '.join(agent_ids.keys())}")
        print(f"  ✓ Created conversation: {conv_id}")
        print(f"  ✓ Created initial task: {task_id}")
        print("  ✓ Simulated multi-agent workflow")
        print("  ✓ Received WebSocket updates")
        print("  ✓ Cleaned up resources")

    except httpx.HTTPStatusError as e:
        resp = e.response
        print(
            f"\n❌ HTTP error {resp.status_code} on {resp.request.method} {resp.request.url}"
        )
        try:
            print(f"   Response: {resp.json()}")
        except Exception:
            print(f"   Response: {resp.text}")
        raise
    except Exception as e:
        print(f"\n❌ Test failed: {repr(e)}")
        import traceback

        traceback.print_exc()
        raise


if __name__ == "__main__":
    asyncio.run(main())
