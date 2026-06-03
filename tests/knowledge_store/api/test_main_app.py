"""Smoke + handler tests for the Knowledge Store ASGI app (``app.main``).

Importing ``app.main`` executes the module-level app wiring (metrics mount,
middleware, router mounting, system-info). The ``with TestClient(...)``
context drives the lifespan startup/shutdown. ChromaDB / spaCy / sentence-
transformers are mocked at the conftest level.
"""

from __future__ import annotations

import json

from fastapi import HTTPException
from fastapi.testclient import TestClient


class TestMainApp:
    def test_health_check_and_lifespan(self):
        from app.main import app  # noqa: PLC0415

        # Entering the context manager runs the lifespan startup; leaving it
        # runs shutdown — covering both log branches in lifespan().
        with TestClient(app) as client:
            r = client.get("/health")
            assert r.status_code == 200
            assert r.json() == {"status": "healthy", "service": "knowledge-store"}

    def test_http_exception_handler_shapes_body(self):
        from app.main import handle_http_exception  # noqa: PLC0415

        resp = handle_http_exception(None, HTTPException(status_code=404, detail="nope"))
        assert resp.status_code == 404
        assert json.loads(resp.body) == {"error": "nope"}
