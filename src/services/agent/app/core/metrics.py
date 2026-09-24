"""
Prometheus metrics for the agent service.

Exposes metrics for task processing, RAG queries, model inference, and error rates.
"""


from prometheus_client import Counter, Gauge, Histogram

# Task processing metrics
task_processing_total = Counter(
    "agent_tasks_total",
    "Total number of tasks processed",
    ["status"]  # status: success, error
)

task_processing_duration = Histogram(
    "agent_task_processing_duration_seconds",
    "Time spent processing tasks",
    buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0]
)

# RAG pipeline metrics
rag_query_total = Counter(
    "agent_rag_queries_total",
    "Total number of RAG queries",
    ["status"]  # status: success, error, timeout
)

rag_query_duration = Histogram(
    "agent_rag_query_duration_seconds",
    "Time spent on RAG queries",
    buckets=[0.01, 0.05, 0.1, 0.5, 1.0, 2.0, 5.0]
)

rag_query_results = Histogram(
    "agent_rag_query_results_count",
    "Number of results returned by RAG queries",
    buckets=[1, 2, 5, 10, 20, 50]
)

# Model inference metrics
model_inference_total = Counter(
    "agent_model_inferences_total",
    "Total number of model inferences",
    ["model_name", "device", "status"]  # device: cpu, cuda
)

model_inference_duration = Histogram(
    "agent_model_inference_duration_seconds",
    "Time spent on model inference",
    ["model_name", "device"],
    buckets=[0.01, 0.05, 0.1, 0.5, 1.0, 2.0, 5.0, 10.0]
)

# Knowledge store client metrics
knowledge_store_requests_total = Counter(
    "agent_knowledge_store_requests_total",
    "Total number of knowledge store requests",
    ["status"]  # status: success, error, timeout
)

knowledge_store_request_duration = Histogram(
    "agent_knowledge_store_request_duration_seconds",
    "Time spent on knowledge store requests",
    buckets=[0.01, 0.05, 0.1, 0.5, 1.0, 2.0, 5.0, 10.0]
)

# Agent status metrics
agent_registered = Gauge(
    "agent_registered",
    "Whether the agent is registered (1) or not (0)"
)

agent_heartbeat_total = Counter(
    "agent_heartbeats_total",
    "Total number of heartbeats sent",
    ["status"]  # status: success, error
)

# Error metrics
agent_errors_total = Counter(
    "agent_errors_total",
    "Total number of errors",
    ["error_type"]  # error_type: registration, heartbeat, task_processing, rag, model
)

# Task queue metrics
task_queue_size = Gauge(
    "agent_task_queue_size",
    "Current size of the task queue"
)

