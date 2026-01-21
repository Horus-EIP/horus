"""
FastAPI Application Factory

This module provides the application factory pattern for creating and configuring
the FastAPI application instance. It handles:

- Application lifecycle management with async context managers
- Middleware configuration (CORS, logging, security, metrics, tracing)
- Router registration for all API endpoints
- Background task management (agent heartbeat monitoring)
- Graceful shutdown handling
- Observability stack (structured logging, metrics, distributed tracing)

The application follows a modular architecture with clear separation of concerns:
- Authentication and authorization
- Agent registry and lifecycle management
- Task orchestration and execution
- Real-time communication via WebSockets
- Conversation persistence and management
- User administration

Key Components:
- Lifespan management for startup/shutdown tasks
- CORS middleware for cross-origin requests
- Correlation ID middleware for request tracing
- Metrics middleware for Prometheus metrics
- OpenTelemetry tracing for distributed traces
- Router inclusion with organized endpoint grouping
- Background task coordination

Usage:
    The create_app_environment() function returns a configured FastAPI instance
    ready for deployment or testing.
"""

import asyncio
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import make_asgi_app

import agents.routes
import chat.routes
import conversations.routes
import core.rabbitmq_tool
import db.models
import tasks.routes
import users.routes
from agents.controller import check_agent_heartbeat
from auth.routes import router as auth_router
from core.correlation_middleware import CorrelationIDMiddleware
from core.logger import get_logger, log_error, log_startup, log_success
from core.metrics import set_rabbitmq_connection_status, set_system_info
from core.metrics_middleware import MetricsMiddleware
from core.middleware import LoggingMiddleware
from core.rabbitmq_tool import rabbitmq_instance
from core.structured_logging import get_structured_logger
# OpenTelemetry auto-instrumentation is handled by opentelemetry-instrument wrapper
# See Dockerfile CMD / entrypoint.sh for details
from db.database import engine
from db.init_setup import init_db

logger = get_logger("app")
structured_logger = get_structured_logger("app")


