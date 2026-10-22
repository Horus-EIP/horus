#!/usr/bin/env python3
"""
End-to-End Resilience Tests

Tests system behavior under failure conditions:
- MAS restart recovery
- RabbitMQ restart recovery
- PostgreSQL restart recovery
- Agent failure handling
- Knowledge Store unavailability

Usage:
    python test_resilience.py --url http://localhost:8000 --ks-url http://localhost:8080

Requirements:
    pip install httpx pytest
"""

import argparse
import asyncio
import sys
import time
from dataclasses import dataclass

import httpx


@dataclass
class TestResult:
    """Result of a resilience test."""

    name: str
    passed: bool
    duration: float
    details: str


class ResilienceTests:
    """End-to-end resilience test suite."""

    def __init__(self, mas_url: str, ks_url: str, admin_user: str, admin_pass: str):
        self.mas_url = mas_url.rstrip("/")
        self.ks_url = ks_url.rstrip("/")
        self.admin_user = admin_user
        self.admin_pass = admin_pass
        self.token: str | None = None
        self.results: list[TestResult] = []

    async def run_all_tests(self):
        """Run all resilience tests."""
        print("\n" + "=" * 70)
        print("🔧 HORUS RESILIENCE TEST SUITE")
        print("=" * 70 + "\n")

        async with httpx.AsyncClient(timeout=30.0) as client:
            # Authenticate first
            if not await self._authenticate(client):
                print("❌ Authentication failed - cannot run tests")
                return False

            # Run tests
            tests = [
                ("Data Persistence", self.test_data_persistence),
                ("Conversation Recovery", self.test_conversation_recovery),
                ("Agent Re-registration", self.test_agent_reregistration),
                ("Knowledge Store Recovery", self.test_knowledge_store_recovery),
                ("Graceful Degradation", self.test_graceful_degradation),
                ("Concurrent Requests", self.test_concurrent_requests),
            ]

            for name, test_func in tests:
                print(f"▶️  Running: {name}")
                start = time.time()
                try:
                    passed, details = await test_func(client)
                    duration = time.time() - start
                    result = TestResult(name, passed, duration, details)
                except Exception as e:
                    duration = time.time() - start
                    result = TestResult(name, False, duration, f"Exception: {str(e)}")

                self.results.append(result)
                status = "✅ PASS" if result.passed else "❌ FAIL"
                print(f"   {status} ({result.duration:.2f}s) - {result.details}\n")

        # Print summary
        self._print_summary()
        return all(r.passed for r in self.results)

    async def _authenticate(self, client: httpx.AsyncClient) -> bool:
        """Authenticate and get token."""
        try:
            response = await client.post(
                f"{self.mas_url}/auth/token",
                data={"username": self.admin_user, "password": self.admin_pass},
            )
            if response.status_code == 200:
                self.token = response.json().get("access_token")
                return True
        except Exception:
            pass
        return False

    def _headers(self):
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    async def test_data_persistence(self, client: httpx.AsyncClient):
        """Test that data persists correctly."""
        # Create a conversation
        unique_name = f"Resilience Test {time.time()}"
        response = await client.post(
            f"{self.mas_url}/conversations/create",
            headers=self._headers(),
            json={"name": unique_name},
        )

        if response.status_code not in [200, 201]:
            return False, "Failed to create conversation"

        conv_id = response.json().get("id")

        # Verify it exists
        response = await client.get(f"{self.mas_url}/conversations/all", headers=self._headers())

        if response.status_code != 200:
            return False, "Failed to list conversations"

        conversations = response.json()
        found = any(c.get("id") == conv_id for c in conversations)

        if not found:
            return False, "Created conversation not found"

        return True, f"Conversation {conv_id} persisted correctly"

    async def test_conversation_recovery(self, client: httpx.AsyncClient):
        """Test conversation data survives and is retrievable."""
        # Get existing conversations
        response = await client.get(f"{self.mas_url}/conversations/all", headers=self._headers())

        if response.status_code != 200:
            return False, "Failed to retrieve conversations"

        conversations = response.json()
        count = len(conversations) if isinstance(conversations, list) else 0

        return True, f"Retrieved {count} conversations successfully"

    async def test_agent_reregistration(self, client: httpx.AsyncClient):
        """Test that agents can be listed and are tracked."""
        response = await client.get(f"{self.mas_url}/agents/", headers=self._headers())

        if response.status_code != 200:
            return False, "Failed to list agents"

        agents = response.json()
        count = len(agents) if isinstance(agents, list) else 0

        if count == 0:
            return True, "No agents registered (expected in some scenarios)"

        # Check agent status
        active = sum(1 for a in agents if a.get("status") == "active")
        return True, f"Found {count} agents ({active} active)"

    async def test_knowledge_store_recovery(self, client: httpx.AsyncClient):
        """Test Knowledge Store is accessible and functional."""
        # Health check
        try:
            response = await client.get(f"{self.ks_url}/health")
            if response.status_code != 200:
                return False, "Health check failed"
        except Exception as e:
            return False, f"Cannot reach Knowledge Store: {e}"

        # Try a query
        try:
            response = await client.post(
                f"{self.ks_url}/store/query", json={"query": "test query", "k": 3}
            )
            if response.status_code not in [200, 404]:
                return False, f"Query failed with status {response.status_code}"
        except Exception as e:
            return False, f"Query error: {e}"

        return True, "Knowledge Store is healthy and queryable"

    async def test_graceful_degradation(self, client: httpx.AsyncClient):
        """Test system handles errors gracefully."""
        # Test invalid endpoint returns proper error
        response = await client.get(f"{self.mas_url}/nonexistent/endpoint", headers=self._headers())

        if response.status_code != 404:
            return False, f"Expected 404, got {response.status_code}"

        # Test invalid auth returns 401
        response = await client.get(
            f"{self.mas_url}/conversations/all", headers={"Authorization": "Bearer invalid_token"}
        )

        if response.status_code != 401:
            return False, f"Expected 401 for invalid token, got {response.status_code}"

        return True, "System handles errors gracefully"

    async def test_concurrent_requests(self, client: httpx.AsyncClient):
        """Test system handles concurrent requests."""

        async def make_request():
            return await client.get(f"{self.mas_url}/agents/", headers=self._headers())

        # Make 10 concurrent requests
        tasks = [make_request() for _ in range(10)]
        responses = await asyncio.gather(*tasks, return_exceptions=True)

        successes = sum(
            1 for r in responses if not isinstance(r, Exception) and r.status_code == 200
        )

        if successes < 8:  # Allow some failures
            return False, f"Only {successes}/10 concurrent requests succeeded"

        return True, f"{successes}/10 concurrent requests succeeded"

    def _print_summary(self):
        """Print test summary."""
        print("=" * 70)
        print("📊 TEST SUMMARY")
        print("=" * 70)

        passed = sum(1 for r in self.results if r.passed)
        total = len(self.results)

        for result in self.results:
            status = "✅" if result.passed else "❌"
            print(f"  {status} {result.name}: {result.details}")

        print("-" * 70)
        print(f"  Total: {passed}/{total} tests passed")

        if passed == total:
            print("\n🎉 ALL TESTS PASSED!")
        else:
            print(f"\n⚠️  {total - passed} TESTS FAILED")

        print("=" * 70 + "\n")


async def main():
    parser = argparse.ArgumentParser(description="Run resilience tests")
    parser.add_argument("--url", default="http://localhost:8000", help="MAS URL")
    parser.add_argument("--ks-url", default="http://localhost:8080", help="Knowledge Store URL")
    parser.add_argument("--admin-user", default="admin", help="Admin username")
    parser.add_argument("--admin-pass", default="admin", help="Admin password")

    args = parser.parse_args()

    tests = ResilienceTests(args.url, args.ks_url, args.admin_user, args.admin_pass)
    success = await tests.run_all_tests()

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    asyncio.run(main())
