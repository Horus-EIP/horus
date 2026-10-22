"""FastAPI middleware for correlation-ID propagation.

Reads ``X-Request-ID``/``X-Correlation-ID`` (or mints one), binds it to
the structured-logging contextvar, and echoes it on the response.
"""

import uuid

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from core.logger import get_correlation_id, set_correlation_id


class CorrelationIDMiddleware(BaseHTTPMiddleware):
    """Propagate a correlation ID across the request lifecycle."""

    async def dispatch(self, request: Request, call_next):
        corr_id = request.headers.get("X-Request-ID") or request.headers.get("X-Correlation-ID")
        if corr_id:
            set_correlation_id(corr_id)
        else:
            set_correlation_id(str(uuid.uuid4()))

        response = await call_next(request)

        if corr_id := get_correlation_id():
            response.headers["X-Request-ID"] = corr_id

        return response
