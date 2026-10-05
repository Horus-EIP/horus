from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import ai_agents.decision_making_agent as dma
from ai_agents.answer_contract import (
    NOT_IN_DOCUMENTS_ANSWER,
    REASON_DEGENERATE_OUTPUT,
    REASON_INVALID_OUTPUT,
    REASON_NOT_IN_DOCUMENTS,
    REASON_RETRIEVAL_ERROR,
    AgentAnswer,
    AnswerFieldStream,
    AnswerStatus,
    SourceCatalog,
    answer_of,
    answer_prompt,
    answer_response_format,
    answer_schema,
    parse_answer,
)
from ai_agents.decision_making_agent import DecisionMakingAgent
from ai_agents.rag_pipeline import RAGPipeline

Q4_PASSAGE = {
    "chunk_id": "doc-q4:3",
    "doc_id": "doc-q4",
    "title": "1_Q4_2025_Financial_Report.md",
    "page": 2,
    "text": "Q4 2025 revenue was $4.2M.",
}
EXPENSE_PASSAGE = {
    "chunk_id": "doc-expense:0",
    "doc_id": "doc-expense",
    "title": "4_Expense_Policy.md",
    "page": None,
    "text": "Hotel nights are capped at $250.",
}
Q4_SOURCE = {
    "doc_id": "doc-q4",
    "chunk_id": "doc-q4:3",
    "title": "1_Q4_2025_Financial_Report.md",
    "page": 2,
}
EXPENSE_SOURCE = {
    "doc_id": "doc-expense",
    "chunk_id": "doc-expense:0",
    "title": "4_Expense_Policy.md",
    "page": None,
}
SPIRAL = (
    "Revenue was $265K → no — wait, actually, it was $263K → wrong. "
    "But the table says $265K → no, wait, but actually $263K. We conclude "
    "$265K → no. We give up and settle: revenue was $265K → not in text. "
    "Absurd: the variance note says $263K → wrong → no — wait."
)
LLAMA_SERVER_ENV = {
    "LLM_BACKEND": "vllm",
    "LLM_VLLM_URL": "http://llm:8080/v1",
    "LLM_VLLM_MODEL": "qwen3-4b",
    "LLM_VLLM_MAX_MODEL_LEN": "8192",
}


def _catalog(*passages) -> SourceCatalog:
    catalog = SourceCatalog()
    catalog.format_passages(list(passages), 12000)
    return catalog


def _contract(**fields) -> str:
    return json.dumps({"status": "ok", "answer": "Q4 2025 revenue was $4.2M.", **fields})


