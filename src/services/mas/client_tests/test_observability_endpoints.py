"""
Test Observability Endpoints

This module tests the availability of observability-related endpoints:
- /metrics (Prometheus)
- /rabbitmq/heartbeat (Health check)

Usage:
    python src/services/mas/client_tests/test_observability_endpoints.py
"""

import asyncio
import sys

import httpx

BASE_URL = "http://localhost:8000"
USERNAME = "admin"
PASSWORD = "secret"


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
        except Exception:
            return None


def bearer_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def test_observability():
    print("🚀 Starting Observability Endpoints Test...")

    # Try to get token, but proceed even if it fails (some endpoints might be public)
    token = await login()
    headers = bearer_headers(token) if token else {}

    async with httpx.AsyncClient(
        base_url=BASE_URL, headers=headers, timeout=10.0
    ) as client:
        # 1. Check Metrics Endpoint
        print("\n1️⃣  Checking /metrics endpoint...")
        try:
            r = await client.get("/metrics")
            if r.status_code == 200:
                print("✅ /metrics is accessible")
                # Check for some expected metrics
                expected_metrics = [
                    "python_gc_objects_collected_total",
                    "process_virtual_memory_bytes",
                ]
                found = [m for m in expected_metrics if m in r.text]
                if found:
                    print(f"✅ Found standard metrics: {found}")

                if "mas_task_queue_depth" in r.text:
                    print("✅ Found 'mas_task_queue_depth' metric")
                else:
                    print(
                        "ℹ️  'mas_task_queue_depth' metric not found (might be 0 or not initialized)"
                    )
            else:
                print(f"❌ /metrics failed: {r.status_code} {r.text}")
        except Exception as e:
            print(f"❌ /metrics check failed with error: {e}")

        # 2. Check RabbitMQ Heartbeat (Health)
        print("\n2️⃣  Checking /rabbitmq/heartbeat endpoint...")
        try:
            r = await client.post("/rabbitmq/heartbeat")
            if r.status_code == 200:
                print("✅ /rabbitmq/heartbeat is accessible")
            elif r.status_code == 401:
                print(
                    "❌ /rabbitmq/heartbeat requires authentication (and token failed or wasn't provided)"
                )
            else:
                print(f"❌ /rabbitmq/heartbeat failed: {r.status_code} {r.text}")
        except Exception as e:
            print(f"❌ /rabbitmq/heartbeat check failed with error: {e}")


if __name__ == "__main__":
    asyncio.run(test_observability())
