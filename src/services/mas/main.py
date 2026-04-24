"""MAS service ASGI entry point.

Wires ``core.app.create_app_environment()`` and exposes a single
authenticated ``/`` health endpoint. Run with
``uvicorn main:app --host 0.0.0.0 --port 8000`` (or Docker Compose).
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
    description="Authenticated ping: returns the decoded JWT claims on success.",
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
