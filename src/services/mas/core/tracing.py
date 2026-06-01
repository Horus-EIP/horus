import os

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from core.config import settings


def init_tracing(app) -> bool:
    """Configure OTLP export and FastAPI instrumentation when OTEL_ENABLED=true."""
    if os.environ.get("OTEL_ENABLED", "").lower() != "true":
        return False

    resource = Resource.create(
        attributes={"service.name": "mas-service", "service.version": "1.0.0"}
    )

    tracer_provider = TracerProvider(resource=resource)

    otlp_endpoint = settings.otel_exporter_otlp_endpoint
    otlp_exporter = OTLPSpanExporter(endpoint=otlp_endpoint, insecure=True)

    span_processor = BatchSpanProcessor(otlp_exporter)
    tracer_provider.add_span_processor(span_processor)

    trace.set_tracer_provider(tracer_provider)

    FastAPIInstrumentor.instrument_app(app, tracer_provider=tracer_provider)
    return True
