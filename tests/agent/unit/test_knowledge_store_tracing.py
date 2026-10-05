import os
from unittest.mock import patch

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

import ai_agents.knowledge_store_client as ksc
from ai_agents.knowledge_store_client import KnowledgeStoreClient


class StoreResponse:
    status_code = 200

    def raise_for_status(self):
        return None

    def json(self):
        return {"documents": [["Hotels: $250/night (US)"]]}


class StoreClient:
    def __init__(self, **_kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False

    async def get(self, _url, params=None):
        return StoreResponse()


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
def exported_spans(global_exporter, monkeypatch):
    monkeypatch.setattr(ksc.httpx, "AsyncClient", StoreClient)
    global_exporter.clear()
    return global_exporter


async def test_rag_retrieval_runs_inside_knowledge_store_spans(exported_spans):
    client = KnowledgeStoreClient(base_url="http://ks.test", api_prefix="", max_retries=1)

    result = await client.fetch_for_rag("What is the hotel limit in the US?")

    assert result["data"] == "Hotels: $250/night (US)"
    spans = {span.name: span for span in exported_spans.get_finished_spans()}
    assert set(spans) == {"knowledge_store_fetch_for_rag", "knowledge_store_query"}
    retrieval = spans["knowledge_store_fetch_for_rag"]
    assert spans["knowledge_store_query"].parent.span_id == retrieval.context.span_id
