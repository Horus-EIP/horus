from __future__ import annotations

import json
import threading
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

import ai_agents.decision_making_agent as dma
import ai_agents.response_cache as response_cache
from ai_agents.answer_contract import AnswerStatus
from ai_agents.generation_stop import GenerationTimedOut
from ai_agents.rag_pipeline import RAGPipeline

QUESTION = "What was Q4 2025 revenue?"
CONTEXT = "Q4 2025 Financial Report: revenue was $4.2M."
SPIRAL = (
    "Revenue was $265K → no — wait, actually, it was $263K → wrong. "
    "But the table says $265K → no, wait, but actually $263K. We conclude "
    "$265K → no. We give up and settle: revenue was $265K → not in text. "
    "Absurd: the variance note says $263K → wrong → no — wait."
)


class FakeRedis:
    def __init__(self):
        self.entries: dict[str, str] = {}

    async def get(self, key):
        return self.entries.get(key)

    async def set(self, key, value, ex=None):
        self.entries[key] = value

    async def aclose(self):
        return None


class FakeKnowledgeStore:
    def __init__(self):
        self.uploads = 0
        self.version_reads = 0
        self.failure: httpx.Response | Exception | None = None

    def upload(self):
        self.uploads += 1

    def handle(self, request: httpx.Request) -> httpx.Response:
        if not request.url.path.endswith("/corpus-version"):
            return httpx.Response(404)
        self.version_reads += 1
        if isinstance(self.failure, Exception):
            raise self.failure
        if self.failure is not None:
            return self.failure
        return httpx.Response(
            200, json={"version": f"boot-{self.uploads}", "changed_at": "2026-10-05T09:00:00Z"}
        )


@pytest.fixture
def knowledge_store(monkeypatch):
    store = FakeKnowledgeStore()
    transport = httpx.MockTransport(store.handle)
    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda *args, **kwargs: real_client(*args, transport=transport, **kwargs),
    )
    return store


@pytest.fixture
def redis(monkeypatch, knowledge_store):
    fake = FakeRedis()
    monkeypatch.setenv("AGENT_RESPONSE_CACHE", "1")
    monkeypatch.setenv("AGENT_RESPONSE_CACHE_VERSION_TTL", "0")
    monkeypatch.setattr(response_cache, "_REDIS_AVAILABLE", True)
    monkeypatch.setattr(response_cache, "_new_client", lambda: fake)
    monkeypatch.setattr(response_cache, "_corpus_version_memo", None)
    return fake


def _contract(answer: str, status: str = "ok", sources=()) -> str:
    return json.dumps({"status": status, "answer": answer, "sources": list(sources)})


def _stored_answers(redis) -> list[str]:
    return [json.loads(entry)["answer"] for entry in redis.entries.values()]


def _pipeline(*answers: str, retrieved=None):
    remaining = list(answers)

    def complete(*_args, **_kwargs):
        if not remaining:
            raise AssertionError("the model was asked more often than the test expected")
        answer = remaining.pop(0)
        return answer if answer.startswith("{") else _contract(answer)

    retrieval = MagicMock()
    retrieval.fetch = AsyncMock(return_value=retrieved or {"data": CONTEXT})
    decision = MagicMock()
    decision.device = "cuda"
    decision.complete.side_effect = complete
    return RAGPipeline(retrieval, decision, tool_registry=MagicMock()), decision


