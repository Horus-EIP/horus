import os
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind

from core import tracing
from core.rabbitmq_manager import RabbitMQ
from core.version import HORUS_VERSION
from tasks import decomposition, router


def run_init_tracing(app, env, auto_instrumented=False):
    instrumentor = MagicMock()
    instrumentor.return_value.is_instrumented_by_opentelemetry = auto_instrumented
    with (
        patch.dict(os.environ, {"OTEL_ENABLED": "true"}),
        patch("core.tracing.OTLPSpanExporter") as exporter,
        patch("core.tracing.FastAPIInstrumentor", instrumentor),
        patch.object(trace, "set_tracer_provider") as set_tracer_provider,
    ):
        for name, value in env.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        enabled = tracing.init_tracing(app)
    provider = set_tracer_provider.call_args.args[0] if set_tracer_provider.called else None
    if provider is not None:
        provider.shutdown()
    return enabled, provider, instrumentor, exporter


def recording_provider(**kwargs):
    exporter = InMemorySpanExporter()
    with patch.dict(os.environ, {"OTEL_SDK_DISABLED": "false"}):
        provider = TracerProvider(**kwargs)
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return provider, exporter


@pytest.fixture(scope="module")
def global_exporter():
    provider = trace.get_tracer_provider()
    if not isinstance(provider, TracerProvider):
        with patch.dict(os.environ, {"OTEL_SDK_DISABLED": "false"}):
            provider = TracerProvider()
        trace.set_tracer_provider(provider)
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return exporter


@pytest.fixture
def exported_spans(global_exporter):
    global_exporter.clear()
    return global_exporter


def span_names(exporter):
    return [span.name for span in exporter.get_finished_spans()]


class TestInitTracing:
    def test_service_name_comes_from_otel_service_name(self):
        _, provider, _, _ = run_init_tracing(FastAPI(), {"OTEL_SERVICE_NAME": "mas-staging"})

        assert provider.resource.attributes["service.name"] == "mas-staging"

    def test_service_name_defaults_to_mas(self):
        _, provider, _, _ = run_init_tracing(FastAPI(), {"OTEL_SERVICE_NAME": None})

        assert provider.resource.attributes["service.name"] == "mas"

    def test_reports_the_release_version(self):
        _, provider, _, _ = run_init_tracing(FastAPI(), {})

        assert provider.resource.attributes["service.version"] == HORUS_VERSION

    def test_exports_spans_over_otlp(self):
        enabled, provider, _, exporter = run_init_tracing(FastAPI(), {})

        assert enabled is True
        exporter.assert_called_once()
        assert exporter.call_args.kwargs["insecure"] is True
        assert provider.sampler is tracing.TRACE_SAMPLER

    def test_does_nothing_unless_otel_is_enabled(self):
        with (
            patch.dict(os.environ, {"OTEL_ENABLED": "false"}),
            patch.object(trace, "set_tracer_provider") as set_tracer_provider,
        ):
            assert tracing.init_tracing(FastAPI()) is False

        set_tracer_provider.assert_not_called()

    def test_instruments_the_app_when_nothing_else_does(self):
        app = FastAPI()

        _, provider, instrumentor, _ = run_init_tracing(app, {})

        instrumentor.instrument_app.assert_called_once_with(app, tracer_provider=provider)

    def test_leaves_the_app_to_opentelemetry_instrument_when_it_is_active(self):
        enabled, provider, instrumentor, _ = run_init_tracing(
            FastAPI(), {}, auto_instrumented=True
        )

        assert enabled is True
        assert provider is not None
        instrumentor.instrument_app.assert_not_called()


class TestRootSampling:
    def test_a_client_span_outside_any_request_is_not_exported(self):
        provider, exporter = recording_provider(sampler=tracing.TRACE_SAMPLER)
        tracer = provider.get_tracer("test")

        with tracer.start_as_current_span("SELECT horus", kind=SpanKind.CLIENT):
            pass

        assert exporter.get_finished_spans() == ()

    def test_a_request_and_the_client_calls_it_makes_are_exported(self):
        provider, exporter = recording_provider(sampler=tracing.TRACE_SAMPLER)
        tracer = provider.get_tracer("test")

        with tracer.start_as_current_span("POST /tasks/new_task/", kind=SpanKind.SERVER):
            with tracer.start_as_current_span("SELECT horus", kind=SpanKind.CLIENT):
                pass

        assert span_names(exporter) == ["SELECT horus", "POST /tasks/new_task/"]

    def test_internal_and_consumer_roots_are_exported(self):
        provider, exporter = recording_provider(sampler=tracing.TRACE_SAMPLER)
        tracer = provider.get_tracer("test")

        with tracer.start_as_current_span("route_task", kind=SpanKind.INTERNAL):
            pass
        with tracer.start_as_current_span("horus.work.general process", kind=SpanKind.CONSUMER):
            pass

        assert span_names(exporter) == ["route_task", "horus.work.general process"]


class TestPipelineSpans:
    def test_routing_runs_inside_a_route_task_span(self, exported_spans):
        with patch.object(router, "available_roster", return_value=[]):
            router.route_task("What is our hotel limit?", MagicMock())

        assert span_names(exported_spans) == ["route_task"]

    def test_the_full_llm_router_runs_inside_a_route_task_llm_span(self, exported_spans):
        with patch("tasks.decomposition.get_available_agents", return_value=[]):
            decomposition.select_agent_for_task("What is our hotel limit?", MagicMock())

        assert span_names(exported_spans) == ["route_task_llm"]

    def test_decomposition_runs_inside_a_decompose_task_span(self, exported_spans):
        with patch("tasks.decomposition.get_available_agents", return_value=[]):
            decomposition.decompose_task("Compare Q1 and Q2", MagicMock())

        assert span_names(exported_spans) == ["decompose_task"]

    def test_aggregation_runs_inside_an_aggregate_results_span(self, exported_spans):
        with patch("tasks.decomposition.ask_llm", return_value="final answer"):
            assert decomposition.aggregate_results([], "partial") == "final answer"

        assert span_names(exported_spans) == ["aggregate_results"]

    def test_manager_llm_calls_run_inside_their_own_spans(self, exported_spans):
        db = MagicMock()
        with (
            patch("tasks.decomposition._planned_steps_from_actions", return_value=[]),
            patch("tasks.decomposition.ask_llm", return_value='{"decision": "DONE"}'),
        ):
            decomposition.manager_announce_plan("demand", [], db)
            decomposition.manager_review_step("demand", "transcript", [], [], db)

        assert span_names(exported_spans) == ["announce_plan", "review_step"]

    def test_publishing_runs_inside_a_producer_span_that_the_agent_continues(
        self, exported_spans
    ):
        channel = MagicMock()
        connection = MagicMock()
        connection.channel.return_value = channel
        rabbitmq = RabbitMQ(retries=1, delay=0.1)
        with patch("core.rabbitmq_manager.pika.BlockingConnection", return_value=connection):
            rabbitmq.connect()
            rabbitmq.publish("horus.work.general", '{"task_id": "t1"}')

        (span,) = exported_spans.get_finished_spans()
        assert span.name == "publish horus.work.general"
        assert span.kind == SpanKind.PRODUCER
        assert span.attributes["messaging.system"] == "rabbitmq"
        assert span.attributes["messaging.destination.name"] == "horus.work.general"
        headers = channel.basic_publish.call_args.kwargs["properties"].headers
        assert format(span.context.span_id, "016x") in headers["traceparent"]
