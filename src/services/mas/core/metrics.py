"""
Prometheus Metrics Module for MAS.

Comprehensive metrics collection for:
- HTTP request counts and latencies
- Agent lifecycle metrics
- Task queue and processing metrics
- Error rates by type
- Database connection pool metrics

Usage:
    from core.metrics import (
        REQUEST_COUNT, REQUEST_LATENCY,
        increment_request_count, observe_request_latency
    )
    
    # In middleware or route handlers
    increment_request_count(method="POST", endpoint="/tasks", status="200")
    observe_request_latency(method="POST", endpoint="/tasks", duration=0.125)
"""

from prometheus_client import Counter, Gauge, Histogram, Info

# =============================================================================
# HTTP Request Metrics
# =============================================================================

REQUEST_COUNT = Counter(
    "mas_http_requests_total",
    "Total number of HTTP requests",
    ["method", "endpoint", "status_code"]
)

REQUEST_LATENCY = Histogram(
    "mas_http_request_duration_seconds",
    "HTTP request latency in seconds",
    ["method", "endpoint"],
    buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0]
)

REQUEST_IN_PROGRESS = Gauge(
    "mas_http_requests_in_progress",
    "Number of HTTP requests currently being processed",
    ["method", "endpoint"]
)

# =============================================================================
# Agent Metrics
# =============================================================================

AGENT_COUNT = Gauge(
    "mas_agents_total",
    "Total number of registered agents",
    ["status"]  # active, inactive
)

AGENT_REGISTRATIONS = Counter(
    "mas_agent_registrations_total",
    "Total number of agent registration attempts",
    ["status"]  # success, failure
)

AGENT_HEARTBEATS = Counter(
    "mas_agent_heartbeats_total",
    "Total number of agent heartbeats received",
    ["agent_id", "status"]  # success, failure, timeout
)

AGENT_LAST_HEARTBEAT = Gauge(
    "mas_agent_last_heartbeat_timestamp",
    "Timestamp of last heartbeat from agent",
    ["agent_id", "agent_name"]
)

# =============================================================================
# Task Metrics
# =============================================================================

TASK_COUNT = Counter(
    "mas_tasks_total",
    "Total number of tasks created",
    ["status"]  # created, assigned, completed, failed, cancelled
)

TASK_QUEUE_DEPTH = Gauge(
    "mas_task_queue_depth",
    "Current number of tasks in each state",
    ["status"]  # pending, running, completed, failed
)

TASK_PROCESSING_TIME = Histogram(
    "mas_task_processing_duration_seconds",
    "Time spent processing tasks",
    ["agent_id"],
    buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0]
)

TASK_ASSIGNMENT_TIME = Histogram(
    "mas_task_assignment_duration_seconds",
    "Time to assign a task to an agent",
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0]
)

# =============================================================================
# Error Metrics
# =============================================================================

ERROR_COUNT = Counter(
    "mas_errors_total",
    "Total number of errors",
    ["type", "component"]  # type: validation, auth, database, rabbitmq, etc.
)

# =============================================================================
# RabbitMQ Metrics
# =============================================================================

RABBITMQ_MESSAGES_PUBLISHED = Counter(
    "mas_rabbitmq_messages_published_total",
    "Total number of messages published to RabbitMQ",
    ["queue", "status"]  # success, failure
)

RABBITMQ_CONNECTION_STATUS = Gauge(
    "mas_rabbitmq_connection_status",
    "RabbitMQ connection status (1=connected, 0=disconnected)"
)

# =============================================================================
# Conversation Metrics
# =============================================================================

CONVERSATION_COUNT = Gauge(
    "mas_conversations_total",
    "Total number of conversations"
)

MESSAGE_COUNT = Counter(
    "mas_messages_total",
    "Total number of messages",
    ["role"]  # user, assistant, system
)

WEBSOCKET_CONNECTIONS = Gauge(
    "mas_websocket_connections_active",
    "Number of active WebSocket connections"
)

# =============================================================================
# System Info
# =============================================================================

SYSTEM_INFO = Info(
    "mas_system",
    "MAS system information"
)

# =============================================================================
# Helper Functions
# =============================================================================


def increment_request_count(method: str, endpoint: str, status_code: int):
    """Increment the request counter."""
    REQUEST_COUNT.labels(
        method=method,
        endpoint=endpoint,
        status_code=str(status_code)
    ).inc()


def observe_request_latency(method: str, endpoint: str, duration: float):
    """Record request latency."""
    REQUEST_LATENCY.labels(method=method, endpoint=endpoint).observe(duration)


def track_request_in_progress(method: str, endpoint: str, increment: bool = True):
    """Track requests currently in progress."""
    gauge = REQUEST_IN_PROGRESS.labels(method=method, endpoint=endpoint)
    if increment:
        gauge.inc()
    else:
        gauge.dec()


def update_agent_count(active: int, inactive: int):
    """Update agent count gauges."""
    AGENT_COUNT.labels(status="active").set(active)
    AGENT_COUNT.labels(status="inactive").set(inactive)


def record_agent_registration(success: bool):
    """Record an agent registration attempt."""
    AGENT_REGISTRATIONS.labels(status="success" if success else "failure").inc()


def record_agent_heartbeat(agent_id: str, agent_name: str, success: bool):
    """Record an agent heartbeat."""
    AGENT_HEARTBEATS.labels(
        agent_id=agent_id,
        status="success" if success else "failure"
    ).inc()
    if success:
        import time
        AGENT_LAST_HEARTBEAT.labels(agent_id=agent_id, agent_name=agent_name).set(time.time())


def record_task_created(status: str = "created"):
    """Record a task creation."""
    TASK_COUNT.labels(status=status).inc()


def update_task_queue_depth(pending: int, running: int, completed: int, failed: int):
    """Update task queue depth gauges."""
    TASK_QUEUE_DEPTH.labels(status="pending").set(pending)
    TASK_QUEUE_DEPTH.labels(status="running").set(running)
    TASK_QUEUE_DEPTH.labels(status="completed").set(completed)
    TASK_QUEUE_DEPTH.labels(status="failed").set(failed)


def observe_task_processing_time(agent_id: str, duration: float):
    """Record task processing time."""
    TASK_PROCESSING_TIME.labels(agent_id=agent_id).observe(duration)


def observe_task_assignment_time(duration: float):
    """Record task assignment time."""
    TASK_ASSIGNMENT_TIME.observe(duration)


def record_error(error_type: str, component: str):
    """Record an error occurrence."""
    ERROR_COUNT.labels(type=error_type, component=component).inc()


def record_rabbitmq_publish(queue: str, success: bool):
    """Record a RabbitMQ publish attempt."""
    RABBITMQ_MESSAGES_PUBLISHED.labels(
        queue=queue,
        status="success" if success else "failure"
    ).inc()


def set_rabbitmq_connection_status(connected: bool):
    """Set RabbitMQ connection status."""
    RABBITMQ_CONNECTION_STATUS.set(1 if connected else 0)


def record_message(role: str):
    """Record a message creation."""
    MESSAGE_COUNT.labels(role=role).inc()


def set_websocket_connections(count: int):
    """Set the number of active WebSocket connections."""
    WEBSOCKET_CONNECTIONS.set(count)


def set_system_info(version: str, environment: str):
    """Set system information."""
    SYSTEM_INFO.info({
        "version": version,
        "environment": environment
    })
