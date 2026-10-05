import datetime

from prometheus_client import REGISTRY

from core import metrics

BUCKET = "mas_task_processing_seconds_bucket"


def sample(name, labels=None):
    return REGISTRY.get_sample_value(name, labels or {})


class TestTaskProcessingTime:
    def test_buckets_reach_the_thirty_minute_task_timeout(self):
        assert sample(BUCKET, {"le": "1800.0"}) is not None

    def test_a_twenty_minute_cpu_task_lands_in_a_finite_bucket(self):
        started = datetime.datetime.now(datetime.UTC) - datetime.timedelta(minutes=20)
        under_fifteen_minutes = sample(BUCKET, {"le": "900.0"})
        under_thirty_minutes = sample(BUCKET, {"le": "1800.0"})

        metrics.observe_task_processing_time(started)

        assert sample(BUCKET, {"le": "900.0"}) == under_fifteen_minutes
        assert sample(BUCKET, {"le": "1800.0"}) == under_thirty_minutes + 1

    def test_a_naive_creation_time_is_read_as_utc(self):
        started = datetime.datetime.now(datetime.UTC).replace(tzinfo=None) - datetime.timedelta(
            minutes=5
        )
        total_before = sample("mas_task_processing_seconds_sum")

        metrics.observe_task_processing_time(started)

        assert 300 <= sample("mas_task_processing_seconds_sum") - total_before < 360

    def test_a_task_without_a_creation_time_is_not_recorded(self):
        count_before = sample("mas_task_processing_seconds_count")

        metrics.observe_task_processing_time(None)

        assert sample("mas_task_processing_seconds_count") == count_before


class TestRoutingDecisions:
    def test_each_decision_counts_once_under_its_method_and_route(self):
        labels = {"method": "embedding", "route": "SINGLE_AGENT"}
        before = sample("mas_routing_decisions_total", labels) or 0.0

        metrics.observe_routing_decision("embedding", "SINGLE_AGENT", 0.008)

        assert sample("mas_routing_decisions_total", labels) == before + 1

    def test_routing_latency_is_kept_per_method_with_millisecond_buckets(self):
        under_ten_ms = sample("mas_routing_decision_seconds_bucket", {"method": "rules", "le": "0.01"}) or 0.0
        count = sample("mas_routing_decision_seconds_count", {"method": "rules"}) or 0.0

        metrics.observe_routing_decision("rules", "DIRECT_ANSWER", 0.0004)

        assert sample("mas_routing_decision_seconds_bucket", {"method": "rules", "le": "0.01"}) == under_ten_ms + 1
        assert sample("mas_routing_decision_seconds_count", {"method": "rules"}) == count + 1

    def test_a_slow_cpu_llm_fallback_lands_in_a_finite_bucket(self):
        labels = {"method": "llm", "le": "300.0"}
        before = sample("mas_routing_decision_seconds_bucket", labels) or 0.0

        metrics.observe_routing_decision("llm", "SINGLE_AGENT", 240.0)

        assert sample("mas_routing_decision_seconds_bucket", labels) == before + 1
        assert sample("mas_routing_decision_seconds_bucket", {"method": "llm", "le": "1800.0"}) is not None