class TestCacheHits:
    async def test_a_repeated_question_is_answered_from_the_cache(self, redis):
        pipeline, decision = _pipeline("Q4 2025 revenue was $4.2M.")

        first = await pipeline.generate_response(QUESTION)
        second = await pipeline.generate_response(QUESTION)

        assert first.answer == second.answer == "Q4 2025 revenue was $4.2M."
        assert second.status is AnswerStatus.OK
        assert decision.complete.call_count == 1

    async def test_full_width_and_ascii_questions_share_one_entry(self, redis):
        pipeline, decision = _pipeline("Q4 2025 revenue was $4.2M.")

        await pipeline.generate_response("What was Ｑ４ ２０２５ revenue?")
        assert (await pipeline.generate_response(QUESTION)).answer == "Q4 2025 revenue was $4.2M."

        assert decision.complete.call_count == 1

    async def test_answers_are_stored_nfkc_normalised(self, redis):
        pipeline, _ = _pipeline("Ｑ４ ２０２５ revenue was $4。2M")

        await pipeline.generate_response(QUESTION)

        assert _stored_answers(redis) == ["Q4 2025 revenue was $4.2M"]
        assert (await pipeline.generate_response(QUESTION)).answer == "Q4 2025 revenue was $4.2M"

    async def test_an_answer_about_what_a_policy_does_not_cover_is_cached(self, redis):
        pipeline, decision = _pipeline("Alcohol is not covered by the Expense Policy.")

        await pipeline.generate_response("Can I expense wine?")
        await pipeline.generate_response("Can I expense wine?")

        assert decision.complete.call_count == 1


class TestCorpusVersion:
    async def test_after_an_upload_the_cache_misses(self, redis, knowledge_store):
        pipeline, decision = _pipeline("Revenue was $4.2M.", "Revenue was $4.3M.")

        assert (await pipeline.generate_response(QUESTION)).answer == "Revenue was $4.2M."
        knowledge_store.upload()

        assert (await pipeline.generate_response(QUESTION)).answer == "Revenue was $4.3M."
        assert decision.complete.call_count == 2

    async def test_an_upload_during_generation_does_not_keep_the_older_answer(
        self, redis, knowledge_store
    ):
        pipeline, decision = _pipeline()
        answers = iter(["Revenue was $4.2M.", "Revenue was $4.3M."])

        def answer_while_a_document_is_uploaded(*_args, **_kwargs):
            answer = next(answers)
            if knowledge_store.uploads == 0:
                knowledge_store.upload()
            return _contract(answer)

        decision.complete.side_effect = answer_while_a_document_is_uploaded

        await pipeline.generate_response(QUESTION)

        assert (await pipeline.generate_response(QUESTION)).answer == "Revenue was $4.3M."
        assert decision.complete.call_count == 2

    async def test_the_version_is_read_from_the_knowledge_store(self, redis, knowledge_store):
        pipeline, _ = _pipeline("Revenue was $4.2M.")

        await pipeline.generate_response(QUESTION)

        assert knowledge_store.version_reads == 1

    async def test_the_version_is_reused_within_its_ttl(self, redis, knowledge_store, monkeypatch):
        monkeypatch.setenv("AGENT_RESPONSE_CACHE_VERSION_TTL", "60")
        pipeline, _ = _pipeline("Revenue was $4.2M.")

        await pipeline.generate_response(QUESTION)
        await pipeline.generate_response(QUESTION)

        assert knowledge_store.version_reads == 1

    @pytest.mark.parametrize(
        "failure",
        [
            httpx.Response(503),
            httpx.Response(200, json={"status": "healthy"}),
            httpx.Response(200, text="not json"),
            httpx.ConnectError("connection refused"),
            httpx.ReadTimeout("timed out"),
        ],
        ids=["unavailable", "no-version-field", "not-json", "unreachable", "timeout"],
    )
    async def test_a_version_read_failure_bypasses_the_cache(self, redis, knowledge_store, failure):
        knowledge_store.failure = failure
        pipeline, decision = _pipeline("Revenue was $4.2M.", "Revenue was $4.2M.")

        assert (await pipeline.generate_response(QUESTION)).answer == "Revenue was $4.2M."
        assert (await pipeline.generate_response(QUESTION)).answer == "Revenue was $4.2M."

        assert decision.complete.call_count == 2
        assert redis.entries == {}

    async def test_a_disabled_cache_never_asks_for_the_version(self, knowledge_store, monkeypatch):
        monkeypatch.setenv("AGENT_RESPONSE_CACHE", "0")
        pipeline, decision = _pipeline("Revenue was $4.2M.")

        assert (await pipeline.generate_response(QUESTION)).answer == "Revenue was $4.2M."

        assert knowledge_store.version_reads == 0
        assert decision.complete.call_count == 1


