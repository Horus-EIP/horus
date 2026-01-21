"""
Coverage Completion Tests

This module adds tests for routes that were previously missing from the client test suite:
- GET / (Health check)
- POST /rabbitmq/heartbeat
- GET /agents/details/{id}
- GET /conversations/get_history/{chat_id}
- DELETE /conversations/delete-conversation/{chat_id}

Usage:
    python client_test_coverage_completion.py
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
        r = await client.post(
            "/auth/token",
            data={"username": USERNAME, "password": PASSWORD},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if r.status_code != 200:
            print(f"❌ LOGIN failed: {r.status_code} {r.text}")
            sys.exit(1)
        data = r.json()
        print(f"✅ LOGIN successful")
        return data["access_token"]

async def test_health_check(token: str):
    print("\n[Test] GET / (Health Check)")
    headers = bearer_headers(token)
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=10.0) as client:
        # Test with valid token
        r = await client.get("/", headers=headers)
        if r.status_code == 200:
            print("✅ GET / with token successful")
        else:
            print(f"❌ GET / with token failed: {r.status_code} {r.text}")

        # Test without token
        r = await client.get("/")
        if r.status_code == 401:
            print("✅ GET / without token correctly denied (401)")
        else:
            print(f"❌ GET / without token unexpected status: {r.status_code}")

async def test_rabbitmq_heartbeat():
    print("\n[Test] POST /rabbitmq/heartbeat")
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=10.0) as client:
        r = await client.post("/rabbitmq/heartbeat")
        if r.status_code == 200:
            print("✅ POST /rabbitmq/heartbeat successful")
        else:
            print(f"❌ POST /rabbitmq/heartbeat failed: {r.status_code} {r.text}")

async def test_agent_details(token: str):
    print("\n[Test] GET /agents/details/{id}")
    headers = bearer_headers(token)
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=10.0) as client:
        # 1. Register a temporary agent
        agent_payload = {
            "name": "temp_agent_details_test",
            "skills": ["testing"],
            "description": "Temporary agent for details test"
        }
        r = await client.post("/agents/register", json=agent_payload, headers=headers)
        
        # Handle conflict if exists
        if r.status_code == 409:
            # Try to find it and delete it first? Or just use existing.
            # Let's find it.
            r_list = await client.get("/agents/details/", headers=headers)
            agents = r_list.json()
            agent_id = next((a["id"] for a in agents if a["name"] == agent_payload["name"]), None)
        else:
            if r.status_code != 200:
                print(f"❌ Failed to register temp agent: {r.status_code} {r.text}")
                return
            agent_id = r.json()["agent_id"]

        if not agent_id:
            print("❌ Could not get agent ID for test")
            return

        # 2. Get details by ID
        r = await client.get(f"/agents/details/{agent_id}", headers=headers)
        if r.status_code == 200:
            details = r.json()
            if details["name"] == agent_payload["name"]:
                print(f"✅ GET /agents/details/{agent_id} successful")
            else:
                print(f"❌ GET /agents/details/{agent_id} returned wrong data: {details}")
        else:
            print(f"❌ GET /agents/details/{agent_id} failed: {r.status_code} {r.text}")

        # Cleanup
        await client.delete(f"/agents/unregister/{agent_id}", headers=headers)

async def test_conversation_history_and_delete(token: str):
    print("\n[Test] GET /conversations/get_history/{chat_id} & DELETE /conversations/delete-conversation/{chat_id}")
    headers = bearer_headers(token)
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=10.0) as client:
        # 1. Create conversation
        r = await client.post(
            "/conversations/create-conversation/",
            json={"name": "History Test Conversation"},
            headers=headers
        )
        if r.status_code != 200:
            print(f"❌ Failed to create conversation: {r.status_code} {r.text}")
            return
        
        chat_id = r.json()["conversation_id"]
        print(f"   Created conversation {chat_id}")

        # 2. Get History (should be empty initially)
        r = await client.get(f"/conversations/get_history/{chat_id}", headers=headers)
        if r.status_code == 200:
            history = r.json()
            if isinstance(history, list):
                print(f"✅ GET /conversations/get_history/{chat_id} successful (Items: {len(history)})")
            else:
                print(f"❌ GET /conversations/get_history/{chat_id} returned invalid format")
        else:
            print(f"❌ GET /conversations/get_history/{chat_id} failed: {r.status_code} {r.text}")

        # 3. Delete Conversation
        r = await client.delete(f"/conversations/delete-conversation/{chat_id}", headers=headers)
        if r.status_code == 200:
            print(f"✅ DELETE /conversations/delete-conversation/{chat_id} successful")
        else:
            print(f"❌ DELETE /conversations/delete-conversation/{chat_id} failed: {r.status_code} {r.text}")

        # 4. Verify deletion (Get history should fail with 404)
        r = await client.get(f"/conversations/get_history/{chat_id}", headers=headers)
        if r.status_code == 404:
            print(f"✅ Verified deletion (History returns 404)")
        else:
            print(f"❌ Deletion verification failed. Status: {r.status_code}")

async def main():
    print("=" * 60)
    print("COVERAGE COMPLETION TESTS")
    print("=" * 60)

    try:
        token = await login()
        
        await test_health_check(token)
        await test_rabbitmq_heartbeat()
        await test_agent_details(token)
        await test_conversation_history_and_delete(token)
        
    except Exception as e:
        print(f"\n❌ An unexpected error occurred: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
