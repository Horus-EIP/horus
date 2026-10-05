from __future__ import annotations

import json
from collections import Counter
from typing import Any

from eval_report import rate, stats
from eval_scoring import answer_correct, source_check
from eval_testset import CATEGORIES

REPORT_KIND = "horus-contract-probe"
SCHEMA_VERSION = 1
PROBED_CATEGORIES = ("lookup", "numeric", "multi_hop", "not_in_corpus")
WARMUP_QUESTION = "In one sentence, what kinds of documents are in the knowledge store?"
STATUS_OK = "ok"
STATUS_NOT_FOUND = "not_found"
LENGTH_FINISH_REASON = "length"
THINK_TAG = "<think"

ERROR_STAGE_RETRIEVAL = "retrieval"
ERROR_STAGE_LLM = "llm"

FAILURE_RETRIEVAL = "retrieval_error"
FAILURE_REQUEST = "request_error"
FAILURE_EMPTY = "empty"
FAILURE_TRUNCATED = "truncated"
FAILURE_NOT_JSON = "not_json"
FAILURE_NOT_OBJECT = "not_object"
FAILURE_SCHEMA = "schema"
FAILURE_NO_SCHEMA = "no_schema"

SUPPORTED_KEYWORDS = frozenset(
    {
        "type",
        "enum",
        "const",
        "properties",
        "required",
        "additionalProperties",
        "items",
        "minItems",
        "maxItems",
        "minLength",
        "maxLength",
    }
)
ANNOTATION_KEYWORDS = frozenset({"title", "description", "$schema", "default", "examples"})
_JSON_TYPE_NAMES = (
    (bool, "boolean"),
    (int, "integer"),
    (float, "number"),
    (str, "string"),
    (list, "array"),
    (dict, "object"),
    (type(None), "null"),
)


def json_type(value: Any) -> str:
    for python_type, name in _JSON_TYPE_NAMES:
        if isinstance(value, python_type):
            return name
    return type(value).__name__


def _type_matches(value: Any, expected: str) -> bool:
    actual = json_type(value)
    if expected == "number":
        return actual in ("integer", "number")
    return actual == expected


def _same_json(left: Any, right: Any) -> bool:
    return left == right and isinstance(left, bool) == isinstance(right, bool)


def schema_violations(value: Any, schema: dict[str, Any], path: str = "$") -> list[str]:
    unsupported = sorted(set(schema) - SUPPORTED_KEYWORDS - ANNOTATION_KEYWORDS)
    if unsupported:
        return [f"{path}: the checker does not support {', '.join(unsupported)}"]
    expected = schema.get("type")
    if expected is not None:
        allowed = expected if isinstance(expected, list) else [expected]
        if not any(_type_matches(value, name) for name in allowed):
            return [f"{path}: expected {' or '.join(allowed)}, found {json_type(value)}"]
    problems: list[str] = []
    if "enum" in schema and not any(_same_json(value, option) for option in schema["enum"]):
        problems.append(f"{path}: {value!r} is not one of {schema['enum']!r}")
    if "const" in schema and not _same_json(value, schema["const"]):
        problems.append(f"{path}: {value!r} is not {schema['const']!r}")
    if isinstance(value, str):
        problems.extend(_length_violations(path, len(value), schema, "minLength", "maxLength", "characters"))
    if isinstance(value, list):
        problems.extend(_length_violations(path, len(value), schema, "minItems", "maxItems", "items"))
        if isinstance(schema.get("items"), dict):
            for index, element in enumerate(value):
                problems.extend(schema_violations(element, schema["items"], f"{path}[{index}]"))
    if isinstance(value, dict):
        problems.extend(_object_violations(value, schema, path))
    return problems


def _length_violations(
    path: str, length: int, schema: dict[str, Any], low: str, high: str, unit: str
) -> list[str]:
    problems = []
    if low in schema and length < schema[low]:
        problems.append(f"{path}: {length} {unit}, at least {schema[low]} expected")
    if high in schema and length > schema[high]:
        problems.append(f"{path}: {length} {unit}, at most {schema[high]} expected")
    return problems


def _object_violations(value: dict[str, Any], schema: dict[str, Any], path: str) -> list[str]:
    properties = schema.get("properties") or {}
    problems = [f"{path}: missing {name!r}" for name in schema.get("required") or [] if name not in value]
    extra = schema.get("additionalProperties", True)
    for name, element in value.items():
        if name in properties:
            problems.extend(schema_violations(element, properties[name], f"{path}.{name}"))
        elif extra is False:
            problems.append(f"{path}: {name!r} is not allowed")
        elif isinstance(extra, dict):
            problems.extend(schema_violations(element, extra, f"{path}.{name}"))
    return problems


def check_reply(reply: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None, list[str]]:
    if reply.get("error"):
        return None, FAILURE_REQUEST, []
    content = reply.get("content")
    truncated = reply.get("finish_reason") == LENGTH_FINISH_REASON
    if not isinstance(content, str) or not content.strip():
        return None, FAILURE_TRUNCATED if truncated else FAILURE_EMPTY, []
    try:
        data = json.loads(content)
    except ValueError:
        return None, FAILURE_TRUNCATED if truncated else FAILURE_NOT_JSON, []
    if not isinstance(data, dict):
        return None, FAILURE_NOT_OBJECT, []
    schema = reply.get("schema")
    if not isinstance(schema, dict):
        return data, FAILURE_NO_SCHEMA, []
    violations = schema_violations(data, schema)
    return data, FAILURE_SCHEMA if violations else None, violations