class TestGenerationSettings:
    async def test_a_different_context_cap_misses_the_cache(self, redis, monkeypatch):
        pipeline, decision = _pipeline("Revenue was $4.2M.", "Revenue was $4.2M.")

        monkeypatch.setenv("AGENT_MAX_CONTEXT_CHARS", "12000")
        await pipeline.generate_response(QUESTION)
        monkeypatch.setenv("AGENT_MAX_CONTEXT_CHARS", "6000")
        await pipeline.generate_response(QUESTION)

        assert decision.complete.call_count == 2
        assert len(redis.entries) == 2

    async def test_a_mock_answer_and_a_model_answer_never_share_an_entry(self, redis, monkeypatch):
        pipeline, decision = _pipeline("Revenue was $4.2M.", "Simulated: revenue was $4.2M.")

        monkeypatch.setenv("LLM_BACKEND", "vllm")
        monkeypatch.setenv("LLM_VLLM_MODEL", "qwen3-4b")
        assert (await pipeline.generate_response(QUESTION)).answer == "Revenue was $4.2M."
        monkeypatch.setenv("LLM_VLLM_MODEL", "horus-mock")
        mock = await pipeline.generate_response(QUESTION)
        monkeypatch.setenv("LLM_VLLM_MODEL", "qwen3-4b")
        local = await pipeline.generate_response(QUESTION)

        assert mock.answer == "Simulated: revenue was $4.2M."
        assert local.answer == "Revenue was $4.2M."
        assert decision.complete.call_count == 2
        assert len(redis.entries) == 2

    async def test_an_unset_cap_shares_the_entry_of_the_default_cap(self, redis, monkeypatch):
        pipeline, decision = _pipeline("Revenue was $4.2M.")

        monkeypatch.delenv("AGENT_MAX_CONTEXT_CHARS", raising=False)
        await pipeline.generate_response(QUESTION)
        monkeypatch.setenv("AGENT_MAX_CONTEXT_CHARS", str(dma.DEFAULT_MAX_CONTEXT_CHARS))
        await pipeline.generate_response(QUESTION)

        assert decision.complete.call_count == 1


