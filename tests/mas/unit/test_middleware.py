"""Tests for MAS correlation-ID middleware."""

import json
import logging
from io import StringIO
from uuid import UUID

from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from fastapi.testclient import TestClient

from core.correlation_middleware import CorrelationIDMiddleware
from core.structured_logging import JSONFormatter, get_correlation_id, get_structured_logger


def _build_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(CorrelationIDMiddleware)

    @app.get("/ping")
    async def ping():
        return PlainTextResponse(get_correlation_id() or "")

    return app


class TestCorrelationIDMiddleware:
    def test_uses_correlation_id_header_in_response_and_request_log(self):
        stream = StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(JSONFormatter())
        logger = get_structured_logger("http")
        logger.addHandler(handler)
        try:
            response = TestClient(_build_app()).get(
                "/ping", headers={"X-Correlation-ID": "corr-112"}
            )
        finally:
            logger.removeHandler(handler)

        assert response.status_code == 200
        assert response.headers["X-Request-ID"] == "corr-112"
        assert response.headers["X-Correlation-ID"] == "corr-112"
        assert response.text == "corr-112"
        assert json.loads(stream.getvalue())["correlation_id"] == "corr-112"

    def test_generates_an_id_when_no_request_header_is_provided(self):
        response = TestClient(_build_app()).get("/ping")

        assert response.status_code == 200
        request_id = response.headers["X-Request-ID"]
        assert UUID(request_id)
        assert response.headers["X-Correlation-ID"] == request_id
        assert response.text == request_id

    def test_prefers_request_id_when_both_request_headers_are_provided(self):
        response = TestClient(_build_app()).get(
            "/ping",
            headers={
                "X-Request-ID": "request-112",
                "X-Correlation-ID": "correlation-112",
            },
        )

        assert response.headers["X-Request-ID"] == "request-112"
        assert response.headers["X-Correlation-ID"] == "request-112"
