# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import json
from typing import Any

LENGTH_FINISH_REASON = "length"
THINK_TAG = "<think"

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
LENGTH_KEYWORDS = ("minItems", "maxItems", "minLength", "maxLength")
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


def _whole(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _texts(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(entry, str) for entry in value)


def _malformed_keywords(schema: dict[str, Any]) -> list[str]:
    checks = {
        "type": lambda v: v is None or isinstance(v, str) or _texts(v),
        "enum": lambda v: isinstance(v, list),
        "required": lambda v: v is None or _texts(v),
        "properties": lambda v: v is None or isinstance(v, dict),
        "additionalProperties": lambda v: v is None or isinstance(v, (bool, dict)),
        "items": lambda v: v is None or isinstance(v, (bool, dict)),
        **dict.fromkeys(LENGTH_KEYWORDS, _whole),
    }
    return [name for name, valid in checks.items() if name in schema and not valid(schema[name])]


def schema_violations(value: Any, schema: Any, path: str = "$") -> list[str]:
    if schema is True:
        return []
    if schema is False:
        return [f"{path}: the schema allows no value here"]
    if not isinstance(schema, dict):
        return [f"{path}: the checker does not support a {json_type(schema)} schema"]
    unsupported = sorted(set(schema) - SUPPORTED_KEYWORDS - ANNOTATION_KEYWORDS)
    if unsupported:
        return [f"{path}: the checker does not support {', '.join(unsupported)}"]
    malformed = _malformed_keywords(schema)
    if malformed:
        return [f"{path}: the checker does not support {name} {schema[name]!r}" for name in malformed]
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
        if isinstance(schema.get("items"), (bool, dict)):
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


def thought_first(reply: dict[str, Any]) -> bool:
    content = reply.get("content")
    return bool(reply.get("reasoning_content")) or (
        isinstance(content, str) and content.lstrip().startswith(THINK_TAG)
    )


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _rounded(value: Any) -> float | None:
    number = _number(value)
    return round(number, 2) if number is not None else None


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


def throughput(records: list[dict[str, Any]], tokens: str, milliseconds: str) -> float | None:
    counted = [r for r in records if r.get(tokens) and r.get(milliseconds)]
    total_ms = sum(r[milliseconds] for r in counted)
    return round(sum(r[tokens] for r in counted) * 1000.0 / total_ms, 2) if total_ms > 0 else None
