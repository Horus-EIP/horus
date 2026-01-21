"""
OpenTelemetry Distributed Tracing Module for MAS.

This module provides distributed tracing capabilities using OpenTelemetry:
- Automatic instrumentation of FastAPI routes
- Manual span creation for custom tracing
- Trace context propagation to downstream services
- OTLP export for trace visualization (SigNoz, Jaeger, etc.)

Usage:
    from core.tracing import setup_tracing, create_span, get_tracer
    
    # Setup tracing at application startup
    setup_tracing(app, service_name="mas")
    
    # Create custom spans
    with create_span("process_task") as span:
        span.set_attribute("task_id", task_id)
        # ... processing logic ...

Environment Variables:
    OTEL_ENABLED: Enable/disable tracing (default: true)
    OTEL_EXPORTER_OTLP_ENDPOINT: OTLP collector endpoint (e.g., http://otel-collector:4317)
    OTEL_SERVICE_NAME: Service name for traces (default: mas)
"""

import os
from contextlib import contextmanager
from typing import Any, Dict, Optional

from fastapi import FastAPI

# Check if OpenTelemetry is available
OTEL_AVAILABLE = False
JAEGER_AVAILABLE = False
trace = None
Span = None

try:
    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.instrumentation.logging import LoggingInstrumentor
    from opentelemetry.instrumentation.requests import RequestsInstrumentor
    from opentelemetry.propagate import set_global_textmap
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
    from opentelemetry.trace import Status, StatusCode, Span
    from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
    
    OTEL_AVAILABLE = True
except ImportError:
    pass

# Optional Jaeger exporter (not required when using SigNoz/OTLP)
try:
    from opentelemetry.exporter.jaeger.thrift import JaegerExporter
    JAEGER_AVAILABLE = True
except ImportError:
    JaegerExporter = None
    JAEGER_AVAILABLE = False

from core.structured_logging import get_structured_logger

logger = get_structured_logger("tracing")

# Global tracer instance
_tracer = None


def setup_tracing(
    app: FastAPI,
    service_name: str = None,
    jaeger_endpoint: str = None,
    otlp_endpoint: str = None,
) -> bool:
    """
    Setup OpenTelemetry tracing for the FastAPI application.
    
    Args:
        app: FastAPI application instance
        service_name: Name of the service for traces
        jaeger_endpoint: Jaeger collector endpoint (e.g., http://jaeger:14268/api/traces)
        otlp_endpoint: OTLP exporter endpoint (alternative to Jaeger)
    
    Returns:
        True if tracing was successfully configured, False otherwise
    """
    global _tracer
    
    if not OTEL_AVAILABLE:
        logger.warning("OpenTelemetry not available. Install with: pip install opentelemetry-api opentelemetry-sdk opentelemetry-instrumentation-fastapi opentelemetry-exporter-jaeger")
        return False
    
    # Check if tracing is enabled
    otel_enabled = os.getenv("OTEL_ENABLED", "true").lower() == "true"
    if not otel_enabled:
        logger.info("OpenTelemetry tracing is disabled")
        return False
    
    # Get configuration from environment
    service_name = service_name or os.getenv("OTEL_SERVICE_NAME", "mas")
    jaeger_endpoint = jaeger_endpoint or os.getenv("OTEL_EXPORTER_JAEGER_ENDPOINT", "http://jaeger:14268/api/traces")
    otlp_endpoint = otlp_endpoint or os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    
    try:
        # Create resource with service information
        resource = Resource.create({
            "service.name": service_name,
            "service.version": os.getenv("SERVICE_VERSION", "1.0.0"),
            "deployment.environment": os.getenv("ENVIRONMENT", "development"),
        })
        
        # Create tracer provider
        provider = TracerProvider(resource=resource)
        
        # Configure exporters
        if otlp_endpoint:
            # Use OTLP exporter (preferred - works with SigNoz, Jaeger, etc.)
            exporter = OTLPSpanExporter(endpoint=otlp_endpoint)
            provider.add_span_processor(BatchSpanProcessor(exporter))
            logger.info(f"OTLP exporter configured: {otlp_endpoint}")
        elif jaeger_endpoint and JAEGER_AVAILABLE:
            # Use Jaeger exporter (fallback if OTLP not configured)
            exporter = JaegerExporter(
                collector_endpoint=jaeger_endpoint,
            )
            provider.add_span_processor(BatchSpanProcessor(exporter))
            logger.info(f"Jaeger exporter configured: {jaeger_endpoint}")
        elif jaeger_endpoint and not JAEGER_AVAILABLE:
            logger.warning("Jaeger endpoint configured but jaeger exporter not installed. Install with: pip install opentelemetry-exporter-jaeger")
        
        # Also add console exporter for debugging in development
        if os.getenv("OTEL_CONSOLE_EXPORT", "false").lower() == "true":
            provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
            logger.info("Console span exporter enabled")
        
        # Set the tracer provider
        trace.set_tracer_provider(provider)
        
        # Set up propagators for distributed tracing
        set_global_textmap(TraceContextTextMapPropagator())
        
        # Instrument FastAPI
        FastAPIInstrumentor.instrument_app(app)
        logger.info("FastAPI instrumentation enabled")
        
        # Instrument requests library for outgoing HTTP calls
        try:
            RequestsInstrumentor().instrument()
            logger.info("Requests library instrumentation enabled")
        except Exception as e:
            logger.warning(f"Failed to instrument requests library: {e}")
        
        # Instrument logging to include trace context
        try:
            LoggingInstrumentor().instrument()
            logger.info("Logging instrumentation enabled")
        except Exception as e:
            logger.warning(f"Failed to instrument logging: {e}")
        
        # Store global tracer
        _tracer = trace.get_tracer(service_name)
        
        logger.info(f"OpenTelemetry tracing configured for service: {service_name}")
        return True
        
    except Exception as e:
        logger.error(f"Failed to configure OpenTelemetry tracing: {e}", exc_info=True)
        return False


