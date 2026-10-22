"""
Metrics Middleware for FastAPI.

This middleware collects Prometheus metrics for all HTTP requests:
- Request count by method, endpoint, and status code
- Request latency histograms
- Requests currently in progress

Usage:
    from fastapi import FastAPI
    from core.metrics_middleware import MetricsMiddleware

    app = FastAPI()
    app.add_middleware(MetricsMiddleware)
"""

import time
from collections.abc import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from core.metrics import (
    increment_request_count,
    observe_request_latency,
    record_error,
    track_request_in_progress,
)
from core.structured_logging import get_structured_logger

logger = get_structured_logger("metrics_middleware")


class MetricsMiddleware(BaseHTTPMiddleware):
    """
    Middleware to collect Prometheus metrics for HTTP requests.
    """

    EXCLUDED_PATHS = ["/metrics", "/docs", "/redoc", "/openapi.json", "/favicon.ico"]

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Process request and collect metrics."""
        # Skip excluded paths
        if request.url.path in self.EXCLUDED_PATHS:
            return await call_next(request)

        # Normalize endpoint for metrics (avoid high cardinality)
        endpoint = self._normalize_endpoint(request.url.path)
        method = request.method

        # Track request in progress
        track_request_in_progress(method, endpoint, increment=True)

        start_time = time.time()
        status_code = 500  # Default to error if something goes wrong

        try:
            response = await call_next(request)
            status_code = response.status_code
            return response

        except Exception as e:
            # Record error
            record_error(error_type=type(e).__name__, component="http")
            raise

        finally:
            # Calculate duration
            duration = time.time() - start_time

            # Record metrics
            increment_request_count(method, endpoint, status_code)
            observe_request_latency(method, endpoint, duration)
            track_request_in_progress(method, endpoint, increment=False)

    def _normalize_endpoint(self, path: str) -> str:
        """
        Normalize endpoint path to avoid high cardinality metrics.

        Replaces dynamic path segments (IDs, UUIDs) with placeholders.
        """
        import re

        # Replace UUIDs
        path = re.sub(
            r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
            "{id}",
            path,
            flags=re.IGNORECASE,
        )

        # Replace numeric IDs
        path = re.sub(r"/\d+", "/{id}", path)

        # Remove trailing slashes for consistency
        path = path.rstrip("/")

        return path or "/"
