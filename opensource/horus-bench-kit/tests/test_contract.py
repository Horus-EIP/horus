# SPDX-License-Identifier: Apache-2.0
import json

import pytest

from horus_bench_kit.contract import (
    FAILURE_EMPTY,
    FAILURE_NO_SCHEMA,
    FAILURE_NOT_JSON,
    FAILURE_NOT_OBJECT,
    FAILURE_REQUEST,
    FAILURE_SCHEMA,
    FAILURE_TRUNCATED,
    check_reply,
    json_type,
    reply_timings,
    schema_violations,
    thought_first,
    throughput,
)


def verdict_schema(evidence_ids=("E1", "E2")):
    return {
        "type": "object",
        "properties": {
            "verdict": {"type": "string", "enum": ["supported", "refuted", "unknown"]},
            "reason": {"type": "string", "description": "one short sentence"},
            "evidence": {
                "type": "array",
                "maxItems": 3,
                "items": {"type": "string", "enum": list(evidence_ids)},
            },
        },
        "required": ["verdict", "reason", "evidence"],
        "additionalProperties": False,
    }


GOOD = {"verdict": "supported", "reason": "The timetable lists a 06:40 ferry.", "evidence": ["E1"]}


def reply(content, **overrides):
    value = {
        "id": "claim-01",
        "schema": verdict_schema(),
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
            "predicted_per_second": 10.004,
        },
        "wall_s": 16.4,
    }
    value.update(overrides)
    return value


class TestSchemaViolations:
    def test_a_matching_object_is_valid(self):
        assert schema_violations(GOOD, verdict_schema()) == []

    def test_a_missing_required_key_is_reported(self):
        value = {"verdict": "unknown", "reason": "x"}
        assert schema_violations(value, verdict_schema(["E1"])) == ["$: missing 'evidence'"]

    def test_an_extra_key_is_rejected_when_additional_properties_is_false(self):
        assert schema_violations({**GOOD, "score": 3}, verdict_schema()) == [
            "$: 'score' is not allowed"
        ]

    def test_additional_properties_can_be_a_schema(self):
        schema = {"type": "object", "additionalProperties": {"type": "integer"}}
        assert schema_violations({"a": 1, "b": "2"}, schema) == [
            "$.b: expected integer, found string"
        ]

    def test_a_value_outside_the_enum_is_reported(self):
        assert schema_violations({**GOOD, "verdict": "maybe"}, verdict_schema()) == [
            "$.verdict: 'maybe' is not one of ['supported', 'refuted', 'unknown']"
        ]

    def test_an_item_outside_its_enum_is_reported_with_its_index(self):
        assert schema_violations({**GOOD, "evidence": ["E1", "E9"]}, verdict_schema(["E1"])) == [
            "$.evidence[1]: 'E9' is not one of ['E1']"
        ]

    def test_without_evidence_ids_an_evidence_field_is_not_allowed(self):
        assert schema_violations(GOOD, verdict_schema([])) == [
            "$.evidence[0]: 'E1' is not one of []"
        ]
        assert (
            schema_violations(
                {"verdict": "unknown", "reason": "No.", "evidence": []}, verdict_schema([])
            )
            == []
        )

    def test_types_are_json_types(self):
        schema = {
            "type": "object",
            "properties": {"n": {"type": "integer"}, "f": {"type": "number"}},
        }
        assert schema_violations({"n": 3, "f": 2}, schema) == []
        assert schema_violations({"n": True, "f": "2"}, schema) == [
            "$.n: expected integer, found boolean",
            "$.f: expected number, found string",
        ]
        assert schema_violations("text", {"type": ["object", "null"]}) == [
            "$: expected object or null, found string"
        ]

    def test_enum_does_not_confuse_booleans_and_numbers(self):
        assert schema_violations(True, {"enum": [1]}) == ["$: True is not one of [1]"]
        assert schema_violations(1, {"enum": [1.0]}) == []

    def test_lengths_and_const_are_checked(self):
        schema = {
            "type": "array",
            "minItems": 1,
            "maxItems": 2,
            "items": {"type": "string", "maxLength": 2},
        }
        assert schema_violations([], schema) == ["$: 0 items, at least 1 expected"]
        assert schema_violations(["a", "bcd", "e"], schema) == [
            "$: 3 items, at most 2 expected",
            "$[1]: 3 characters, at most 2 expected",
        ]
        assert schema_violations("", {"minLength": 1}) == ["$: 0 characters, at least 1 expected"]
        assert schema_violations("x", {"const": "y"}) == ["$: 'x' is not 'y'"]

    def test_an_unsupported_keyword_makes_the_reply_invalid_rather_than_unchecked(self):
        assert schema_violations("x", {"type": "string", "pattern": "^x$"}) == [
            "$: the checker does not support pattern"
        ]

    def test_annotations_are_ignored(self):
        assert (
            schema_violations("x", {"type": "string", "title": "Reason", "description": "d"}) == []
        )

    def test_boolean_subschemas_allow_anything_or_nothing(self):
        schema = {
            "type": "object",
            "properties": {"note": True, "secret": False},
            "additionalProperties": False,
        }
        assert schema_violations({"note": [1, "x"]}, schema) == []
        assert schema_violations({"secret": 1}, schema) == [
            "$.secret: the schema allows no value here"
        ]
        assert schema_violations([1], {"items": False}) == ["$[0]: the schema allows no value here"]
        assert schema_violations([1], {"items": True}) == []

    @pytest.mark.parametrize(
        ("schema", "message"),
        [
            ({"minLength": "3"}, "$: the checker does not support minLength '3'"),
            ({"maxItems": 1.5}, "$: the checker does not support maxItems 1.5"),
            ({"minItems": True}, "$: the checker does not support minItems True"),
            ({"type": 5}, "$: the checker does not support type 5"),
            ({"enum": "ab"}, "$: the checker does not support enum 'ab'"),
            ({"required": "verdict"}, "$: the checker does not support required 'verdict'"),
            ({"properties": ["verdict"]}, "$: the checker does not support properties ['verdict']"),
            (
                {"items": [{"type": "string"}]},
                "$: the checker does not support items [{'type': 'string'}]",
            ),
        ],
    )
    def test_a_malformed_keyword_makes_the_reply_invalid_rather_than_crash(self, schema, message):
        assert schema_violations(["a"], schema) == [message]

    def test_a_subschema_that_is_not_an_object_or_a_boolean_is_not_supported(self):
        schema = {"type": "object", "properties": {"verdict": "string"}}
        assert schema_violations({"verdict": "x"}, schema) == [
            "$.verdict: the checker does not support a string schema"
        ]

    def test_json_type_names(self):
        assert [json_type(v) for v in (True, 1, 1.5, "s", [], {}, None)] == [
            "boolean",
            "integer",
            "number",
            "string",
            "array",
            "object",
            "null",
        ]
        assert json_type(b"x") == "bytes"


