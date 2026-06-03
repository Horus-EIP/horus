"""Unit tests for ``CorrelationIDMiddleware`` (``app.core.middleware``).

Mounts the middleware on a throwaway FastAPI app and drives every branch:
generated id, caller-supplied id, an excluded path, and an exception.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.middleware import CorrelationIDMiddleware


def _make_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(CorrelationIDMiddleware)

    @app.get("/ok")
    async def ok():
        return {"ok": True}

    @app.get("/boom")
    async def boom():
        raise RuntimeError("kaboom")

    return app


class TestCorrelationIDMiddleware:
    def test_generates_correlation_id_when_absent(self):
        client = TestClient(_make_app())
        r = client.get("/ok")
        assert r.status_code == 200
        assert r.headers.get("X-Request-ID")
        assert r.headers["X-Request-ID"] == r.headers["X-Correlation-ID"]

    def test_propagates_caller_supplied_request_id(self):
        client = TestClient(_make_app())
        r = client.get("/ok", headers={"X-Request-ID": "fixed-id-123"})
        assert r.headers["X-Request-ID"] == "fixed-id-123"
        assert r.headers["X-Correlation-ID"] == "fixed-id-123"

    def test_excluded_path_skips_correlation_headers(self):
        # /metrics is in EXCLUDED_PATHS, so the middleware returns early and
        # never attaches the correlation headers. (The route 404s on this
        # bare app, which is fine — we only care about the header behaviour.)
        client = TestClient(_make_app())
        r = client.get("/metrics")
        assert "X-Request-ID" not in r.headers

    def test_exception_path_is_logged_and_reraised(self):
        client = TestClient(_make_app(), raise_server_exceptions=False)
        r = client.get("/boom")
        assert r.status_code == 500
