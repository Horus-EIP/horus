"""Prometheus metrics for document operations, query latency, embeddings, and collection stats."""

import functools
import time

from prometheus_client import Counter, Gauge, Histogram, Info

LONG_RUNNING_TAIL_BUCKETS = (10.0, 30.0, 60.0, 120.0, 300.0, 600.0, 900.0, 1200.0, 1800.0)

# --- Document metrics ---
DOCUMENT_OPERATIONS = Counter(
    "knowledge_store_document_operations_total",
    "Total number of document operations",
    ["operation", "status"],  # operation: add, delete, get; status: success, error
)

DOCUMENT_COUNT = Gauge("knowledge_store_documents_total", "Total number of documents in the store")

# --- Query metrics ---
QUERY_COUNT = Counter(
    "knowledge_store_queries_total",
    "Total number of queries",
    ["status"],  # success, error
)

QUERY_LATENCY = Histogram(
    "knowledge_store_query_duration_seconds",
    "Query latency in seconds",
    buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, *LONG_RUNNING_TAIL_BUCKETS],
)

QUERY_RESULTS = Histogram(
    "knowledge_store_query_results_count",
    "Number of results returned by queries",
    buckets=[0, 1, 2, 5, 10, 20, 50, 100],
)

# --- Embedding metrics ---
EMBEDDING_TIME = Histogram(
    "knowledge_store_embedding_duration_seconds",
    "Time to generate embeddings",
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, *LONG_RUNNING_TAIL_BUCKETS],
)

EMBEDDING_COUNT = Counter(
    "knowledge_store_embeddings_total", "Total number of embeddings generated", ["status"]
)

# --- System info ---
SYSTEM_INFO = Info("knowledge_store_system", "Knowledge Store system information")

# --- Helpers ---


def record_document_operation(operation: str, success: bool):
    """Record a document operation."""
    DOCUMENT_OPERATIONS.labels(operation=operation, status="success" if success else "error").inc()


def set_document_count(count: int):
    """Set the total document count."""
    DOCUMENT_COUNT.set(count)


def record_query(success: bool, duration: float, results_count: int):
    """Record a query operation."""
    QUERY_COUNT.labels(status="success" if success else "error").inc()
    QUERY_LATENCY.observe(duration)
    QUERY_RESULTS.observe(results_count)


def record_embedding(success: bool, duration: float):
    """Record embedding generation."""
    EMBEDDING_COUNT.labels(status="success" if success else "error").inc()
    EMBEDDING_TIME.observe(duration)


def _returned_count(results) -> int:
    try:
        return len(results["ids"][0])
    except (KeyError, IndexError, TypeError):
        return 0


def timed_query(query):
    @functools.wraps(query)
    async def timed(*args, **kwargs):
        started = time.perf_counter()
        try:
            results = await query(*args, **kwargs)
        except Exception:
            record_query(False, time.perf_counter() - started, 0)
            raise
        record_query(True, time.perf_counter() - started, _returned_count(results))
        return results

    return timed


def timed_embedding(embed):
    @functools.wraps(embed)
    def timed(*args, **kwargs):
        started = time.perf_counter()
        try:
            embedding = embed(*args, **kwargs)
        except Exception:
            record_embedding(False, time.perf_counter() - started)
            raise
        record_embedding(True, time.perf_counter() - started)
        return embedding

    return timed


def set_system_info(version: str, embedding_model: str):
    """Set system information."""
    SYSTEM_INFO.info({"version": version, "embedding_model": embedding_model})
