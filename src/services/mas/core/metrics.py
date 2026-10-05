import datetime

from prometheus_client import Counter, Gauge, Histogram

LONG_RUNNING_BUCKETS = (
    0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0, 600.0, 900.0, 1200.0, 1800.0
)

ROUTING_BUCKETS = (
    0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1, 0.2, 0.5, *LONG_RUNNING_BUCKETS[2:]
)

# Business Metrics
AGENT_COUNT = Gauge(
    "mas_agent_count", "Number of currently registered agents", ["status"]
)

TASK_QUEUE_DEPTH = Gauge(
    "mas_task_queue_depth", "Current number of tasks waiting in queue"
)

TASK_ERRORS = Counter(
    "mas_task_errors_total",
    "Total number of task execution errors",
    ["agent_id", "error_type"],
)

TASK_PROCESSING_TIME = Histogram(
    "mas_task_processing_seconds",
    "Time spent processing tasks by agents",
    buckets=LONG_RUNNING_BUCKETS,
)

ROUTING_DECISIONS = Counter(
    "mas_routing_decisions_total",
    "Routing decisions by the router stage that made them and the route chosen",
    ["method", "route"],
)

ROUTING_DECISION_TIME = Histogram(
    "mas_routing_decision_seconds",
    "Time the router took to choose a task's route, by the router stage that chose it",
    ["method"],
    buckets=ROUTING_BUCKETS,
)


def observe_routing_decision(method: str, route: str, seconds: float) -> None:
    ROUTING_DECISIONS.labels(method=method, route=route).inc()
    ROUTING_DECISION_TIME.labels(method=method).observe(max(0.0, seconds))


def observe_task_processing_time(created_at) -> None:
    if not isinstance(created_at, datetime.datetime):
        return
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=datetime.UTC)
    elapsed = datetime.datetime.now(datetime.UTC) - created_at
    TASK_PROCESSING_TIME.observe(max(0.0, elapsed.total_seconds()))