def expected_status(item: dict[str, Any]) -> str:
    return STATUS_NOT_FOUND if item["category"] == "not_in_corpus" else STATUS_OK


def cited_titles(data: dict[str, Any] | None, sources_by_label: dict[str, Any] | None) -> list[str]:
    cited = (data or {}).get("sources")
    known = sources_by_label or {}
    titles: list[str] = []
    for label in cited if isinstance(cited, list) else []:
        source = known.get(label) if isinstance(label, str) else None
        title = source.get("title") if isinstance(source, dict) else None
        if isinstance(title, str) and title and title not in titles:
            titles.append(title)
    return titles


def thought_first(reply: dict[str, Any]) -> bool:
    content = reply.get("content")
    return bool(reply.get("reasoning_content")) or (
        isinstance(content, str) and content.lstrip().startswith(THINK_TAG)
    )


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def reply_timings(reply: dict[str, Any]) -> dict[str, Any]:
    usage = reply.get("usage") if isinstance(reply.get("usage"), dict) else {}
    timings = reply.get("timings") if isinstance(reply.get("timings"), dict) else {}
    return {
        "wall_s": _number(reply.get("wall_s")),
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": usage.get("completion_tokens"),
        "cached_tokens": timings.get("cache_n"),
        "prompt_n": timings.get("prompt_n"),
        "prompt_ms": _number(timings.get("prompt_ms")),
        "predicted_n": timings.get("predicted_n"),
        "predicted_ms": _number(timings.get("predicted_ms")),
        "prompt_tps": _rounded(timings.get("prompt_per_second")),
        "generation_tps": _rounded(timings.get("predicted_per_second")),
    }


def _rounded(value: Any) -> float | None:
    number = _number(value)
    return round(number, 2) if number is not None else None


def _scores(item: dict[str, Any], reply: dict[str, Any]) -> dict[str, Any]:
    if reply.get("error_stage") == ERROR_STAGE_RETRIEVAL:
        return {
            "json_valid": None,
            "failure": FAILURE_RETRIEVAL,
            "violations": [],
            "status": None,
            "status_correct": None,
            "answer": None,
            "blank_answer": False,
            "answer_correct_auto": None,
            "cited_sources": [],
            "source_correct_auto": None,
        }
    data, failure, violations = check_reply(reply)
    valid = failure is None
    status = data.get("status") if valid else None
    answer = data.get("answer") if valid else None
    titles = cited_titles(data if valid else None, reply.get("sources_by_label"))
    in_corpus = item["category"] != "not_in_corpus"
    return {
        "json_valid": valid,
        "failure": failure,
        "violations": violations,
        "status": status,
        "status_correct": status == expected_status(item),
        "answer": answer,
        "blank_answer": valid and not str(answer or "").strip(),
        "answer_correct_auto": answer_correct(item, answer) if valid else False,
        "cited_sources": titles,
        "source_correct_auto": source_check(item, cited_sources=titles)["source_correct_auto"]
        if in_corpus
        else None,
    }


def reply_record(item: dict[str, Any], reply: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": item["id"],
        "category": item["category"],
        "question": item["question"],
        "expected_status": expected_status(item),
        **_scores(item, reply),
        "error": reply.get("error"),
        "finish_reason": reply.get("finish_reason"),
        "thought_first": thought_first(reply),
        "labels": list(reply.get("labels") or []),
        "retrieved_titles": list(reply.get("retrieved_titles") or []),
        **reply_timings(reply),
        "content": reply.get("content"),
        "reasoning_chars": len(reply.get("reasoning_content") or ""),
    }


def _throughput(records: list[dict[str, Any]], tokens: str, milliseconds: str) -> float | None:
    counted = [r for r in records if r.get(tokens) and r.get(milliseconds)]
    total_ms = sum(r[milliseconds] for r in counted)
    return round(sum(r[tokens] for r in counted) * 1000.0 / total_ms, 2) if total_ms > 0 else None


def _rates(records: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "replies": len(records),
        "json_valid": rate([r["json_valid"] for r in records]),
        "status_correct": rate([r["status_correct"] for r in records]),
        "answer_correct_auto": rate([r["answer_correct_auto"] for r in records]),
        "source_correct_auto": rate([r["source_correct_auto"] for r in records]),
    }


def contract_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        **_rates(records),
        "failures": dict(Counter(r["failure"] for r in records if r["failure"])),
        "thought_first": sum(1 for r in records if r["thought_first"]),
        "truncated": sum(1 for r in records if r["finish_reason"] == LENGTH_FINISH_REASON),
        "blank_answers": sum(1 for r in records if r["blank_answer"]),
        "wall_s": stats([r["wall_s"] for r in records]),
        "prompt_tokens": stats([r["prompt_tokens"] for r in records]),
        "completion_tokens": stats([r["completion_tokens"] for r in records]),
        "prompt_tps": _throughput(records, "prompt_n", "prompt_ms"),
        "generation_tps": _throughput(records, "predicted_n", "predicted_ms"),
        "by_category": {
            category: _rates([r for r in records if r["category"] == category])
            for category in CATEGORIES
            if any(r["category"] == category for r in records)
        },
    }


def probe_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [item for item in items if item["category"] in PROBED_CATEGORIES]


def build_contract_report(
    *,
    label: str,
    run: dict[str, Any],
    model: dict[str, Any],
    llama_server: dict[str, Any] | None,
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "kind": REPORT_KIND,
        "schema_version": SCHEMA_VERSION,
        "label": label,
        "run": run,
        "model": model,
        "llama_server": llama_server,
        "summary": contract_summary(records),
        "replies": records,
    }
