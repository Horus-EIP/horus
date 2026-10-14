"""
Middleware pour logging automatique des requêtes FastAPI
"""

import time
import uuid
from collections.abc import Callable

import structlog
from core.hybrid_logging import log_system_performance
from core.logger import get_logger, log_api_request
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware


class LoggingMiddleware(BaseHTTPMiddleware):
    """Middleware pour logger automatiquement toutes les requêtes API"""

    def __init__(self, app, exclude_paths: list = None):
        super().__init__(app)
        self.exclude_paths = exclude_paths or [
            "/docs",
            "/redoc",
            "/openapi.json",
            "/favicon.ico",
        ]
        self.logger = get_logger("middleware")

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """
        Intercepts requests to add logging and correlation IDs.

        1. Generates a UUID for the request (X-Request-ID).
        2. Binds the UUID to structlog's contextvars.
        3. Logs the request start event.
        4. Executes the request and measures duration.
        5. Logs the request completion (or failure).
        6. Adds X-Request-ID header to the response.
        7. Clears contextvars.
        """
        # Skip logging for excluded paths
        if request.url.path in self.exclude_paths:
            return await call_next(request)

        # Log request start
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        structlog.contextvars.bind_contextvars(correlation_id=str(request_id))
        start_time = time.time()
        client_ip = request.client.host if request.client else "unknown"
        user_agent = request.headers.get("user-agent", "unknown")

        self.logger.info(
            "Request started",
            method=request.method,
            path=request.url.path,
            ip=client_ip,
            user_agent=user_agent,
        )

        # Process request
        try:
            response = await call_next(request)

            # Calculate duration
            duration = (time.time() - start_time) * 1000

            # Log successful response
            log_api_request(
                method=request.method,
                endpoint=request.url.path,
                status_code=response.status_code,
                duration=duration,
            )

            # Log performance dans les fichiers
            log_system_performance(
                "api",
                f"{request.method} {request.url.path}",
                duration=duration / 1000,  # en secondes
                details=f"Status: {response.status_code}, IP: {client_ip} ({duration:.3f}ms)",
            )

            response.headers["X-Request-ID"] = str(request_id)

            return response

        except Exception as e:
            # Log error
            duration = (time.time() - start_time) * 1000
            self.logger.error(
                "Request failed",
                method=request.method,
                path=request.url.path,
                error=str(e),
                duration=duration,
                exc_info=True,
            )

            # Re-raise the exception
            raise e
        finally:
            structlog.contextvars.clear_contextvars()
