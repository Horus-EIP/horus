"""
OpenTelemetry Tracing for Agent Service.

Provides distributed tracing to SigNoz for request flow visualization.
"""

import os
from typing import Optional

# Check if OpenTelemetry is available
OTEL_AVAILABLE = False

try:
    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.instrumentation.requests import RequestsInstrumentor
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
    from opentelemetry.propagate import set_global_textmap
    
    OTEL_AVAILABLE = True
except ImportError:
    trace = None


def setup_tracing(app, service_name: str = "agent") -> bool:
    """
    Setup OpenTelemetry tracing for the Agent FastAPI application.
    
    Args:
        app: FastAPI application instance
        service_name: Name of the service for traces
    
    Returns:
        True if tracing was configured, False otherwise
    """
    if not OTEL_AVAILABLE:
        print("OpenTelemetry not available. Install with: pip install opentelemetry-api opentelemetry-sdk opentelemetry-instrumentation-fastapi opentelemetry-exporter-otlp-proto-grpc")
        return False
    
    # Check if tracing is enabled
    otel_enabled = os.getenv("OTEL_ENABLED", "false").lower() == "true"
    if not otel_enabled:
        print("OpenTelemetry tracing is disabled (OTEL_ENABLED != true)")
        return False
    
    # Get configuration from environment
    service_name = os.getenv("OTEL_SERVICE_NAME", service_name)
    otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://signoz-otel-collector:4317")
    
    try:
        # Create resource with service information
        resource = Resource.create({
            "service.name": service_name,
            "service.version": "1.0.0",
            "deployment.environment": os.getenv("ENVIRONMENT", "development"),
        })
        
        # Create tracer provider
        provider = TracerProvider(resource=resource)
        
        # Configure OTLP exporter
        exporter = OTLPSpanExporter(endpoint=otlp_endpoint, insecure=True)
        provider.add_span_processor(BatchSpanProcessor(exporter))
        
        # Set the tracer provider
        trace.set_tracer_provider(provider)
        
        # Set up W3C Trace Context propagator
        set_global_textmap(TraceContextTextMapPropagator())
        
        # Instrument FastAPI
        FastAPIInstrumentor.instrument_app(app)
        
        # Instrument requests library for outgoing HTTP calls
        try:
            RequestsInstrumentor().instrument()
        except Exception as e:
            print(f"Failed to instrument requests library: {e}")
        
        print(f"OpenTelemetry tracing configured for service: {service_name} -> {otlp_endpoint}")
        return True
        
    except Exception as e:
        print(f"Failed to configure OpenTelemetry tracing: {e}")
        return False


def get_tracer(name: str = "agent"):
    """Get a tracer instance."""
    if not OTEL_AVAILABLE:
        return None
    return trace.get_tracer(name)
