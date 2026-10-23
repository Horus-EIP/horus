from __future__ import annotations

import json
from pathlib import Path

from fastapi import HTTPException
from fastapi.testclient import TestClient

RELEASE_VERSION = (
    (Path(__file__).resolve().parents[3] / "VERSION").read_text(encoding="utf-8").strip()
)


class TestMainApp:
    def test_health_check_and_lifespan(self):
        from app.main import app  # noqa: PLC0415

        # Entering the context manager runs the lifespan startup; leaving it
        # runs shutdown — covering both log branches in lifespan().
        with TestClient(app) as client:
            r = client.get("/health")
            assert r.status_code == 200
            assert r.json() == {
                "status": "healthy",
                "service": "knowledge-store",
                "version": RELEASE_VERSION,
            }

    def test_mock_ai_mode_is_one_warning_at_start(self, monkeypatch, caplog):
        from app.main import app  # noqa: PLC0415

        for mode, warned in (("mock", 1), ("local", 0)):
            monkeypatch.setenv("HORUS_AI_MODE", mode)
            caplog.clear()
            with caplog.at_level("WARNING"), TestClient(app):
                pass
            warnings = [r for r in caplog.records if "Mock AI mode" in r.getMessage()]
            assert len(warnings) == warned, mode

    def test_the_mock_warning_says_what_is_faked_and_what_is_off(self, monkeypatch):
        import app.main as main  # noqa: PLC0415

        monkeypatch.setattr(main, "EMBED_URL", "http://llm-mock:8080/v1")
        monkeypatch.setenv("HORUS_SPACY", "off")
        monkeypatch.setenv("OTEL_SDK_DISABLED", "true")
        text = main.mock_ai_warning()
        assert text.startswith("Mock AI mode: the answers built on this knowledge store")
        assert "search is word matching" in text
        assert "spaCy is off" in text
        assert "exports no trace" in text
        monkeypatch.setattr(main, "EMBED_URL", "")
        monkeypatch.delenv("HORUS_SPACY")
        monkeypatch.delenv("OTEL_SDK_DISABLED")
        assert main.mock_ai_warning() == (
            "Mock AI mode: the answers built on this knowledge store are simulated by llm-mock"
        )

    def test_openapi_reports_the_release_version(self):
        from app.main import app  # noqa: PLC0415

        assert app.version == RELEASE_VERSION

    def test_http_exception_handler_shapes_body(self):
        from app.main import handle_http_exception  # noqa: PLC0415

        resp = handle_http_exception(None, HTTPException(status_code=404, detail="nope"))
        assert resp.status_code == 404
        assert json.loads(resp.body) == {"error": "nope"}