class TestOnlyValidatedAnswersAreCached:
    async def test_a_degenerate_answer_is_never_cached(self, redis):
        assert dma._is_degenerate_output(SPIRAL)
        pipeline, decision = _pipeline(SPIRAL, SPIRAL)

        await pipeline.generate_response(QUESTION)
        await pipeline.generate_response(QUESTION)

        assert redis.entries == {}
        assert decision.complete.call_count == 2

    async def test_the_spiral_fallback_answer_is_never_cached(self, redis):
        fallback = dma.DEGENERATE_OUTPUT_FALLBACK
        pipeline, decision = _pipeline(fallback, fallback)

        await pipeline.generate_response(QUESTION)
        await pipeline.generate_response(QUESTION)

        assert redis.entries == {}
        assert decision.complete.call_count == 2

    @pytest.mark.parametrize(
        "refusal",
        [
            "The retrieved content does not contain this information.",
            "The retrieved content doesn’t contain this information.",
            "I don't have that information yet.",
            "I don't have that information in the finance corpus yet.",
            "I don’t have that information in the compliance corpus yet.",
            "That isn't covered in the current HR documents — please reach out to "
            "your people partner.",
            "There is no information about late fees in the retrieved content.",
            "I'm sorry, but I cannot answer that from the documents.",
        ],
    )
    async def test_a_refusal_is_never_cached(self, redis, refusal):
        pipeline, decision = _pipeline(refusal, refusal)

        await pipeline.generate_response(QUESTION)
        await pipeline.generate_response(QUESTION)

        assert redis.entries == {}
        assert decision.complete.call_count == 2

    async def test_an_empty_answer_is_never_cached(self, redis):
        pipeline, decision = _pipeline("", "")

        await pipeline.generate_response(QUESTION)
        await pipeline.generate_response(QUESTION)

        assert redis.entries == {}
        assert decision.complete.call_count == 2

    async def test_the_timeout_answer_is_never_cached(self, redis, monkeypatch):
        monkeypatch.setenv("REACT_TIMEOUT_SECONDS", "0.05")
        release = threading.Event()
        pipeline, decision = _pipeline()
        decision.complete.side_effect = lambda *_args, **_kwargs: (
            release.wait(5) and _contract("late answer")
        )

        try:
            with pytest.raises(GenerationTimedOut):
                await pipeline.generate_response(QUESTION)
        finally:
            release.set()

        assert redis.entries == {}

    async def test_an_entry_that_fails_validation_is_not_served(self, redis):
        pipeline, decision = _pipeline("Revenue was $4.2M.", "Revenue was $4.2M.")
        await pipeline.generate_response(QUESTION)
        (key,) = redis.entries
        redis.entries[key] = json.dumps({"answer": SPIRAL, "sources": []})

        assert (await pipeline.generate_response(QUESTION)).answer == "Revenue was $4.2M."
        assert decision.complete.call_count == 2

    async def test_an_entry_from_the_previous_cache_format_is_not_served(self, redis):
        pipeline, decision = _pipeline("Revenue was $4.2M.", "Revenue was $4.2M.")
        await pipeline.generate_response(QUESTION)
        (key,) = redis.entries
        redis.entries[key] = "Revenue was $4.2M."

        assert (await pipeline.generate_response(QUESTION)).status is AnswerStatus.OK
        assert decision.complete.call_count == 2

    async def test_an_answer_the_documents_do_not_contain_is_never_cached(self, redis):
        not_found = _contract("The documents don't say.", status="not_found")
        pipeline, decision = _pipeline(not_found, not_found)

        first = await pipeline.generate_response(QUESTION)
        await pipeline.generate_response(QUESTION)

        assert first.status is AnswerStatus.NOT_FOUND
        assert redis.entries == {}
        assert decision.complete.call_count == 2

    async def test_a_cache_hit_keeps_the_sources_the_answer_cited(self, redis):
        retrieved = {
            "data": CONTEXT,
            "passages": [
                {
                    "chunk_id": "doc-q4:2",
                    "doc_id": "doc-q4",
                    "title": "1_Q4_2025_Financial_Report.md",
                    "page": None,
                    "text": CONTEXT,
                }
            ],
        }
        pipeline, decision = _pipeline(
            _contract("Q4 2025 revenue was $4.2M.", sources=["S1"]), retrieved=retrieved
        )

        first = await pipeline.generate_response(QUESTION)
        second = await pipeline.generate_response(QUESTION)

        assert decision.complete.call_count == 1
        assert (
            second.sources
            == first.sources
            == [
                {
                    "doc_id": "doc-q4",
                    "chunk_id": "doc-q4:2",
                    "title": "1_Q4_2025_Financial_Report.md",
                    "page": None,
                }
            ]
        )


class TestWithTheDecisionAgent:
    def _pipeline_over(self, model_output: str):
        model = MagicMock(return_value=model_output)
        retrieval = MagicMock()
        retrieval.fetch = AsyncMock(return_value={"data": CONTEXT})
        agent = dma.DecisionMakingAgent(decision_model=model, device="cuda")
        return RAGPipeline(retrieval, agent, tool_registry=MagicMock()), model

    async def test_a_spiral_replaced_by_the_fallback_is_never_cached(self, redis):
        pipeline, model = self._pipeline_over(SPIRAL)

        first = await pipeline.generate_response(QUESTION)
        await pipeline.generate_response(QUESTION)

        assert first.status is AnswerStatus.FAILED
        assert first.answer == dma.DEGENERATE_OUTPUT_FALLBACK
        assert redis.entries == {}
        assert model.call_count == 2

    async def test_a_full_width_answer_is_cached_in_ascii(self, redis):
        pipeline, model = self._pipeline_over(
            '{"status": "ok", "answer": "Ｑ４ ２０２５ revenue was $4。2M"}'
        )

        await pipeline.generate_response(QUESTION)
        second = await pipeline.generate_response(QUESTION)

        assert second.answer == "Q4 2025 revenue was $4.2M"
        assert _stored_answers(redis) == ["Q4 2025 revenue was $4.2M"]
        assert model.call_count == 1
