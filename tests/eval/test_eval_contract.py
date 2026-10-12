import json

from eval_contract import (
    FAILURE_NOT_JSON,
    FAILURE_RETRIEVAL,
    FAILURE_TRUNCATED,
    REPORT_KIND,
    build_contract_report,
    cited_titles,
    contract_summary,
    probe_items,
    reply_record,
)

REPLY_KEYS = [
    "id",
    "category",
    "question",
    "expected_status",
    "json_valid",
    "failure",
    "violations",
    "status",
    "status_correct",
    "answer",
    "blank_answer",
    "answer_correct_auto",
    "cited_sources",
    "source_correct_auto",
    "error",
    "finish_reason",
    "thought_first",
    "labels",
    "retrieved_titles",
    "wall_s",
    "prompt_tokens",
    "completion_tokens",
    "cached_tokens",
    "prompt_n",
    "prompt_ms",
    "predicted_n",
    "predicted_ms",
    "prompt_tps",
    "generation_tps",
    "content",
    "reasoning_chars",
]
SUMMARY_KEYS = [
    "replies",
    "json_valid",
    "status_correct",
    "answer_correct_auto",
    "source_correct_auto",
    "failures",
    "thought_first",
    "truncated",
    "blank_answers",
    "wall_s",
    "prompt_tokens",
    "completion_tokens",
    "prompt_tps",
    "generation_tps",
    "by_category",
]


def answer_schema(labels):
    properties = {
        "status": {"type": "string", "enum": ["ok", "not_found"]},
        "answer": {"type": "string"},
    }
    required = ["status", "answer"]
    if labels:
        properties["sources"] = {"type": "array", "items": {"type": "string", "enum": list(labels)}}
        required.append("sources")
    return {"type": "object", "properties": properties, "required": required, "additionalProperties": False}


SOURCES = {
    "S1": {"doc_id": "d4", "chunk_id": "d4:2", "title": "4_Expense_Policy.md", "page": None},
    "S2": {"doc_id": "d2", "chunk_id": "d2:7", "title": "2_Employee_Handbook.md", "page": None},
}


def reply(content, **overrides):
    value = {
        "id": "x-01",
        "labels": ["S1", "S2"],
        "sources_by_label": SOURCES,
        "schema": answer_schema(["S1", "S2"]),
        "retrieved_titles": ["4_Expense_Policy.md", "2_Employee_Handbook.md"],
        "content": content if isinstance(content, str) else json.dumps(content),
        "reasoning_content": None,
        "finish_reason": "stop",
        "usage": {"prompt_tokens": 900, "completion_tokens": 40},
        "timings": {
            "cache_n": 300,
            "prompt_n": 600,
            "prompt_ms": 12000.0,
            "prompt_per_second": 50.0,
            "predicted_n": 40,
            "predicted_ms": 4000.0,
            "predicted_per_second": 10.0,
        },
        "wall_s": 16.4,
    }
    value.update(overrides)
    return value


GOOD = {"status": "ok", "answer": "The US hotel limit is $250 per night.", "sources": ["S1"]}


