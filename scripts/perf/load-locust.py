"""
Locust Load Testing for Horus MAS

Drives realistic authenticated read/write traffic against the MAS API so we can
measure latency under concurrency (EIP Tech 4, point D / K1 - chat p95).

Usage:
    python3 -m locust -f scripts/perf/load-locust.py --headless \
        -u 20 -r 5 -t 2m --host http://localhost:8000 \
        --csv scripts/perf/results-archive/locust-baseline

Auth/endpoints verified against the current MAS API (May 2026):
    POST /auth/token                          (OAuth2 password flow, grant_type=password)
    GET  /conversations/get-conversations/
    POST /conversations/create-conversation/  (body: {"name": ...})
    GET  /agents/details/
    GET  /users/me
    GET  /users/users_list
    GET  /tasks/stats/queue
    GET  /tasks/list

Credentials default to admin / SUPER_USER_PASSWORD (default "secret").
"""

import os
import time

from locust import HttpUser, between, events, task

ADMIN_USER = os.environ.get("SUPER_USER_USERNAME", "admin")
ADMIN_PASS = os.environ.get("SUPER_USER_PASSWORD", "secret")


class MASUser(HttpUser):
    """A typical authenticated MAS user: reads dominate, writes are rarer."""

    wait_time = between(1, 5)
    token: str | None = None

    def on_start(self):
        with self.client.post(
            "/auth/token",
            data={
                "username": ADMIN_USER,
                "password": ADMIN_PASS,
                "grant_type": "password",
            },
            catch_response=True,
        ) as response:
            if response.status_code == 200:
                self.token = response.json().get("access_token")
                response.success()
            else:
                response.failure(f"auth failed: {response.status_code}")

    def _headers(self):
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    @task(10)
    def list_conversations(self):
        self.client.get("/conversations/get-conversations/", headers=self._headers(),
                        name="GET /conversations/get-conversations/")

    @task(5)
    def list_agents(self):
        self.client.get("/agents/details/", headers=self._headers(),
                        name="GET /agents/details/")

    @task(5)
    def me(self):
        self.client.get("/users/me", headers=self._headers(), name="GET /users/me")

    @task(3)
    def task_queue_stats(self):
        self.client.get("/tasks/stats/queue", headers=self._headers(),
                        name="GET /tasks/stats/queue")

    @task(3)
    def task_list(self):
        self.client.get("/tasks/list", headers=self._headers(), name="GET /tasks/list")

    @task(2)
    def users_list(self):
        self.client.get("/users/users_list", headers=self._headers(),
                        name="GET /users/users_list")

    @task(2)
    def create_conversation(self):
        self.client.post(
            "/conversations/create-conversation/",
            headers=self._headers(),
            json={"name": f"Load Test Conversation {time.time():.0f}"},
            name="POST /conversations/create-conversation/",
        )


@events.request.add_listener
def on_request(request_type, name, response_time, response_length, exception, **kwargs):
    if response_time > 1000:
        print(f"SLOW REQUEST: {request_type} {name} took {response_time:.0f}ms")


@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):
    stats = environment.stats
    print("\n" + "=" * 60)
    print("LOAD TEST COMPLETE")
    print("=" * 60)
    print(f"Total requests:        {stats.total.num_requests}")
    print(f"Failed requests:       {stats.total.num_failures}")
    print(f"Average response time: {stats.total.avg_response_time:.2f} ms")
    print(f"p95 response time:     {stats.total.get_response_time_percentile(0.95):.0f} ms")
    print(f"Requests/sec:          {stats.total.total_rps:.2f}")
    if stats.total.num_requests:
        rate = (stats.total.num_failures / stats.total.num_requests) * 100
        print(f"Failure rate:          {rate:.2f}%")
