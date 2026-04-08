"""
FastAPI Application Factory

This module provides the application factory pattern for creating and configuring
the FastAPI application instance. It handles:

- Application lifecycle management with async context managers
- Middleware configuration (CORS, logging, security)
- Router registration for all API endpoints
- Background task management (agent heartbeat monitoring)
- Graceful shutdown handling

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
- Custom logging middleware for request/response tracking
- Router inclusion with organized endpoint grouping
- Background task coordination

Usage:
    The create_app_environment() function returns a configured FastAPI instance
    ready for deployment or testing.
"""

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import make_asgi_app
from prometheus_fastapi_instrumentator import Instrumentator

import agents.routes
import chat.routes
import conversations.routes
import core.rabbitmq_tool
import db.models
import tasks.routes
import users.routes
from agents.controller import check_agent_heartbeat
from auth.routes import router as auth_router
from core.logger import get_logger, log_error, log_startup, log_success
from core.middleware import LoggingMiddleware
from core.rabbitmq_tool import rabbitmq_instance
from core.tracing import init_tracing
from db.database import engine
from db.init_setup import init_db
from tasks.controller import check_task_timeout

instrumentator = None

logger = get_logger("app")


def create_app_environment():
    """
    Create and configure the FastAPI application environment.

    This function serves as the application factory, creating a fully configured
    FastAPI instance with all necessary middleware, routers, and settings.

    Configuration includes:
    - CORS middleware for cross-origin requests (configured for development)
    - Custom logging middleware for request/response tracking
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
        """,
        version="1.0.0",
        openapi_tags=[
            {
                "name": "Health",
                "description": "Health check and system status endpoints",
            },
            {
                "name": "Authentication",
                "description": "Login, registration, and token management",
            },
            {
                "name": "Agents",
                "description": "Agent registration, heartbeat, and management",
            },
            {
                "name": "Tasks",
                "description": "Task creation, assignment, and status tracking",
            },
            {"name": "Chat", "description": "WebSocket chat endpoints"},
            {
                "name": "Conversations",
                "description": "Conversation history and management",
            },
            {"name": "Users", "description": "User management (Admin only)"},
            {"name": "RabbitMQ", "description": "Message queue management"},
        ],
    )

    app.add_middleware(LoggingMiddleware)
    log_success("app", "Logging middleware added")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["Content-Disposition"],
    )
    log_success("app", "CORS middleware configured")

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

    if init_tracing(app):
        log_success("app", "OpenTelemetry tracing initialized")

    global instrumentator
    instrumentator = Instrumentator().instrument(app)
    instrumentator.expose(app)

    log_success("app", "FastAPI application environment created successfully")
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
        # Note: Base.metadata.create_all() should NOT be called here
        # It's called in init_db() after migrations run, to avoid conflicts
        # with Alembic when running migrations
        # db.models.Base.metadata.create_all(bind=engine)
        # log_success("lifespan", "Database models created successfully")

        init_db()
        log_success("lifespan", "Database initialized successfully")

    except Exception as e:
        log_error("lifespan", f"Failed to initialize database: {str(e)}", exc_info=True)
        raise

    task = asyncio.create_task(check_agent_heartbeat())
    log_success("lifespan", "Agent heartbeat monitoring started")

    task_timeout_checker = asyncio.create_task(check_task_timeout())
    log_success("lifespan", "Task timeout monitoring started")

    try:
        rabbitmq_instance.connect()
        log_success("lifespan", "RabbitMQ connection established")
    except Exception as e:
        log_error("lifespan", f"Failed to connect to RabbitMQ: {str(e)}", exc_info=True)
        raise

    yield
    logger.info("Shutting down application...")
    task.cancel()
    task_timeout_checker.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    if rabbitmq_instance:
        rabbitmq_instance.close()
    engine.dispose()
    log_success("lifespan", "Application shutdown completed")
