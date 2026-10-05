"""Unit tests for Prometheus metric helpers (``app.core.metrics``).

Assertions are written as *relative* deltas against the global default
registry so they are robust to ordering and to other tests (or the app
itself) touching the same counters.
"""

from __future__ import annotations

from prometheus_client import REGISTRY

from app.core import metrics


def _sample(name: str, labels: dict | None = None) -> float:
    return REGISTRY.get_sample_value(name, labels or {}) or 0.0


class TestMetricHelpers:
    def test_record_document_operation_success_then_error(self):
        ok_before = _sample(
            "knowledge_store_document_operations_total",
            {"operation": "add", "status": "success"},
        )
        metrics.record_document_operation("add", True)
        assert (
            _sample(
                "knowledge_store_document_operations_total",
                {"operation": "add", "status": "success"},
            )
            == ok_before + 1
        )

        err_before = _sample(
            "knowledge_store_document_operations_total",
            {"operation": "delete", "status": "error"},
        )
        metrics.record_document_operation("delete", False)
        assert (
            _sample(
                "knowledge_store_document_operations_total",
                {"operation": "delete", "status": "error"},
            )
            == err_before + 1
        )

    def test_set_document_count(self):
        metrics.set_document_count(7)
        assert _sample("knowledge_store_documents_total") == 7.0

    def test_record_query_success_and_error(self):
        ok_before = _sample("knowledge_store_queries_total", {"status": "success"})
        err_before = _sample("knowledge_store_queries_total", {"status": "error"})
        count_before = _sample("knowledge_store_query_duration_seconds_count")

        metrics.record_query(True, 0.12, 5)
        metrics.record_query(False, 0.34, 0)

        assert _sample("knowledge_store_queries_total", {"status": "success"}) == ok_before + 1
        assert _sample("knowledge_store_queries_total", {"status": "error"}) == err_before + 1
        assert _sample("knowledge_store_query_duration_seconds_count") == count_before + 2

    def test_record_embedding_success_and_error(self):
        ok_before = _sample("knowledge_store_embeddings_total", {"status": "success"})
        err_before = _sample("knowledge_store_embeddings_total", {"status": "error"})

        metrics.record_embedding(True, 0.05)
        metrics.record_embedding(False, 0.06)

        assert _sample("knowledge_store_embeddings_total", {"status": "success"}) == ok_before + 1
        assert _sample("knowledge_store_embeddings_total", {"status": "error"}) == err_before + 1

    def test_set_system_info(self):
        metrics.set_system_info(version="9.9.9", embedding_model="test-model")
        assert (
            _sample(
                "knowledge_store_system_info",
                {"version": "9.9.9", "embedding_model": "test-model"},
            )
            == 1.0
        )


class TestLatencyBuckets:
    def test_query_and_embedding_buckets_reach_thirty_minutes(self):
        for name in (
            "knowledge_store_query_duration_seconds_bucket",
            "knowledge_store_embedding_duration_seconds_bucket",
        ):
            assert REGISTRY.get_sample_value(name, {"le": "1800.0"}) is not None, name

    def test_sub_second_resolution_is_kept(self):
        assert REGISTRY.get_sample_value(
            "knowledge_store_query_duration_seconds_bucket", {"le": "0.01"}
        ) is not None

    def test_a_query_stuck_behind_a_cpu_corpus_scan_lands_in_a_finite_bucket(self):
        bucket = "knowledge_store_query_duration_seconds_bucket"
        under_five_minutes = _sample(bucket, {"le": "300.0"})
        under_ten_minutes = _sample(bucket, {"le": "600.0"})

        metrics.record_query(True, 420.0, 4)

        assert _sample(bucket, {"le": "300.0"}) == under_five_minutes
        assert _sample(bucket, {"le": "600.0"}) == under_ten_minutes + 1