def get_tracer(name: str = None):
    """
    Get a tracer instance.
    
    Args:
        name: Optional tracer name (defaults to global tracer)
    
    Returns:
        Tracer instance or NoOpTracer if tracing is not available
    """
    if not OTEL_AVAILABLE:
        return None
    
    if name:
        return trace.get_tracer(name)
    return _tracer or trace.get_tracer("mas")


@contextmanager
def create_span(
    name: str,
    attributes: Dict[str, Any] = None,
    kind=None,
):
    """
    Create a new span for tracing.
    
    Args:
        name: Span name
        attributes: Optional attributes to add to the span
        kind: Span kind (SpanKind.INTERNAL, SpanKind.CLIENT, SpanKind.SERVER, etc.)
    
    Yields:
        Span instance
    
    Example:
        with create_span("process_task", {"task_id": "123"}) as span:
            # ... do work ...
            span.set_attribute("result", "success")
    """
    if not OTEL_AVAILABLE or not _tracer:
        # No-op context manager when tracing is not available
        class NoOpSpan:
            def set_attribute(self, key, value): pass
            def set_status(self, status): pass
            def record_exception(self, exception): pass
            def add_event(self, name, attributes=None): pass
        
        yield NoOpSpan()
        return
    
    kwargs = {}
    if kind:
        kwargs["kind"] = kind
    
    with _tracer.start_as_current_span(name, **kwargs) as span:
        if attributes:
            for key, value in attributes.items():
                span.set_attribute(key, value)
        try:
            yield span
        except Exception as e:
            span.set_status(Status(StatusCode.ERROR, str(e)))
            span.record_exception(e)
            raise


def add_span_attributes(**attributes):
    """
    Add attributes to the current span.
    
    Args:
        **attributes: Key-value pairs to add as span attributes
    """
    if not OTEL_AVAILABLE:
        return
    
    span = trace.get_current_span()
    if span:
        for key, value in attributes.items():
            span.set_attribute(key, value)


def record_exception(exception: Exception, attributes: Dict[str, Any] = None):
    """
    Record an exception on the current span.
    
    Args:
        exception: The exception to record
        attributes: Optional additional attributes
    """
    if not OTEL_AVAILABLE:
        return
    
    span = trace.get_current_span()
    if span:
        span.record_exception(exception, attributes=attributes)
        span.set_status(Status(StatusCode.ERROR, str(exception)))


def add_span_event(name: str, attributes: Dict[str, Any] = None):
    """
    Add an event to the current span.
    
    Args:
        name: Event name
        attributes: Optional event attributes
    """
    if not OTEL_AVAILABLE:
        return
    
    span = trace.get_current_span()
    if span:
        span.add_event(name, attributes=attributes)


def get_trace_context() -> Dict[str, str]:
    """
    Get the current trace context for propagation.
    
    Returns:
        Dictionary with trace context headers
    """
    if not OTEL_AVAILABLE:
        return {}
    
    from opentelemetry.propagate import inject
    
    carrier = {}
    inject(carrier)
    return carrier


def inject_trace_context(headers: Dict[str, str]) -> Dict[str, str]:
    """
    Inject trace context into headers for outgoing requests.
    
    Args:
        headers: Existing headers dictionary
    
    Returns:
        Headers with trace context added
    """
    if not OTEL_AVAILABLE:
        return headers
    
    from opentelemetry.propagate import inject
    
    inject(headers)
    return headers
