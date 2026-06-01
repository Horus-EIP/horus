"""FastAPI application factory for the MAS service.

``create_app_environment()`` returns a fully wired ``FastAPI`` instance:
middleware, routers, OpenTelemetry, Prometheus instrumentation, and the
lifespan that boots/teardown background tasks.
"""

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_fastapi_instrumentator import Instrumentator

import agents.routes
import analytics.routes
import chat.routes
import conversations.routes
import core.rabbitmq_tool
import tasks.routes
import users.routes
from agents.controller import check_agent_heartbeat
from auth.routes import router as auth_router
from core.embedding_setup import start_embedding_preload_background_thread
from core.llm_setup import start_llm_preload_background_thread
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
    """Build the configured ``FastAPI`` instance.

    Registers CORS, logging middleware, all routers (/agents, /chat,
    /conversations, /tasks, /auth, /users, /rabbitmq), tracing, and
    Prometheus instrumentation.
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
        (analytics.routes.router, "Analytics"),
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
    """FastAPI lifespan: init DB and background tasks at startup, cancel them cleanly on shutdown."""
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

    start_llm_preload_background_thread()
    log_success("lifespan", "LLM background preload started (if LLM_AUTOINIT=1)")

    start_embedding_preload_background_thread()
    log_success(
        "lifespan",
        "Sentence-embedding model background preload started (warms skill cache)",
    )

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
