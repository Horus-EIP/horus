import os
from unittest.mock import patch

from fastapi import FastAPI

from core.tracing import init_tracing


class TestTracing:
    @patch.dict(os.environ, {"OTEL_ENABLED": "true"}, clear=False)
    @patch("core.tracing.FastAPIInstrumentor")
    @patch("core.tracing.trace")
    @patch("core.tracing.BatchSpanProcessor")
    @patch("core.tracing.OTLPSpanExporter")
    @patch("core.tracing.TracerProvider")
    @patch("core.tracing.Resource")
    def test_init_tracing(
        self,
        mock_resource,
        mock_provider,
        mock_exporter,
        mock_processor,
        mock_trace,
        mock_instrumentor,
    ):
        # Setup
        app = FastAPI()

        # Execute
        assert init_tracing(app) is True

        # Verify
        mock_resource.create.assert_called_once()
        mock_provider.assert_called_once()
        mock_exporter.assert_called_once()
        mock_processor.assert_called_once()
        mock_trace.set_tracer_provider.assert_called_once()
        mock_instrumentor.instrument_app.assert_called_once()

        # Verify arguments
        call_args = mock_instrumentor.instrument_app.call_args
        assert call_args[0][0] == app
