"""Observability middleware: correlation IDs, request metrics, structured logging."""

import time
import uuid
from collections.abc import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.logging import (
    clear_correlation_id,
    get_logger,
    set_correlation_id,
)

logger = get_logger("middleware")


class CorrelationIDMiddleware(BaseHTTPMiddleware):
    """Middleware to manage correlation IDs for request tracing."""

    EXCLUDED_PATHS = ["/docs", "/redoc", "/openapi.json", "/favicon.ico", "/metrics"]

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if request.url.path in self.EXCLUDED_PATHS:
            return await call_next(request)

        # Extract or generate correlation ID
        correlation_id = (
            request.headers.get("X-Request-ID")
            or request.headers.get("X-Correlation-ID")
            or str(uuid.uuid4())
        )

        set_correlation_id(correlation_id)

        start_time = time.time()

        try:
            response = await call_next(request)

            duration = time.time() - start_time

            response.headers["X-Request-ID"] = correlation_id
            response.headers["X-Correlation-ID"] = correlation_id

            # Log request
            logger.info(
                f"{request.method} {request.url.path} -> {response.status_code}",
                extra={
                    "type": "http_request",
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": response.status_code,
                    "duration_ms": round(duration * 1000, 2),
                },
            )

            return response

        except Exception as e:
            logger.error(
                f"Request failed: {request.method} {request.url.path}",
                extra={
                    "type": "http_error",
                    "method": request.method,
                    "path": request.url.path,
                    "error": str(e),
                },
                exc_info=True,
            )
            raise
        finally:
            clear_correlation_id()
