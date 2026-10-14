"""FastAPI middleware that propagates a correlation ID per request.

Reads ``X-Request-ID``/``X-Correlation-ID`` (or mints one), binds it to a
contextvar, and echoes it on the response.
"""

import time
import uuid
from collections.abc import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from core.structured_logging import (
    clear_correlation_id,
    get_structured_logger,
    log_request,
    set_correlation_id,
)

logger = get_structured_logger("middleware")


class CorrelationIDMiddleware(BaseHTTPMiddleware):
    """
    Middleware to manage correlation IDs for request tracing.
    
    Features:
    - Extracts correlation ID from incoming request headers
    - Generates new correlation ID if not present
    - Stores correlation ID in context variable
    - Adds correlation ID to response headers
    - Logs all requests with structured JSON output
    """

    CORRELATION_ID_HEADERS = ["X-Request-ID", "X-Correlation-ID"]
    EXCLUDED_PATHS = ["/docs", "/redoc", "/openapi.json", "/favicon.ico", "/metrics"]

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Process request with correlation ID tracking."""
        # Skip excluded paths
        if request.url.path in self.EXCLUDED_PATHS:
            return await call_next(request)

        # Extract or generate correlation ID
        correlation_id = None
        for header in self.CORRELATION_ID_HEADERS:
            correlation_id = request.headers.get(header)
            if correlation_id:
                break

        if not correlation_id:
            correlation_id = str(uuid.uuid4())

        # Set correlation ID in context
        set_correlation_id(correlation_id)

        # Track request timing
        start_time = time.time()
        client_ip = request.client.host if request.client else "unknown"

        try:
            # Process request
            response = await call_next(request)

            # Calculate duration
            duration_ms = (time.time() - start_time) * 1000

            # Add correlation ID to response headers
            response.headers["X-Request-ID"] = correlation_id
            response.headers["X-Correlation-ID"] = correlation_id

            # Log request with structured fields
            log_request(
                method=request.method,
                path=request.url.path,
                status_code=response.status_code,
                duration_ms=duration_ms,
                client_ip=client_ip,
                query_params=str(request.query_params) if request.query_params else None,
            )

            return response

        except Exception as e:
            # Calculate duration even on error
            duration_ms = (time.time() - start_time) * 1000

            # Log error
            logger.error(
                f"Request failed: {request.method} {request.url.path}",
                extra={
                    "type": "http_error",
                    "method": request.method,
                    "path": request.url.path,
                    "duration_ms": round(duration_ms, 2),
                    "client_ip": client_ip,
                    "error": str(e),
                    "error_type": type(e).__name__,
                },
                exc_info=True
            )
            raise
        finally:
            # Clear correlation ID after request
            clear_correlation_id()
