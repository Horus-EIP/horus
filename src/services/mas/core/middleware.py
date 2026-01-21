"""
Middleware pour logging automatique des requêtes FastAPI
"""

import time
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from core.hybrid_logging import log_system_performance
from core.logger import get_logger, log_api_request


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
        # Skip logging for excluded paths
        if request.url.path in self.exclude_paths:
            return await call_next(request)

        # Log request start
        start_time = time.time()
        client_ip = request.client.host if request.client else "unknown"
        user_agent = request.headers.get("user-agent", "unknown")

        self.logger.info(
            f"📥 Incoming {request.method} {request.url.path} from {client_ip}"
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
                details=f"Status: {response.status_code}, IP: {client_ip}",
            )

            return response

        except Exception as e:
            # Log error
            duration = (time.time() - start_time) * 1000
            self.logger.error(
                f"💥 Error processing {request.method} {request.url.path}: {str(e)}",
                exc_info=True,
            )

            # Re-raise the exception
            raise e
