import json

import pytest
from eval_contract import (
    FAILURE_EMPTY,
    FAILURE_NO_SCHEMA,
    FAILURE_NOT_JSON,
    FAILURE_NOT_OBJECT,
    FAILURE_REQUEST,
    FAILURE_RETRIEVAL,
    FAILURE_SCHEMA,
    FAILURE_TRUNCATED,
    REPORT_KIND,
    build_contract_report,
    check_reply,
    cited_titles,
    contract_summary,
    probe_items,
    reply_record,
    schema_violations,
)


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


class TestSchemaViolations:
    def test_the_b98_shape_is_valid(self):
        assert schema_violations(GOOD, answer_schema(["S1", "S2"])) == []

    def test_a_missing_required_key_is_reported(self):
        assert schema_violations({"status": "ok", "answer": "x"}, answer_schema(["S1"])) == ["$: missing 'sources'"]

    def test_an_extra_key_is_rejected_when_additional_properties_is_false(self):
        assert schema_violations({**GOOD, "reason": "none"}, answer_schema(["S1"])) == ["$: 'reason' is not allowed"]

    def test_a_status_outside_the_enum_is_reported(self):
        assert schema_violations({**GOOD, "status": "failed"}, answer_schema(["S1"])) == [
            "$.status: 'failed' is not one of ['ok', 'not_found']"
        ]

    def test_a_label_that_was_not_shown_is_reported(self):
        assert schema_violations({**GOOD, "sources": ["S1", "S9"]}, answer_schema(["S1"])) == [
            "$.sources[1]: 'S9' is not one of ['S1']"
        ]

    def test_without_passages_a_sources_field_is_not_allowed(self):
        assert schema_violations(GOOD, answer_schema([])) == ["$: 'sources' is not allowed"]
        assert schema_violations({"status": "not_found", "answer": "No."}, answer_schema([])) == []

    def test_types_are_json_types(self):
        schema = {"type": "object", "properties": {"n": {"type": "integer"}, "f": {"type": "number"}}}
        assert schema_violations({"n": 3, "f": 2}, schema) == []
        assert schema_violations({"n": True, "f": "2"}, schema) == [
            "$.n: expected integer, found boolean",
            "$.f: expected number, found string",
        ]
        assert schema_violations("text", {"type": ["object", "null"]}) == ["$: expected object or null, found string"]

    def test_enum_does_not_confuse_booleans_and_numbers(self):
        assert schema_violations(True, {"enum": [1]}) == ["$: True is not one of [1]"]
        assert schema_violations(1, {"enum": [1.0]}) == []

    def test_lengths_and_const_are_checked(self):
        schema = {"type": "array", "minItems": 1, "maxItems": 2, "items": {"type": "string", "maxLength": 2}}
        assert schema_violations([], schema) == ["$: 0 items, at least 1 expected"]
        assert schema_violations(["a", "bcd", "e"], schema) == [
            "$: 3 items, at most 2 expected",
            "$[1]: 3 characters, at most 2 expected",
        ]
        assert schema_violations("x", {"const": "y"}) == ["$: 'x' is not 'y'"]

    def test_an_unsupported_keyword_makes_the_reply_invalid_rather_than_unchecked(self):
        assert schema_violations("x", {"type": "string", "pattern": "^x$"}) == [
            "$: the checker does not support pattern"
        ]

    def test_annotations_are_ignored(self):
        assert schema_violations("x", {"type": "string", "title": "Answer", "description": "d"}) == []


class TestCheckReply:
    @pytest.mark.parametrize(
        ("overrides", "failure"),
        [
            ({"error": "HTTP 500: boom", "content": None}, FAILURE_REQUEST),
            ({"content": ""}, FAILURE_EMPTY),
            ({"content": "  \n"}, FAILURE_EMPTY),
            ({"content": "", "finish_reason": "length"}, FAILURE_TRUNCATED),
            ({"content": '{"status": "ok", "answer": "The US ho', "finish_reason": "length"}, FAILURE_TRUNCATED),
            ({"content": "<think>hotel</think>\n" + json.dumps(GOOD)}, FAILURE_NOT_JSON),
            ({"content": "```json\n" + json.dumps(GOOD) + "\n```"}, FAILURE_NOT_JSON),
            ({"content": json.dumps([GOOD])}, FAILURE_NOT_OBJECT),
            ({"content": json.dumps({"status": "ok", "answer": "x"})}, FAILURE_SCHEMA),
            ({"content": json.dumps(GOOD), "schema": None}, FAILURE_NO_SCHEMA),
        ],
    )
    def test_failures_are_classified(self, overrides, failure):
        assert check_reply({**reply(GOOD), **overrides})[1] == failure

    def test_a_valid_reply_parses_strictly_with_surrounding_whitespace(self):
        data, failure, violations = check_reply(reply("\n " + json.dumps(GOOD) + "\n"))
        assert (data, failure, violations) == (GOOD, None, [])


class TestReplyRecord:
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