class TestReplyRecord:
    def test_the_record_keeps_the_contract_probe_keys_in_order(self, make_item):
        assert list(reply_record(make_item(), reply(GOOD))) == REPLY_KEYS

    def test_a_correct_cited_answer(self, make_item):
        record = reply_record(make_item(), reply(GOOD))
        assert record["json_valid"] is True
        assert record["failure"] is None
        assert record["status"] == "ok"
        assert record["status_correct"] is True
        assert record["answer_correct_auto"] is True
        assert record["cited_sources"] == ["4_Expense_Policy.md"]
        assert record["source_correct_auto"] is True
        assert record["thought_first"] is False
        assert record["prompt_tokens"] == 900
        assert record["completion_tokens"] == 40
        assert record["generation_tps"] == 10.0
        assert record["wall_s"] == 16.4

    def test_a_valid_reply_citing_the_wrong_document(self, make_item):
        record = reply_record(make_item(), reply({**GOOD, "sources": ["S2"]}))
        assert record["json_valid"] is True
        assert record["source_correct_auto"] is False

    def test_an_invalid_reply_counts_as_wrong_answer_and_source(self, make_item):
        record = reply_record(make_item(), reply("The hotel limit is $250."))
        assert record["json_valid"] is False
        assert record["failure"] == FAILURE_NOT_JSON
        assert record["status"] is None
        assert record["status_correct"] is False
        assert record["answer_correct_auto"] is False
        assert record["source_correct_auto"] is False

    def test_not_in_corpus_expects_not_found_and_has_no_source_score(self, make_item):
        item = make_item(
            id="none-01",
            category="not_in_corpus",
            expected_source=None,
            answer_patterns=[r"\b(does|do)\s*(not|n.t)\s+contain\b"],
        )
        refusal = {"status": "not_found", "answer": "The documents do not contain this.", "sources": []}
        record = reply_record(item, reply(refusal))
        assert record["expected_status"] == "not_found"
        assert record["status_correct"] is True
        assert record["answer_correct_auto"] is True
        assert record["source_correct_auto"] is None
        confident = reply_record(item, reply({**GOOD}))
        assert confident["status_correct"] is False

    def test_a_retrieval_error_is_not_scored_against_the_model(self, make_item):
        record = reply_record(make_item(), {"id": "x-01", "error_stage": "retrieval", "error": "store down"})
        assert record["failure"] == FAILURE_RETRIEVAL
        assert record["json_valid"] is None
        assert record["status_correct"] is None
        assert record["answer_correct_auto"] is None
        assert record["source_correct_auto"] is None

    def test_thinking_is_detected_in_either_field(self, make_item):
        assert reply_record(make_item(), reply(GOOD, reasoning_content="Let me look."))["thought_first"] is True
        assert reply_record(make_item(), reply("<think>hm</think>{}"))["thought_first"] is True

    def test_a_blank_ok_answer_is_valid_but_counted(self, make_item):
        record = reply_record(make_item(), reply({"status": "ok", "answer": " ", "sources": []}))
        assert record["json_valid"] is True
        assert record["blank_answer"] is True


def test_cited_titles_keep_order_and_skip_unknown_labels():
    data = {"sources": ["S2", "S9", "S1", "S2", 3]}
    assert cited_titles(data, SOURCES) == ["2_Employee_Handbook.md", "4_Expense_Policy.md"]
    assert cited_titles(None, SOURCES) == []


def test_probe_items_leave_out_direct_questions(items):
    probed = probe_items(items)
    assert len(probed) == 94
    assert {item["category"] for item in probed} == {"lookup", "numeric", "multi_hop", "not_in_corpus"}


class TestSummary:
    def records(self, make_item):
        refusal_item = make_item(
            id="none-01", category="not_in_corpus", expected_source=None, answer_patterns=[r"\bnot\b"]
        )
        return [
            reply_record(make_item(), reply(GOOD)),
            reply_record(make_item(id="x-02"), reply("not json", finish_reason="length")),
            reply_record(make_item(id="x-03"), reply(GOOD, reasoning_content="thinking")),
            reply_record(refusal_item, reply({"status": "not_found", "answer": "Not in the documents.", "sources": []})),
            reply_record(make_item(id="x-04"), {"id": "x-04", "error_stage": "retrieval", "error": "down"}),
        ]

    def test_rates_failures_and_speed(self, make_item):
        summary = contract_summary(self.records(make_item))
        assert list(summary) == SUMMARY_KEYS
        assert summary["replies"] == 5
        assert summary["json_valid"] == {"n": 4, "correct": 3, "pct": 75.0}
        assert summary["failures"] == {FAILURE_TRUNCATED: 1, FAILURE_RETRIEVAL: 1}
        assert summary["truncated"] == 1
        assert summary["thought_first"] == 1
        assert summary["status_correct"] == {"n": 4, "correct": 3, "pct": 75.0}
        assert summary["answer_correct_auto"] == {"n": 4, "correct": 3, "pct": 75.0}
        assert summary["source_correct_auto"] == {"n": 3, "correct": 2, "pct": 66.7}
        assert summary["prompt_tps"] == 50.0
        assert summary["generation_tps"] == 10.0
        assert summary["wall_s"]["n"] == 4
        assert set(summary["by_category"]) == {"lookup", "not_in_corpus"}
        assert summary["by_category"]["not_in_corpus"]["json_valid"] == {"n": 1, "correct": 1, "pct": 100.0}

    def test_the_report_keeps_every_reply(self, make_item):
        records = self.records(make_item)
        report = build_contract_report(
            label="qwen3-4b-q4km-contract",
            run={"completed": True},
            model={"id": "qwen3-4b-q4km"},
            llama_server={"build": "b11382"},
            records=records,
        )
        assert report["kind"] == REPORT_KIND
        assert report["schema_version"] == 1
        assert report["replies"] == records
        assert report["summary"]["replies"] == 5
        json.dumps(report)
