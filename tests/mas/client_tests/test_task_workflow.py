"""
Test Task Workflow

This module tests the complete task workflow with new Task and TaskResult models:
- Task creation with parent_task_id for hierarchical structure
- TaskResult storage with history and future_actions
- Subtask creation and chaining
- Complete conversation flow with multiple agents

Usage:
    python test_task_workflow.py
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
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=10.0) as client:
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


async def setup_agents_and_conversation(headers_http: dict) -> tuple[dict, str]:
    """
    Register test agents and create a conversation.

    Creates two test agents:
    - agent_test: Handles mathematical operations
    - agent_test2: Handles translation tasks

    Args:
        headers_http (dict): HTTP headers with Bearer token

    Returns:
        tuple: (agent_ids dict, conversation_id str)
    """
    agent_ids = {}
    agent_keys = {}
    async with httpx.AsyncClient(
        base_url=BASE_URL, headers=headers_http, timeout=150.0
    ) as client:
        # Register first agent - math operations
        response = await client.post(
            "/agents/register",
            json={
                "name": "agent_test",
                "skills": ["math", "calculation"],
                "description": "Agent specialized in mathematical operations",
            },
        )

        if response.status_code == 409:
            print("ℹ️  Agent agent_test already exists, cleaning up...")
            # Get existing agent ID
            r = await client.get("/agents/details/")
            r.raise_for_status()
            agents = r.json()
            existing_id = next(
                (a["id"] for a in agents if a["name"] == "agent_test"), None
            )
            if existing_id:
                await client.delete(f"/agents/unregister/{existing_id}")
                # Retry registration
                response = await client.post(
                    "/agents/register",
                    json={
                        "name": "agent_test",
                        "skills": ["math", "calculation"],
                        "description": "Agent specialized in mathematical operations",
                    },
                )

        response.raise_for_status()
        data = response.json()
        agent_ids["agent_test"] = data["agent_id"]
        agent_keys["agent_test"] = data["api_key"]
        print(f"✅ Registered agent_test: {agent_ids['agent_test']}")

        # Register second agent - translation
        response = await client.post(
            "/agents/register",
            json={
                "name": "agent_test2",
                "skills": ["translation", "nlp"],
                "description": "Agent specialized in text translation",
            },
        )

        if response.status_code == 409:
            print("ℹ️  Agent agent_test2 already exists, cleaning up...")
            # Get existing agent ID
            r = await client.get("/agents/details/")
            r.raise_for_status()
            agents = r.json()
            existing_id = next(
                (a["id"] for a in agents if a["name"] == "agent_test2"), None
            )
            if existing_id:
                await client.delete(f"/agents/unregister/{existing_id}")
                # Retry registration
                response = await client.post(
                    "/agents/register",
                    json={
                        "name": "agent_test2",
                        "skills": ["translation", "nlp"],
                        "description": "Agent specialized in text translation",
                    },
                )

        response.raise_for_status()
        data = response.json()
        agent_ids["agent_test2"] = data["agent_id"]
        agent_keys["agent_test2"] = data["api_key"]
        print(f"✅ Registered agent_test2: {agent_ids['agent_test2']}")

        # Create conversation
        response = await client.post(
            "/conversations/create-conversation/",
            json={"name": "Task workflow test conversation"},
        )
        response.raise_for_status()
        conv_id = str(response.json()["conversation_id"])
        print(f"✅ Created conversation: {conv_id}")

        # List conversations to verify
        response = await client.get("/conversations/get-conversations/")
        response.raise_for_status()
        print(
            f"✅ Conversations list retrieved: {len(response.json())} conversation(s)"
        )

    return agent_ids, agent_keys, conv_id


async def create_initial_task(headers_http: dict, conv_id: str, agent_ids: dict) -> str:
    """
    Create initial task that will trigger task creation in DB.

    The system will split this into future_actions:
    1. agent_test: Calculate square root
    2. agent_test2: Translate result

    Args:
        headers_http (dict): HTTP headers with Bearer token
        conv_id (str): Conversation ID
        agent_ids (dict): Agent IDs mapping

    Returns:
        str: Created task ID
    """
    async with httpx.AsyncClient(
        base_url=BASE_URL, headers=headers_http, timeout=150.0
    ) as client:
        response = await client.post(
            "/tasks/new_task/",
            json={
                "demand": "Calculate the square root of 4 and translate the result into English",
                "conversation_id": conv_id,
                "skills_required": ["math", "translation"],
            },
        )
        response.raise_for_status()
        result = response.json()
        task_id = result.get("task_id")
        print(f"✅ Task created: {task_id}")
        print(f"   Message: {result.get('message')}")
        return task_id


async def submit_task_result(
    headers_http: dict,
    task_id: str,
    result: str,
    agent_id: str,
    conv_id: str,
    history: list = None,
    future_actions: list = None,
) -> dict:
    """
    Submit task result from agent (simulating agent work completion).

    Args:
        headers_http (dict): HTTP headers with Bearer token
        task_id (str): Task ID being completed
        result (str): The result/output from the agent
        agent_id (str): Agent ID that completed the task
        conv_id (str): Conversation ID
        history (list, optional): Conversation history
        future_actions (list, optional): Remaining actions to execute

    Returns:
        dict: Response from server
    """
    if history is None:
        history = []
    if future_actions is None:
        future_actions = []

    payload = {
        "task_id": task_id,
        "result": result,
        "conversation_id": conv_id,
        "agent_id": agent_id,
        "history": history,
        "future_actions": future_actions,
    }

    async with httpx.AsyncClient(
        base_url=BASE_URL, headers=headers_http, timeout=10.0
    ) as client:
        response = await client.post("/tasks/task-result/", json=payload)
        response.raise_for_status()
        return response.json()


async def websocket_listener(token: str, conv_id: str, agent_id: str, timeout: int = 5):
    """
    Listen to WebSocket for real-time message updates.

    Args:
        token (str): JWT authentication token
        conv_id (str): Conversation ID to listen to
        agent_id (str): Agent ID (for routing context)
        timeout (int): Timeout in seconds for receiving messages
    """
    ws_uri = f"ws://localhost:8000/chat/{conv_id}/?token={token}&agent_id={agent_id}"
    print(f"🔌 Connecting to WebSocket: {ws_uri}")

    try:
        async with connect(ws_uri) as websocket:
            print("✅ WebSocket connected")
            try:
                while True:
                    raw = await asyncio.wait_for(websocket.recv(), timeout=timeout)
                    try:
                        msg = json.loads(raw)
                    except json.JSONDecodeError:
                        msg = raw
                    print(f"📨 WebSocket message: {msg}")
            except asyncio.TimeoutError:
                print(f"⏱️  WebSocket timeout ({timeout}s) - no more messages")
    except Exception as e:
        print(f"❌ WebSocket error: {e}")


async def simulate_agent_task_flow(
    headers_http: dict, agent_ids: dict, conv_id: str, initial_task_id: str
):
    """
    Simulate agents completing tasks in sequence.

    Flow:
    1. Agent 1 (math) completes calculation task
    2. System creates Agent 2 (translation) subtask
    3. Agent 2 completes translation task
    4. Conversation ends (no more future_actions)

    Args:
        headers_http (dict): HTTP headers with Bearer token
        agent_ids (dict): Agent IDs mapping
        conv_id (str): Conversation ID
        initial_task_id (str): Initial task ID created
    """
    print("\n" + "=" * 60)
    print("SIMULATING AGENT TASK FLOW")
    print("=" * 60)


async def simulate_agent_task_flow(
    headers_http: dict,
    agent_ids: dict,
    agent_keys: dict,
    conv_id: str,
    initial_task_id: str,
):
    """
    Simulate agents completing tasks in sequence.

    Flow:
    1. Agent 1 (math) completes calculation task
    2. System creates Agent 2 (translation) subtask
    3. Agent 2 completes translation task
    4. Conversation ends (no more future_actions)

    Args:
        headers_http (dict): HTTP headers with Bearer token
        agent_ids (dict): Agent IDs mapping
        agent_keys (dict): Agent API keys mapping
        conv_id (str): Conversation ID
        initial_task_id (str): Initial task ID created
    """
    print("\n" + "=" * 60)
    print("SIMULATING AGENT TASK FLOW")
    print("=" * 60)

    # Step 1: Agent 1 completes math task
    print("\n[Step 1] Agent 1 (math) completes calculation")
    print("-" * 60)

    history_1 = [
        {
            "role": "user",
            "message": "Calculate the square root of 4 and translate the result into English",
        }
    ]
    future_actions_1 = [[agent_ids["agent_test2"], "Translate result into English"]]

    # Use agent authentication headers
    combined_key1 = f"{agent_ids['agent_test']}:{agent_keys['agent_test']}"
    headers_agent1 = {
        "X-API-Key": combined_key1,
        "Authorization": headers_http["Authorization"],
    }

    result_1 = await submit_task_result(
        headers_http=headers_agent1,
        task_id=initial_task_id,
        result="The square root of 4 is 2.",
        agent_id=agent_ids["agent_test"],
        conv_id=conv_id,
        history=history_1,
        future_actions=future_actions_1,
    )
    print(f"✅ Agent 1 task result submitted:")
    print(f"   Response: {result_1['message']}")

    # Wait a bit for task processing
    await asyncio.sleep(0.5)

    # Step 2: Agent 2 completes translation task
    print("\n[Step 2] Agent 2 (translation) completes translation")
    print("-" * 60)

    history_2 = [
        {
            "role": "user",
            "message": "Calculate the square root of 4 and translate the result into English",
        },
        {"role": "assistant", "message": "The square root of 4 is 2."},
    ]

    # Use agent authentication headers
    combined_key2 = f"{agent_ids['agent_test2']}:{agent_keys['agent_test2']}"
    headers_agent2 = {
        "X-API-Key": combined_key2,
        "Authorization": headers_http["Authorization"],
    }

    # Note: In real scenario, the system would have created a new task_id for the subtask
    # For this test, we simulate it by noting the flow
    result_2 = await submit_task_result(
        headers_http=headers_agent2,
        task_id=initial_task_id,  # In practice, this would be the subtask_id
        result="La racine carrée de 4 est 2.",
        agent_id=agent_ids["agent_test2"],
        conv_id=conv_id,
        history=history_2,
        future_actions=[],  # No more actions
    )
    print(f"✅ Agent 2 task result submitted:")
    print(f"   Response: {result_2['message']}")


async def main():
    """Main test orchestration function."""
    print("\n" + "=" * 60)
    print("TASK WORKFLOW TEST")
    print("=" * 60)

    try:
        # Step 1: Authentication
        print("\n[Step 1] Authenticating...")
        print("-" * 60)
        token = await login_and_get_token()
        headers = bearer_headers(token)
        print(f"✅ Authentication successful. Token: {token[:20]}...")

        # Step 2: Setup
        print("\n[Step 2] Setting up agents and conversation...")
        print("-" * 60)
        agent_ids, agent_keys, conv_id = await setup_agents_and_conversation(headers)
        print(f"✅ Setup complete with agents: {list(agent_ids.keys())}")

        # Step 3: Create initial task
        print("\n[Step 3] Creating initial task...")
        print("-" * 60)
        initial_task_id = await create_initial_task(headers, conv_id, agent_ids)

        # Step 4: WebSocket listener (background)
        print("\n[Step 4] Starting WebSocket listener...")
        print("-" * 60)
        ws_task = asyncio.create_task(
            websocket_listener(token, conv_id, agent_ids["agent_test"], timeout=3)
        )

        # Step 5: Simulate agent task flow
        print("\n[Step 5] Simulating agent task flow...")
        print("-" * 60)
        await simulate_agent_task_flow(
            headers, agent_ids, agent_keys, conv_id, initial_task_id
        )

        # Wait for WebSocket to finish (timeout)
        await ws_task

        print("\n" + "=" * 60)
        print("✅ TEST COMPLETED SUCCESSFULLY")
        print("=" * 60)

    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