class TestStrictParsing:
    def test_an_answer_cites_the_passages_it_names(self):
        catalog = _catalog(Q4_PASSAGE, EXPENSE_PASSAGE)

        answer = parse_answer(_contract(sources=["S2", "S1"]), catalog, strict=True)

        assert answer.status is AnswerStatus.OK
        assert answer.answer == "Q4 2025 revenue was $4.2M."
        assert answer.sources == [EXPENSE_SOURCE, Q4_SOURCE]
        assert answer.reason is None

    def test_a_cited_source_that_was_not_retrieved_is_dropped(self):
        catalog = _catalog(Q4_PASSAGE)

        answer = parse_answer(
            _contract(sources=["S1", "S7", "doc-other:4", "S1"]), catalog, strict=True
        )

        assert answer.sources == [Q4_SOURCE]

    def test_a_source_can_be_cited_by_its_chunk_id(self):
        catalog = _catalog(Q4_PASSAGE, EXPENSE_PASSAGE)

        answer = parse_answer(_contract(sources=["doc-expense:0"]), catalog, strict=True)

        assert answer.sources == [EXPENSE_SOURCE]

    @pytest.mark.parametrize(
        "raw",
        [
            "Q4 2025 revenue was $4.2M.",
            '{"status": "ok", "answer": "Q4 2025 revenue was',
            '```json\n{"status": "ok", "answer": "x"}\n```',
            '{"status": "done", "answer": "x"}',
            '{"status": "ok", "answer": 42}',
            '{"status": "ok", "answer": "   "}',
            '["ok", "x"]',
            "",
        ],
        ids=[
            "prose",
            "truncated",
            "fenced",
            "unknown-status",
            "answer-not-text",
            "empty-answer",
            "not-an-object",
            "empty",
        ],
    )
    def test_output_that_breaks_the_contract_is_a_failed_answer(self, raw):
        answer = parse_answer(raw, _catalog(Q4_PASSAGE), strict=True)

        assert answer.status is AnswerStatus.FAILED
        assert answer.reason == REASON_INVALID_OUTPUT
        assert answer.sources == []

    def test_an_answer_the_documents_do_not_contain_cites_nothing(self):
        raw = json.dumps(
            {"status": "not_found", "answer": "The report does not cover 2027.", "sources": ["S1"]}
        )

        answer = parse_answer(raw, _catalog(Q4_PASSAGE), strict=True)

        assert answer.status is AnswerStatus.NOT_FOUND
        assert answer.answer == "The report does not cover 2027."
        assert answer.sources == []
        assert answer.reason == REASON_NOT_IN_DOCUMENTS

    def test_an_empty_not_found_answer_says_the_documents_do_not_contain_it(self):
        raw = json.dumps({"status": "not_found", "answer": "", "sources": []})

        assert parse_answer(raw, _catalog(), strict=True).answer == NOT_IN_DOCUMENTS_ANSWER

    def test_a_refusal_that_cites_nothing_is_an_answer_not_found(self):
        raw = json.dumps(
            {
                "status": "ok",
                "answer": "The retrieved content does not contain this information.",
                "sources": [],
            }
        )

        answer = parse_answer(raw, _catalog(Q4_PASSAGE), strict=True)

        assert (answer.status, answer.reason) == (AnswerStatus.NOT_FOUND, REASON_NOT_IN_DOCUMENTS)
        assert answer.answer == "The retrieved content does not contain this information."

    def test_an_answer_that_cites_a_passage_is_kept_even_when_it_reads_like_a_refusal(self):
        raw = _contract(
            answer="The policy does not provide enough information about weekends; hotels are capped at $250.",
            sources=["S2"],
        )

        answer = parse_answer(raw, _catalog(Q4_PASSAGE, EXPENSE_PASSAGE), strict=True)

        assert answer.status is AnswerStatus.OK
        assert answer.sources == [EXPENSE_SOURCE]

    def test_the_answer_is_nfkc_normalised(self):
        raw = json.dumps({"status": "ok", "answer": "Ｑ４ ２０２５ $4。2M", "sources": []})

        assert parse_answer(raw, _catalog(), strict=True).answer == "Q4 2025 $4.2M"

    def test_a_spiral_in_the_answer_fails_with_the_clean_fallback(self):
        raw = json.dumps({"status": "ok", "answer": "padding " * 30 + SPIRAL, "sources": []})

        answer = parse_answer(raw, _catalog(), strict=True)

        assert answer.status is AnswerStatus.FAILED
        assert answer.reason == REASON_DEGENERATE_OUTPUT
        assert answer.answer == dma.DEGENERATE_OUTPUT_FALLBACK

    def test_a_spiral_that_broke_the_json_is_reported_as_a_spiral(self):
        answer = parse_answer('{"status": "ok", "answer": "' + SPIRAL, _catalog(), strict=True)

        assert answer.reason == REASON_DEGENERATE_OUTPUT


class TestLenientParsing:
    @pytest.mark.parametrize(
        "raw",
        [
            '```json\n{"status": "ok", "answer": "Revenue was $4.2M.", "sources": ["S1"]}\n```',
            'Here is the answer:\n{"status": "ok", "answer": "Revenue was $4.2M.", '
            '"sources": ["[S1]"]}\nHope it helps.',
            '{"status": "OK", "answer": "Revenue was $4.2M.", "sources": ["s1",],}',
            '{"status": "found", "answer": "Revenue was $4.2M.", "sources": "S1"}',
            '{"status": "ok", "answer": "Revenue was $4.2M.", "sources": [{"chunk_id": "doc-q4:3"}]}',
        ],
        ids=["fenced", "surrounded-by-prose", "trailing-commas", "synonym", "source-object"],
    )
    def test_json_around_the_answer_is_read(self, raw):
        answer = parse_answer(raw, _catalog(Q4_PASSAGE), strict=False)

        assert answer.status is AnswerStatus.OK
        assert answer.answer == "Revenue was $4.2M."
        assert answer.sources == [Q4_SOURCE]

    def test_a_missing_sources_field_is_an_answer_without_sources(self):
        answer = parse_answer('{"status": "ok", "answer": "Yes."}', _catalog(Q4_PASSAGE), strict=False)

        assert (answer.status, answer.sources) == (AnswerStatus.OK, [])

    def test_a_raw_newline_inside_the_answer_is_accepted(self):
        answer = parse_answer('{"status": "ok", "answer": "Line one\nLine two"}', _catalog(), strict=False)

        assert answer.answer == "Line one\nLine two"

    def test_prose_without_json_is_still_a_failed_answer(self):
        answer = parse_answer("Revenue was $4.2M.", _catalog(Q4_PASSAGE), strict=False)

        assert (answer.status, answer.reason) == (AnswerStatus.FAILED, REASON_INVALID_OUTPUT)


