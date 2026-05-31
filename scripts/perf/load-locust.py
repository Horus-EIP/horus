"""
Locust Load Testing for Horus MAS

This file defines load test scenarios for the Multi-Agent System.

Usage:
    # Install locust
    pip install locust

    # Run with web UI
    locust -f locustfile.py --host=http://localhost:8000

    # Run headless
    locust -f locustfile.py --host=http://localhost:8000 \
           --users 100 --spawn-rate 10 --run-time 5m --headless

Scenarios:
    - MASUser: Simulates typical user behavior
    - AgentUser: Simulates agent heartbeat and task processing
    - AdminUser: Simulates admin operations
"""

import json
import random
import time
from typing import Optional

from locust import HttpUser, between, task, events


class MASUser(HttpUser):
    """
    Simulates a typical MAS user:
    - Lists conversations
    - Creates conversations
    - Lists agents
    - Creates tasks
    """
    
    wait_time = between(1, 5)  # Wait 1-5 seconds between tasks
    token: Optional[str] = None
    conversation_ids: list = []
    
    def on_start(self):
        """Authenticate on start."""
        response = self.client.post(
            "/auth/token",
            data={"username": "admin", "password": "admin"}
        )
        if response.status_code == 200:
            self.token = response.json().get("access_token")
    
    def _headers(self):
        headers = {}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers
    
    @task(10)
    def list_conversations(self):
        """List all conversations (high frequency)."""
        with self.client.get(
            "/conversations/all",
            headers=self._headers(),
            catch_response=True
        ) as response:
            if response.status_code == 200:
                data = response.json()
                # Store conversation IDs for later use
                if isinstance(data, list):
                    self.conversation_ids = [c.get("id") for c in data[:10]]
                response.success()
            else:
                response.failure(f"Status: {response.status_code}")
    
    @task(5)
    def list_agents(self):
        """List available agents."""
        self.client.get("/agents/", headers=self._headers())
    
    @task(3)
    def create_conversation(self):
        """Create a new conversation."""
        response = self.client.post(
            "/conversations/create",
            headers=self._headers(),
            json={"name": f"Load Test Conversation {time.time()}"}
        )
        if response.status_code in [200, 201]:
            data = response.json()
            if data.get("id"):
                self.conversation_ids.append(data["id"])
    
    @task(2)
    def get_task_stats(self):
        """Get task queue statistics."""
        self.client.get("/tasks/stats/queue", headers=self._headers())
    
    @task(1)
    def create_task(self):
        """Create a new task (if conversations exist)."""
        if self.conversation_ids:
            conv_id = random.choice(self.conversation_ids)
            self.client.post(
                "/tasks/new_task/",
                headers=self._headers(),
                json={
                    "demand": "What is the quarterly revenue?",
                    "conversation_id": str(conv_id),
                    "skills_required": ["nlp"]
                }
            )


class AgentUser(HttpUser):
    """
    Simulates an agent:
    - Sends regular heartbeats
    - Processes task results
    """
    
    wait_time = between(5, 15)  # Agents are less frequent
    agent_id: Optional[str] = None
    api_key: Optional[str] = None
    token: Optional[str] = None
    
    def on_start(self):
        """Register agent and authenticate."""
        # First authenticate
        response = self.client.post(
            "/auth/token",
            data={"username": "admin", "password": "admin"}
        )
        if response.status_code == 200:
            self.token = response.json().get("access_token")
        
        # Register as agent
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        response = self.client.post(
            "/agents/register",
            headers=headers,
            json={
                "name": f"LoadTestAgent-{random.randint(1000, 9999)}",
                "skills": ["nlp", "summarization"],
                "description": "Load test agent"
            }
        )
        if response.status_code == 200:
            data = response.json()
            self.agent_id = data.get("agent_id")
            self.api_key = data.get("api_key")
    
    def _headers(self):
        headers = {}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if self.agent_id and self.api_key:
            headers["X-API-Key"] = f"{self.agent_id}:{self.api_key}"
            headers["Agent-ID"] = self.agent_id
        return headers
    
    @task(10)
    def heartbeat(self):
        """Send heartbeat (high frequency for agents)."""
        if self.agent_id:
            self.client.post(
                f"/agents/heartbeat/{self.agent_id}",
                headers=self._headers()
            )
    
    @task(1)
    def list_agents(self):
        """Check agent status."""
        self.client.get("/agents/", headers=self._headers())


class AdminUser(HttpUser):
    """
    Simulates an admin user:
    - Lists users
    - Views analytics
    - Monitors system
    """
    
    wait_time = between(2, 10)
    token: Optional[str] = None
    
    def on_start(self):
        """Authenticate as admin."""
        response = self.client.post(
            "/auth/token",
            data={"username": "admin", "password": "admin"}
        )
        if response.status_code == 200:
            self.token = response.json().get("access_token")
    
    def _headers(self):
        headers = {}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers
    
    @task(5)
    def list_users(self):
        """List all users."""
        self.client.get("/users/all", headers=self._headers())
    
    @task(5)
    def list_agents(self):
        """List all agents."""
        self.client.get("/agents/", headers=self._headers())
    
    @task(3)
    def get_task_stats(self):
        """Get task statistics."""
        self.client.get("/tasks/stats/queue", headers=self._headers())
    
    @task(2)
    def list_conversations(self):
        """List conversations."""
        self.client.get("/conversations/all", headers=self._headers())
    
    @task(1)
    def health_check(self):
        """System health check."""
        self.client.post("/rabbitmq/heartbeat", headers=self._headers())


# Event handlers for custom reporting
@events.request.add_listener
def on_request(request_type, name, response_time, response_length, exception, **kwargs):
    """Log slow requests."""
    if response_time > 1000:  # > 1 second
        print(f"SLOW REQUEST: {request_type} {name} took {response_time}ms")


@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):
    """Print summary on test stop."""
    print("\n" + "="*60)
    print("LOAD TEST COMPLETE")
    print("="*60)
    
    stats = environment.stats
    print(f"Total requests: {stats.total.num_requests}")
    print(f"Failed requests: {stats.total.num_failures}")
    print(f"Average response time: {stats.total.avg_response_time:.2f}ms")
    print(f"Requests/sec: {stats.total.total_rps:.2f}")
    
    if stats.total.num_failures > 0:
        failure_rate = (stats.total.num_failures / stats.total.num_requests) * 100
        print(f"Failure rate: {failure_rate:.2f}%")
