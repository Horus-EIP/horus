"""
MAS - Multi-Agent System Entry Point

This module serves as the main entry point for the Multi-Agent System (MAS) application.
It initializes the FastAPI application, sets up database connections, creates database
tables, and configures the authentication system.

Key Features:
- FastAPI application initialization with comprehensive middleware setup
- Database models creation and initialization
- Initial admin user setup
- Logging configuration and startup monitoring
- Health check endpoint for system status

The application follows a modular architecture with separate components for:
- Authentication and authorization
- Agent registry and management
- Task orchestration and execution
- Real-time communication via WebSockets
- Conversation management and persistence

Environment Variables Required:
- Database configuration (POSTGRES_*)
- JWT configuration (JWT_SECRET_KEY, JWT_ALGORITHM)
- Redis configuration (REDIS_*)
- Initial admin user (SUPER_USER_USERNAME, SUPER_USER_PASSWORD)

Usage:
    Run with: uvicorn main:app --host 0.0.0.0 --port 8000
    Or use Docker: docker-compose up
"""

from typing import Annotated

from fastapi import Depends, HTTPException, status

from auth.auth_tool_functions import get_current_user
from core.app import create_app_environment
from core.logger import get_logger, log_error, log_startup, log_success
from db.dependency import db_dependency as db_dependency

logger = get_logger("main")
log_startup("MAS", "Multi-Agent System starting up...")

app = create_app_environment()

user_dependency = Annotated[dict, Depends(get_current_user)]


@app.get(
    "/",
    status_code=status.HTTP_200_OK,
    summary="Health check and authentication test endpoint",
    description="""
    Root endpoint that serves as both a health check and authentication test.
    
    This endpoint:
    - Verifies that the application is running and responsive
    - Tests JWT token authentication
    - Returns authenticated user information
    - Logs authentication attempts for security monitoring
    
    Requires valid JWT authentication token in Authorization header.
    """,
    tags=["Health"],
    responses={
        200: {
            "description": "Authentication successful",
            "content": {
                "application/json": {
                    "examples": {
                        "success": {
                            "summary": "Successful authentication",
                            "value": {
                                "User": {
                                    "user_id": 1,
                                    "username": "admin",
                                    "role": "admin",
                                    "exp": 1640995200,
                                    "nonce": "abc123",
                                },
                                "message": "Authentification succeed",
                            },
                        },
                    }
                }
            },
        },
        401: {
            "description": "Authentication failed",
            "content": {
                "application/json": {
                    "examples": {
                        "not_authenticated": {
                            "summary": "Missing or invalid token",
                            "value": {"detail": "Not authenticated"},
                        },
                    }
                }
            },
        },
    },
)
async def user(user: user_dependency, db: db_dependency):
    # Handle None user case first
    if user is None:
        logger.info(f"Home endpoint accessed by user: unknown")
        log_error("main", "Authentication failed for home endpoint access")
        raise HTTPException(status_code=401, detail="Not authenticated")

    # User is authenticated - log and proceed
    username = user.get("username", "unknown")
    logger.info(f"Home endpoint accessed by user: {username}")
    log_success("main", f"Authentication successful for user: {username}")
    return {"User": user, "message": "Authentification succeed"}