def create_app_environment():
    """
    Create and configure the FastAPI application environment.

    This function serves as the application factory, creating a fully configured
    FastAPI instance with all necessary middleware, routers, and settings.

    Configuration includes:
    - CORS middleware for cross-origin requests (configured for development)
    - Correlation ID middleware for request tracing
    - Metrics middleware for Prometheus metrics collection
    - Custom logging middleware for request/response tracking
    - OpenTelemetry tracing for distributed traces
    - All API routers organized by functionality
    - Application metadata (title, version, description)

    Returns:
        FastAPI: Fully configured FastAPI application instance

    Router Organization:
        - /agents: Agent registration, management, and health monitoring
        - /chat: WebSocket endpoints for real-time communication
        - /conversations: Conversation CRUD operations and history
        - /tasks: Task creation, distribution, and result handling
        - /auth: Authentication, registration, and token management
        - /users: User administration (admin-only operations)
    """
    log_startup("APP", "Creating FastAPI application environment...")

    app = FastAPI(
        lifespan=lifespan,
        title="MAS - Multi-Agent System",
        description="""
        Multi-Agent System (MAS) API
        
        This API provides endpoints for:
        - **Authentication**: User login and registration
        - **Agents**: Management and orchestration of AI agents
        - **Tasks**: Task distribution and execution
        - **Chat**: Real-time communication
        - **Conversations**: History and management
        - **Users**: User administration
        
        ## Observability
        - **Metrics**: `/metrics` - Prometheus metrics endpoint
        - **Tracing**: Distributed tracing via OpenTelemetry/Jaeger
        - **Logging**: Structured JSON logging with correlation IDs
        """,
        version="1.0.0",
        openapi_tags=[
            {"name": "Authentication", "description": "Login, registration, and token management"},
            {"name": "Agents", "description": "Agent registration, heartbeat, and management"},
            {"name": "Tasks", "description": "Task creation, assignment, status tracking, and cancellation"},
            {"name": "Chat", "description": "WebSocket chat endpoints"},
            {"name": "Conversations", "description": "Conversation history and management"},
            {"name": "Users", "description": "User management (Admin only)"},
            {"name": "RabbitMQ", "description": "Message queue management"},
        ]
    )
    
    # Mount Prometheus metrics endpoint
    metrics_app = make_asgi_app()
    app.mount("/metrics", metrics_app)
    log_success("app", "Prometheus metrics endpoint mounted at /metrics")

    # OpenTelemetry tracing is handled automatically by opentelemetry-instrument wrapper
    # See Dockerfile/entrypoint.sh - no manual setup needed
    log_success("app", "OpenTelemetry auto-instrumentation active")

    # Add middleware in order (first added = outermost = last to execute on request)
    # Order matters: CORS -> Correlation ID -> Metrics -> Logging
    
    app.add_middleware(LoggingMiddleware)
    log_success("app", "Logging middleware added")
    
    app.add_middleware(MetricsMiddleware)
    log_success("app", "Metrics middleware added")
    
    app.add_middleware(CorrelationIDMiddleware)
    log_success("app", "Correlation ID middleware added")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["Content-Disposition", "X-Request-ID", "X-Correlation-ID"],
    )
    log_success("app", "CORS middleware configured")

    # Set system info for metrics
    set_system_info(
        version="1.0.0",
        environment=os.getenv("ENVIRONMENT", "development")
    )

    routers = [
        (agents.routes.router, "Agents"),
        (chat.routes.router, "Chat"),
        (conversations.routes.router, "Conversations"),
        (tasks.routes.router, "Tasks"),
        (auth_router, "Authentication"),
        (users.routes.router, "Users"),
        (core.rabbitmq_tool.router, "RabbitMQ"),
    ]

    for router, name in routers:
        app.include_router(router)
        logger.info(f"{name} router included")

    log_success("app", "FastAPI application environment created successfully")
    structured_logger.info(
        "Application initialized",
        extra={
            "type": "startup",
            "tracing_enabled": True,  # Auto-instrumentation via opentelemetry-instrument
            "metrics_enabled": True,
            "environment": os.getenv("ENVIRONMENT", "development"),
        }
    )
    return app


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan context manager.

    Manages the application lifecycle from startup to shutdown, handling:
    - Database initialization (create tables, setup)
    - Background task initialization (agent heartbeat monitoring)
    - Resource cleanup on shutdown
    - Graceful task cancellation

    Startup Tasks:
    - Create database models and tables
    - Initialize database with default data
    - Initialize agent heartbeat monitoring system
    - Start background health check routines
    - Log successful startup completion

    Shutdown Tasks:
    - Cancel all background tasks gracefully
    - Clean up resources and connections
    - Log successful shutdown completion

    Args:
        app: FastAPI application instance

    Yields:
        None: Context for application runtime
    """
    log_startup("LIFESPAN", "Starting application lifespan management...")

    try:
        init_db()
        log_success("lifespan", "Database initialized successfully")

    except Exception as e:
        log_error("lifespan", f"Failed to initialize database: {str(e)}", exc_info=True)
        raise

    task = asyncio.create_task(check_agent_heartbeat())
    log_success("lifespan", "Agent heartbeat monitoring started")

    try:
        rabbitmq_instance.connect()
        set_rabbitmq_connection_status(True)
        log_success("lifespan", "RabbitMQ connection established")
    except Exception as e:
        set_rabbitmq_connection_status(False)
        log_error("lifespan", f"Failed to connect to RabbitMQ: {str(e)}", exc_info=True)
        raise

    yield
    
    # Shutdown
    structured_logger.info("Application shutdown initiated", extra={"type": "shutdown"})
    logger.info("Shutting down application...")
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    if rabbitmq_instance:
        rabbitmq_instance.close()
        set_rabbitmq_connection_status(False)
    engine.dispose()
    log_success("lifespan", "Application shutdown completed")
