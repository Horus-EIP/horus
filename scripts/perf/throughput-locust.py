"""
Throughput micro-benchmark for MAS read endpoints (EIP Tech 4 - K3).

Measures *sustained* requests/sec on the cached read endpoints
(/conversations + /agents/details) with zero think-time.

The /auth/token endpoint is bcrypt-bound and slow under a concurrent login
burst, so we do NOT authenticate inside the test. Fetch one token in the shell
and pass it in via MAS_TOKEN; every virtual user reuses it, so the test
exercises the read path only.

    TOKEN=$(curl -s -X POST http://localhost:8000/auth/token \
        -d "username=admin&password=secret&grant_type=password" \
        -H "Content-Type: application/x-www-form-urlencoded" \
        | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
    MAS_TOKEN="$TOKEN" python3 -m locust -f scripts/perf/throughput-locust.py \
        --headless -u 50 -r 50 -t 45s --host http://localhost:8000 \
        --csv scripts/perf/results-archive/throughput-baseline
"""

import os

from locust import HttpUser, constant, events, task

TOKEN = os.environ.get("MAS_TOKEN", "")


class ReadThroughputUser(HttpUser):
    wait_time = constant(0)

    def _h(self):
        return {"Authorization": f"Bearer {TOKEN}"} if TOKEN else {}

    @task(2)
    def conversations(self):
        self.client.get("/conversations/get-conversations/", headers=self._h(),
                        name="GET /conversations/get-conversations/")

    @task(1)
    def agents(self):
        self.client.get("/agents/details/", headers=self._h(),
                        name="GET /agents/details/")


@events.test_start.add_listener
def _check(environment, **kwargs):
    if not TOKEN:
        print("[throughput] WARNING: MAS_TOKEN is empty - requests will 401")
    else:
        print(f"[throughput] using injected token, length {len(TOKEN)}")


@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):
    s = environment.stats.total
    print("\n" + "=" * 60)
    print("THROUGHPUT TEST COMPLETE")
    print("=" * 60)
    print(f"Total requests: {s.num_requests}")
    print(f"Failures:       {s.num_failures}")
    print(f"Throughput:     {s.total_rps:.1f} req/s")
    print(f"p95 latency:    {s.get_response_time_percentile(0.95):.0f} ms")