class TestSchemaAndPrompt:
    def test_the_schema_only_lets_the_model_cite_the_passages_it_was_given(self):
        schema = answer_schema(["S1", "S2"])

        assert schema["properties"]["status"]["enum"] == ["ok", "not_found"]
        assert schema["properties"]["sources"]["items"]["enum"] == ["S1", "S2"]
        assert schema["required"] == ["status", "answer", "sources"]
        assert schema["additionalProperties"] is False
        assert list(schema["properties"]) == ["status", "answer", "sources"]

    def test_without_passages_the_schema_has_no_sources(self):
        schema = answer_schema([])

        assert "sources" not in schema["properties"]
        assert schema["required"] == ["status", "answer"]

    def test_the_response_format_is_the_openai_json_schema_shape(self):
        response_format = answer_response_format(["S1"])

        assert response_format["type"] == "json_schema"
        assert response_format["json_schema"]["name"] == "agent_answer"
        assert response_format["json_schema"]["strict"] is True
        assert response_format["json_schema"]["schema"] == answer_schema(["S1"])

    def test_the_prompt_keeps_the_rules_first_and_the_passages_then_the_request_last(self):
        system, user = answer_prompt("What was Q4 revenue?", "[S1] Q4.md\nRevenue $4.2M.", ["S1"])

        assert '"sources": ["S1"]' in system
        assert "not_found" in system
        assert user == "Passages:\n[S1] Q4.md\nRevenue $4.2M.\n\nRequest: What was Q4 revenue?"

    def test_the_request_is_written_once(self):
        _, user = answer_prompt("Summarise the travel policy", "[S1] Travel.md\nFly economy.", ["S1"])

        assert user.count("Summarise the travel policy") == 1

    @pytest.mark.parametrize("labels", [["S1"], []])
    def test_the_rules_do_not_depend_on_the_request_or_the_passages(self, labels):
        first, _ = answer_prompt("What was Q4 revenue?", "[S1] Q4.md\nRevenue $4.2M.", labels)
        second, _ = answer_prompt("Who approves leave?", "[S1] HR.md\nYour manager.", labels)

        assert first.encode("utf-8") == second.encode("utf-8")
        assert "Q4" not in first and "leave" not in first

    def test_the_prompt_caps_the_passages(self, monkeypatch):
        monkeypatch.setenv("AGENT_MAX_CONTEXT_CHARS", "6000")

        _, user = answer_prompt("q", "A" * 9000, [])

        assert "A" * 6000 + "\n…[retrieved content truncated]" in user
        assert "A" * 6001 not in user


class TestSourceCatalog:
    def test_passages_get_labels_in_rank_order(self):
        catalog = SourceCatalog()

        context = catalog.format_passages([Q4_PASSAGE, EXPENSE_PASSAGE], 12000)

        assert context == (
            "[S1] 1_Q4_2025_Financial_Report.md, page 2\nQ4 2025 revenue was $4.2M.\n\n"
            "[S2] 4_Expense_Policy.md\nHotel nights are capped at $250."
        )
        assert catalog.labels == ["S1", "S2"]

    def test_a_passage_that_does_not_fit_is_left_out_whole(self):
        catalog = SourceCatalog()
        long_passage = {**EXPENSE_PASSAGE, "text": "x" * 500}

        context = catalog.format_passages([Q4_PASSAGE, long_passage], 200)

        assert catalog.labels == ["S1"]
        assert "[S2]" not in context

    def test_a_first_passage_longer_than_the_budget_is_cut(self):
        catalog = SourceCatalog()

        context = catalog.format_passages([{**Q4_PASSAGE, "text": "y" * 500}], 100)

        assert catalog.labels == ["S1"]
        assert context.endswith("…[retrieved content truncated]")
        assert len(context) < 200

    def test_attached_files_are_labelled_before_the_passages(self):
        catalog = SourceCatalog()
        catalog.add_attached_files(
            [{"filename": "q4.md", "doc_id": "doc-q4"}, {"filename": "notes.txt"}]
        )

        catalog.format_passages([EXPENSE_PASSAGE], 12000)

        assert catalog.cite(["S1", "S2", "S3"]) == [
            {"doc_id": "doc-q4", "chunk_id": None, "title": "q4.md", "page": None},
            {"doc_id": None, "chunk_id": None, "title": "notes.txt", "page": None},
            EXPENSE_SOURCE,
        ]


