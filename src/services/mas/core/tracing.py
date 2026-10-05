import os

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.sampling import Decision, ParentBased, Sampler, SamplingResult
from opentelemetry.trace import SpanKind

from core.config import settings
from core.version import HORUS_VERSION

DEFAULT_SERVICE_NAME = "mas"


class SkipRootClientSpans(Sampler):
    def should_sample(
        self,
        parent_context,
        trace_id,
        name,
        kind=None,
        attributes=None,
        links=None,
        trace_state=None,
    ):
        if kind == SpanKind.CLIENT:
            return SamplingResult(Decision.DROP)
        return SamplingResult(Decision.RECORD_AND_SAMPLE, attributes)

    def get_description(self) -> str:
        return "SkipRootClientSpans"


TRACE_SAMPLER = ParentBased(root=SkipRootClientSpans())


def service_name() -> str:
    return os.environ.get("OTEL_SERVICE_NAME", "").strip() or DEFAULT_SERVICE_NAME


def init_tracing(app) -> bool:
    """Configure OTLP export and FastAPI instrumentation when OTEL_ENABLED=true."""
    if os.environ.get("OTEL_ENABLED", "").lower() != "true":
        return False

    resource = Resource.create(
        attributes={"service.name": service_name(), "service.version": HORUS_VERSION}
    )

    tracer_provider = TracerProvider(resource=resource, sampler=TRACE_SAMPLER)

    otlp_endpoint = settings.otel_exporter_otlp_endpoint
    otlp_exporter = OTLPSpanExporter(endpoint=otlp_endpoint, insecure=True)

    span_processor = BatchSpanProcessor(otlp_exporter)
    tracer_provider.add_span_processor(span_processor)

    trace.set_tracer_provider(tracer_provider)

    if not FastAPIInstrumentor().is_instrumented_by_opentelemetry:
        FastAPIInstrumentor.instrument_app(app, tracer_provider=tracer_provider)
    return True
