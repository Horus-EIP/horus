import unittest
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import Request, Response

from core.middleware import LoggingMiddleware


class TestLoggingMiddleware:

    @pytest.mark.asyncio
    async def test_dispatch_success(self):
        app = MagicMock()

        request = MagicMock(spec=Request)
        request.url.path = "/api/test"
        request.method = "GET"
        request.client.host = "127.0.0.1"
        request.headers = {"user-agent": "test-agent"}

        async def call_next(req):
            return Response(status_code=200)

        with patch("core.middleware.get_logger") as mock_get_logger, patch(
            "core.middleware.structlog.contextvars"
        ) as mock_contextvars, patch(
            "core.middleware.log_api_request"
        ) as mock_log_api, patch(
            "core.middleware.log_system_performance"
        ) as mock_log_perf:

            mock_logger = MagicMock()
            mock_get_logger.return_value = mock_logger

            middleware = LoggingMiddleware(app)

            response = await middleware.dispatch(request, call_next)

            # Verify context binding
            mock_contextvars.bind_contextvars.assert_called_once()
            call_args = mock_contextvars.bind_contextvars.call_args[1]
            assert "correlation_id" in call_args

            # Verify logging
            mock_logger.info.assert_called_with(
                "Request started",
                method="GET",
                path="/api/test",
                ip="127.0.0.1",
                user_agent="test-agent",
            )

            mock_log_api.assert_called_once()
            mock_log_perf.assert_called_once()

            # Verify context clearing
            mock_contextvars.clear_contextvars.assert_called_once()

            # Verify response header
            assert "X-Request-ID" in response.headers

    @pytest.mark.asyncio
    async def test_dispatch_excluded_path(self):
        app = MagicMock()

        request = MagicMock(spec=Request)
        request.url.path = "/docs"

        async def call_next(req):
            return Response(status_code=200)

        with patch("core.middleware.get_logger") as mock_get_logger:
            middleware = LoggingMiddleware(app)
            await middleware.dispatch(request, call_next)
            mock_get_logger.assert_called_once()  # __init__ calls get_logger
            # dispatch shouldn't call logger for excluded path
            mock_get_logger.return_value.info.assert_not_called()

    @pytest.mark.asyncio
    async def test_dispatch_exception(self):
        app = MagicMock()

        request = MagicMock(spec=Request)
        request.url.path = "/api/error"
        request.method = "GET"
        request.client.host = "127.0.0.1"
        request.headers = {}

        async def call_next(req):
            raise ValueError("Test error")

        with patch("core.middleware.get_logger") as mock_get_logger, patch(
            "core.middleware.structlog.contextvars"
        ) as mock_contextvars:

            mock_logger = MagicMock()
            mock_get_logger.return_value = mock_logger

            middleware = LoggingMiddleware(app)

            with pytest.raises(ValueError):
                await middleware.dispatch(request, call_next)

            mock_logger.error.assert_called_with(
                "Request failed",
                method="GET",
                path="/api/error",
                error="Test error",
                duration=unittest.mock.ANY,
                exc_info=True,
            )

            mock_contextvars.clear_contextvars.assert_called_once()
