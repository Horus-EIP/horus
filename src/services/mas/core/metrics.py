from prometheus_client import Counter, Gauge, Histogram

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
    buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0],
)
