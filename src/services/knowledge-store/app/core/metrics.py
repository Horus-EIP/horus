"""
Prometheus Metrics for Knowledge Store.

Collects metrics for:
- Document operations (add, delete, get)
- Query operations and latency
- Embedding generation time
- Collection statistics
"""

from prometheus_client import Counter, Histogram, Gauge, Info

# =============================================================================
# Document Metrics
# =============================================================================

DOCUMENT_OPERATIONS = Counter(
    "knowledge_store_document_operations_total",
    "Total number of document operations",
    ["operation", "status"]  # operation: add, delete, get; status: success, error
)

DOCUMENT_COUNT = Gauge(
    "knowledge_store_documents_total",
    "Total number of documents in the store"
)

# =============================================================================
# Query Metrics
# =============================================================================

QUERY_COUNT = Counter(
    "knowledge_store_queries_total",
    "Total number of queries",
    ["status"]  # success, error
)

QUERY_LATENCY = Histogram(
    "knowledge_store_query_duration_seconds",
    "Query latency in seconds",
    buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0]
)

QUERY_RESULTS = Histogram(
    "knowledge_store_query_results_count",
    "Number of results returned by queries",
    buckets=[0, 1, 2, 5, 10, 20, 50, 100]
)

# =============================================================================
# Embedding Metrics
# =============================================================================

EMBEDDING_TIME = Histogram(
    "knowledge_store_embedding_duration_seconds",
    "Time to generate embeddings",
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0]
)

EMBEDDING_COUNT = Counter(
    "knowledge_store_embeddings_total",
    "Total number of embeddings generated",
    ["status"]
)

# =============================================================================
# System Info
# =============================================================================

SYSTEM_INFO = Info(
    "knowledge_store_system",
    "Knowledge Store system information"
)

# =============================================================================
# Helper Functions
# =============================================================================


def record_document_operation(operation: str, success: bool):
    """Record a document operation."""
    DOCUMENT_OPERATIONS.labels(
        operation=operation,
        status="success" if success else "error"
    ).inc()


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


def set_system_info(version: str, embedding_model: str):
    """Set system information."""
    SYSTEM_INFO.info({
        "version": version,
        "embedding_model": embedding_model
    })