class TestAnswerFieldStream:
    def _stream(self, pieces) -> list[str]:
        view = AnswerFieldStream()
        return [view.feed(piece) for piece in pieces]

    def test_only_the_answer_text_is_shown(self):
        shown = self._stream(['{"status": "ok", "ans', 'wer": "Q4 ', 'revenue', ' was $4.2M."', ', "sources": ["S1"]}'])

        assert "".join(shown) == "Q4 revenue was $4.2M."
        assert shown[0] == ""
        assert shown[-1] == ""

    def test_escapes_split_across_pieces_are_decoded(self):
        shown = self._stream(
            ['{"status": "ok", "answer": "## Q4\\', 'n\\n**Revenue** \\"net\\', '" \\u00', 'e9t\\u00e9 ', '\\ud83d', '\\ude00"}']
        )

        assert "".join(shown) == '## Q4\n\n**Revenue** "net" été 😀'

    def test_nothing_is_shown_before_the_answer_field(self):
        assert self._stream(['{"status": "not_found", ', '"sources": []']) == ["", ""]

    def test_text_after_the_answer_field_is_not_shown(self):
        shown = self._stream(['{"answer": "done", "status": "ok", "answer": "again"}'])

        assert shown == ["done"]


class TestAnswerOf:
    def test_a_pipeline_result_with_a_contract_is_read_back(self):
        contract = AgentAnswer.ok("Yes.", [Q4_SOURCE])

        assert answer_of({"response": "Yes.", "agent_answer": contract.as_dict()}) == contract

    def test_a_plain_result_is_an_answer_without_sources(self):
        assert answer_of({"response": "tool output"}) == AgentAnswer.ok("tool output")
        assert answer_of("specialist output") == AgentAnswer.ok("specialist output")


def _sse(*events) -> list[bytes]:
    lines = []
    for event in events:
        lines.append(event.encode() if isinstance(event, str) else ("data: " + json.dumps(event)).encode())
        lines.append(b"")
    return lines


def _content_chunk(content: str) -> dict:
    return {"choices": [{"index": 0, "delta": {"content": content}, "finish_reason": None}]}


def _streaming_post(content: str) -> MagicMock:
    stream = MagicMock()
    stream.iter_lines.return_value = _sse(_content_chunk(content), "data: [DONE]")
    post = MagicMock()
    post.return_value.__enter__.return_value = stream
    return post


def _remote_agent() -> DecisionMakingAgent:
    agent = DecisionMakingAgent.__new__(DecisionMakingAgent)
    agent.model_name = "Qwen/Qwen3-4B-Instruct-2507"
    agent.device = "cpu"
    agent.decision_model = None
    agent._causal_tokenizer = None
    agent._causal_model = None
    agent._last_gen_tokens = None
    agent._last_prompt_tokens = None
    return agent


@pytest.fixture
def llama_server(monkeypatch):
    for key, value in LLAMA_SERVER_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("AGENT_RESPONSE_CACHE", "0")
    return monkeypatch


def _retrieval(result: dict) -> MagicMock:
    retrieval = MagicMock()
    retrieval.fetch = AsyncMock(return_value=result)
    return retrieval


