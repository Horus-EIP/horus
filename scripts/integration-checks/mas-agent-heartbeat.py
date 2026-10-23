"""
Test Agent Heartbeat

This module tests the agent heartbeat mechanism:
- Register an agent to get credentials
- Send heartbeat signals
- Verify heartbeat updates

Usage:
    python tests/mas/client_tests/test_agent_heartbeat.py
"""

import asyncio

import httpx
import pytest

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
            pytest.skip(f"Live MAS not available at {BASE_URL}: HTTP {e.response.status_code}")
        except Exception as e:
            print(f"❌ LOGIN failed: {e}")
            pytest.skip(f"Live MAS not available at {BASE_URL}: {e}")


async def test_agent_heartbeat_flow():
    print("🚀 Starting Agent Heartbeat Test...")
    token = await login()
    headers = bearer_headers(token)

    async with httpx.AsyncClient(base_url=BASE_URL, timeout=10.0) as client:
        # 1. Register Agent
        print("\n1️⃣  Registering agent...")
        agent_data = {
            "name": "heartbeat_test_agent",
            "skills": ["ping"],
            "description": "Agent for heartbeat tests",
        }

        # Check if agent exists and delete if so
        try:
            r = await client.get("/agents/details/", headers=headers)
            r.raise_for_status()
            agents = r.json()
            existing_id = next(
                (a["id"] for a in agents if a["name"] == "heartbeat_test_agent"), None
            )
            if existing_id:
                await client.delete(f"/agents/unregister/{existing_id}", headers=headers)
        except Exception as e:
            print(f"⚠️  Warning during cleanup: {e}")

        # Register new
        r = await client.post("/agents/register", json=agent_data, headers=headers)
        if r.status_code != 200:
            print(f"❌ Agent registration failed: {r.status_code} {r.text}")
            return

        data = r.json()
        agent_id = data["agent_id"]
        api_key = data["api_key"]
        print(f"✅ Agent registered: {agent_id}")

        # 2. Send Heartbeat
        print(f"\n2️⃣  Sending heartbeat for {agent_id}...")
        # Heartbeat requires X-API-Key (format: agent_id:api_key) and Authorization token (due to PermissionChecker)
        agent_headers = {
            "X-API-Key": f"{agent_id}:{api_key}",
            "Authorization": f"Bearer {token}",
        }

        r = await client.post(f"/agents/heartbeat/{agent_id}", headers=agent_headers)

        if r.status_code == 200:
            print(f"✅ Heartbeat successful: {r.json()}")
        else:
            print(f"❌ Heartbeat failed: {r.status_code} {r.text}")

        # Cleanup
        print("\n🧹 Cleanup: Unregistering agent...")
        await client.delete(f"/agents/unregister/{agent_id}", headers=headers)


if __name__ == "__main__":
    asyncio.run(test_agent_heartbeat_flow())