class TestCheckReply:
    @pytest.mark.parametrize(
        ("overrides", "failure"),
        [
            ({"error": "HTTP 500: boom", "content": None}, FAILURE_REQUEST),
            ({"content": ""}, FAILURE_EMPTY),
            ({"content": "  \n"}, FAILURE_EMPTY),
            ({"content": "", "finish_reason": "length"}, FAILURE_TRUNCATED),
            (
                {
                    "content": '{"verdict": "supported", "reason": "The time',
                    "finish_reason": "length",
                },
                FAILURE_TRUNCATED,
            ),
            ({"content": "<think>ferry</think>\n" + json.dumps(GOOD)}, FAILURE_NOT_JSON),
            ({"content": "```json\n" + json.dumps(GOOD) + "\n```"}, FAILURE_NOT_JSON),
            ({"content": json.dumps([GOOD])}, FAILURE_NOT_OBJECT),
            ({"content": json.dumps({"verdict": "supported", "reason": "x"})}, FAILURE_SCHEMA),
            ({"content": json.dumps(GOOD), "schema": None}, FAILURE_NO_SCHEMA),
        ],
    )
    def test_failures_are_classified(self, overrides, failure):
        assert check_reply({**reply(GOOD), **overrides})[1] == failure

    def test_a_valid_reply_parses_strictly_with_surrounding_whitespace(self):
        assert check_reply(reply("\n " + json.dumps(GOOD) + "\n")) == (GOOD, None, [])

    def test_a_schema_failure_returns_the_data_and_the_violations(self):
        data, failure, violations = check_reply(
            reply({"verdict": "maybe", "reason": "x", "evidence": []})
        )
        assert data["verdict"] == "maybe"
        assert failure == FAILURE_SCHEMA
        assert violations == [
            "$.verdict: 'maybe' is not one of ['supported', 'refuted', 'unknown']"
        ]


class TestReplyFacts:
    def test_thought_first_sees_reasoning_content_or_a_think_tag(self):
        assert thought_first(reply(GOOD, reasoning_content="Let me see."))
        assert thought_first(reply("  <think>hmm</think>{}"))
        assert not thought_first(reply(GOOD))
        assert not thought_first({**reply(GOOD), "content": None})

    def test_reply_timings_read_usage_and_llama_server_timings(self):
        assert reply_timings(reply(GOOD)) == {
            "wall_s": 16.4,
            "prompt_tokens": 900,
            "completion_tokens": 40,
            "cached_tokens": 300,
            "prompt_n": 600,
            "prompt_ms": 12000.0,
            "predicted_n": 40,
            "predicted_ms": 4000.0,
            "prompt_tps": 50.0,
            "generation_tps": 10.0,
        }

    def test_reply_timings_are_null_when_the_server_does_not_report_them(self):
        timings = reply_timings({"usage": "n/a", "timings": None, "wall_s": True})
        assert set(timings.values()) == {None}

    def test_throughput_sums_tokens_over_time_of_the_counted_records(self):
        records = [
            {"predicted_n": 40, "predicted_ms": 4000.0},
            {"predicted_n": 60, "predicted_ms": 6000.0},
            {"predicted_n": None, "predicted_ms": 9000.0},
        ]
        assert throughput(records, "predicted_n", "predicted_ms") == 10.0
        assert throughput([], "predicted_n", "predicted_ms") is None