class TestPipelineOnTheLlamaServer:
    async def test_the_answer_is_constrained_to_the_retrieved_passages(self, llama_server):
        llama_server.delenv("AGENT_STREAM_TOKENS", raising=False)
        post = _streaming_post(_contract(sources=["S1"]))
        pipeline = RAGPipeline(
            _retrieval({"data": "ignored", "passages": [Q4_PASSAGE, EXPENSE_PASSAGE]}),
            _remote_agent(),
            tool_registry=MagicMock(),
        )

        with patch("requests.post", post):
            answer = await pipeline.generate_response("What was Q4 2025 revenue?")

        payload = post.call_args.kwargs["json"]
        schema = payload["response_format"]["json_schema"]["schema"]
        assert schema["properties"]["sources"]["items"]["enum"] == ["S1", "S2"]
        assert "[S1] 1_Q4_2025_Financial_Report.md, page 2" in payload["messages"][1]["content"]
        assert answer == AgentAnswer.ok("Q4 2025 revenue was $4.2M.", [Q4_SOURCE])

    async def test_the_live_preview_streams_only_the_answer_text(self, llama_server):
        llama_server.setenv("AGENT_STREAM_TOKENS", "1")
        stream = MagicMock()
        stream.iter_lines.return_value = _sse(
            _content_chunk('{"status": "ok", '),
            _content_chunk('"answer": "Q4 2025 revenue '),
            _content_chunk('was **$4.2M**.", "sources": ["S1"]}'),
            {"choices": [], "usage": {"prompt_tokens": 400, "completion_tokens": 30}},
            "data: [DONE]",
        )
        post = MagicMock()
        post.return_value.__enter__.return_value = stream
        chunks: list[str] = []

        def emit(step_type, title, detail="", **metadata):
            if step_type == "reasoning.delta":
                chunks.append(metadata["chunk"])

        pipeline = RAGPipeline(
            _retrieval({"data": "ignored", "passages": [Q4_PASSAGE]}),
            _remote_agent(),
            tool_registry=MagicMock(),
        )

        with patch("requests.post", post), patch("ai_agents.step_emitter.emit_step", emit):
            answer = await pipeline.generate_response("What was Q4 2025 revenue?")

        assert "".join(chunks) == "Q4 2025 revenue was **$4.2M**."
        assert post.call_args.kwargs["json"]["response_format"]["type"] == "json_schema"
        assert answer.sources == [Q4_SOURCE]

    async def test_a_failed_search_is_a_failed_answer_without_asking_the_model(self, llama_server):
        decision = MagicMock()
        pipeline = RAGPipeline(
            _retrieval({"data": "Error: Failed to query knowledge store after 3 attempts", "error": "Failed to query knowledge store after 3 attempts"}),
            decision,
            tool_registry=MagicMock(),
        )

        answer = await pipeline.generate_response("What was Q4 2025 revenue?")

        assert (answer.status, answer.reason) == (AnswerStatus.FAILED, REASON_RETRIEVAL_ERROR)
        assert "could not be searched" in answer.answer
        decision.complete.assert_not_called()

    async def test_a_file_named_in_the_request_is_cited_as_a_document(self, llama_server):
        llama_server.delenv("AGENT_STREAM_TOKENS", raising=False)
        post = _streaming_post(_contract(sources=["S1"]))
        resolved = {
            "data": "[Indexed file(s) matching 'q4.md': q4.md | ids: doc-q4]\n\nbody",
            "passages": [{"chunk_id": None, "doc_id": "doc-q4", "title": "q4.md", "page": None, "text": "body"}],
        }
        pipeline = RAGPipeline(_retrieval(resolved), _remote_agent(), tool_registry=MagicMock())

        with patch("requests.post", post):
            answer = await pipeline.generate_response("Summarise q4.md")

        assert answer.sources == [{"doc_id": "doc-q4", "chunk_id": None, "title": "q4.md", "page": None}]


class TestPipelineInProcess:
    async def test_the_in_process_model_is_asked_for_json_and_read_leniently(self, monkeypatch):
        monkeypatch.setenv("AGENT_RESPONSE_CACHE", "0")
        prompts: list[str] = []

        def model(prompt):
            prompts.append(prompt)
            return 'Sure!\n```json\n{"status": "ok", "answer": "Revenue was $4.2M.", "sources": ["S1"]}\n```'

        agent = DecisionMakingAgent(decision_model=model, device="cpu")
        pipeline = RAGPipeline(
            _retrieval({"data": "ignored", "passages": [Q4_PASSAGE]}), agent, tool_registry=MagicMock()
        )

        answer = await pipeline.generate_response("What was Q4 2025 revenue?")

        assert agent.constrains_output is False
        assert "Reply with one JSON object" in prompts[0]
        assert answer == AgentAnswer.ok("Revenue was $4.2M.", [Q4_SOURCE])

    async def test_an_unreadable_in_process_answer_is_failed(self, monkeypatch):
        monkeypatch.setenv("AGENT_RESPONSE_CACHE", "0")
        agent = DecisionMakingAgent(decision_model=MagicMock(return_value="Revenue was $4.2M."), device="cpu")
        pipeline = RAGPipeline(_retrieval({"data": "ctx"}), agent, tool_registry=MagicMock())

        answer = await pipeline.generate_response("What was Q4 2025 revenue?")

        assert (answer.status, answer.reason) == (AnswerStatus.FAILED, REASON_INVALID_OUTPUT)
