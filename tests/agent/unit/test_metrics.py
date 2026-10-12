from prometheus_client import REGISTRY

from core import metrics

TASK_BUCKET = "agent_task_processing_duration_seconds_bucket"
INFERENCE_BUCKET = "agent_model_inference_duration_seconds_bucket"
STORE_BUCKET = "agent_knowledge_store_request_duration_seconds_bucket"
INFERENCE_LABELS = {"model_name": "qwen3-4b", "device": "cpu"}


def sample(name, labels):
    return REGISTRY.get_sample_value(name, labels)


class TestLatencyBuckets:
    def test_task_and_inference_buckets_reach_thirty_minutes(self):
        metrics.model_inference_duration.labels(**INFERENCE_LABELS)

        assert sample(TASK_BUCKET, {"le": "1800.0"}) is not None
        assert sample(INFERENCE_BUCKET, {**INFERENCE_LABELS, "le": "1800.0"}) is not None

    def test_a_fourteen_minute_cpu_answer_lands_in_a_finite_bucket(self):
        under_ten_minutes = sample(TASK_BUCKET, {"le": "600.0"})
        under_fifteen_minutes = sample(TASK_BUCKET, {"le": "900.0"})

        metrics.task_processing_duration.observe(14 * 60)

        assert sample(TASK_BUCKET, {"le": "600.0"}) == under_ten_minutes
        assert sample(TASK_BUCKET, {"le": "900.0"}) == under_fifteen_minutes + 1

    def test_knowledge_store_buckets_cover_three_timed_out_attempts(self):
        under_thirty_seconds = sample(STORE_BUCKET, {"le": "30.0"})
        under_a_minute = sample(STORE_BUCKET, {"le": "60.0"})

        metrics.knowledge_store_request_duration.observe(3 * 10.0 + 1.0 + 2.0)

        assert sample(STORE_BUCKET, {"le": "30.0"}) == under_thirty_seconds
        assert sample(STORE_BUCKET, {"le": "60.0"}) == under_a_minute + 1


class TestPromptTokenBuckets:
    def test_a_prompt_lands_in_the_bucket_of_its_size(self):
        labels = {"call": "answer", "source": "usage"}
        under_4096 = sample("agent_llm_prompt_tokens_bucket", {**labels, "le": "4096.0"}) or 0.0
        under_3072 = sample("agent_llm_prompt_tokens_bucket", {**labels, "le": "3072.0"}) or 0.0

        metrics.llm_prompt_tokens.labels(**labels).observe(3600)

        assert sample("agent_llm_prompt_tokens_bucket", {**labels, "le": "3072.0"}) == under_3072
        assert sample("agent_llm_prompt_tokens_bucket", {**labels, "le": "4096.0"}) == under_4096 + 1

    def test_the_buckets_reach_a_whole_chain_transcript(self):
        metrics.llm_prompt_tokens.labels(call="answer", source="estimate")

        assert sample(
            "agent_llm_prompt_tokens_bucket", {"call": "answer", "source": "estimate", "le": "32768.0"}
        ) is not None
