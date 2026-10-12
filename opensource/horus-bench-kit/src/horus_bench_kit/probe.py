# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import http.client
import json
import os
import re
import shlex
import time
import urllib.error
import urllib.request
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from horus_bench_kit.contract import (
    FAILURE_REQUEST,
    FAILURE_RETRIEVAL,
    LENGTH_FINISH_REASON,
    check_reply,
    reply_timings,
    thought_first,
    throughput,
)
from horus_bench_kit.files import load_data
from horus_bench_kit.scoring import compile_pattern, normalize_answer
from horus_bench_kit.stats import rate, stats

REPORT_KIND = "horus-contract-probe"
SCHEMA_VERSION = 1
PROTOCOL_VERSION = 1
ERROR_STAGE_RETRIEVAL = "retrieval"
ERROR_STAGE_LLM = "llm"
ERROR_BODY_CHARS = 300
SCHEMA_NAME = "reply"
JOB_ITEM_FIELDS = ("id", "question", "context")
META_FIELDS = ("labels", "sources_by_label", "retrieved_titles")
CONTEXT_SUFFIX = ".txt"
REQUEST_ERRORS = (OSError, ValueError, RuntimeError, http.client.HTTPException)

_PLACEHOLDER = re.compile(r"\{(question|context)\}")

Post = Callable[[str, dict[str, Any], float, dict[str, str]], dict[str, Any]]


def load_items(path: Path | str) -> list[Any]:
    path = Path(path)
    if path.suffix.lower() == ".jsonl":
        lines = path.read_text(encoding="utf-8").splitlines()
        return [json.loads(line) for line in lines if line.strip()]
    data = load_data(path, "probe item file")
    return data.get("items") if isinstance(data, dict) else data


def _pattern_problems(label: str, patterns: Any) -> list[str]:
    if not isinstance(patterns, dict) or not patterns:
        return [f"{label}: patterns must map field names to lists of regular expressions"]
    problems = []
    for name, values in patterns.items():
        if not isinstance(values, list) or not values or not all(isinstance(v, str) and v for v in values):
            problems.append(f"{label}: patterns.{name} must be a non-empty list of regular expressions")
            continue
        for value in values:
            try:
                compile_pattern(value)
            except re.error as exc:
                problems.append(f"{label}: patterns.{name} {value!r} is not a valid regular expression: {exc}")
    return problems


def item_problems(items: Any, *, prepared: bool = False) -> list[str]:
    if not isinstance(items, list) or not items:
        return ["the file holds no items: give a non-empty list, or an object with an items list"]
    problems = []
    seen: set[str] = set()
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            problems.append(f"item {index + 1} must be an object")
            continue
        label = f"item {item.get('id') or index + 1}"
        if not isinstance(item.get("id"), str) or not item["id"].strip():
            problems.append(f"{label}: id must be a non-empty string")
        elif item["id"] in seen:
            problems.append(f"{label}: the id is used twice")
        else:
            seen.add(item["id"])
        if prepared:
            if not isinstance(item.get("payload"), dict) or not isinstance(item["payload"].get("messages"), list):
                problems.append(f"{label}: payload must be a chat completion request with messages")
        elif not isinstance(item.get("question"), str) or not item["question"].strip():
            problems.append(f"{label}: question must be a non-empty string")
        for name in ("category", "context", "context_file", "question"):
            if name in item and not isinstance(item[name], str):
                problems.append(f"{label}: {name} must be a string")
        if "expected" in item and (not isinstance(item["expected"], dict) or not item["expected"]):
            problems.append(f"{label}: expected must map field names to values")
        if "patterns" in item:
            problems.extend(_pattern_problems(label, item["patterns"]))
    return problems


def select_probe_items(
    items: list[dict[str, Any]],
    ids: Sequence[str] | None = None,
    categories: Sequence[str] | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    selected = [
        item
        for item in items
        if (not ids or item["id"] in ids) and (not categories or item.get("category") in categories)
    ]
    return selected[:limit] if limit else selected


def response_format_for(schema: dict[str, Any], name: str = SCHEMA_NAME) -> dict[str, Any]:
    return {"type": "json_schema", "json_schema": {"name": name, "strict": True, "schema": schema}}


def response_schema(response_format: Any) -> dict[str, Any] | None:
    if not isinstance(response_format, dict):
        return None
    nested = response_format.get("json_schema")
    if isinstance(nested, dict) and isinstance(nested.get("schema"), dict):
        return nested["schema"]
    flat = response_format.get("schema")
    return flat if isinstance(flat, dict) else None


def render_user(template: str, question: str, context: str) -> str:
    values = {"question": question, "context": context}
    return _PLACEHOLDER.sub(lambda match: values[match.group(1)], template)


def completion_payload(
    model: str,
    system: str,
    user: str,
    max_tokens: int,
    response_format: dict[str, Any],
    temperature: float = 0.0,
) -> dict[str, Any]:
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": False,
        "response_format": response_format,
    }


@dataclass(frozen=True)
class Template:
    system: str
    user: str
    response_format: dict[str, Any]
    max_tokens: int = 512
    temperature: float = 0.0

    @property
    def schema(self) -> dict[str, Any] | None:
        return response_schema(self.response_format)

    def payload(self, model: str, question: str, context: str = "") -> dict[str, Any]:
        user = render_user(self.user, question, context)
        return completion_payload(model, self.system, user, self.max_tokens, self.response_format, self.temperature)


def load_template(
    system_path: Path | str,
    user_path: Path | str,
    *,
    schema_path: Path | str | None = None,
    response_format_path: Path | str | None = None,
    max_tokens: int = 512,
    temperature: float = 0.0,
) -> Template:
    if response_format_path:
        response_format = json.loads(Path(response_format_path).read_text(encoding="utf-8"))
        if response_schema(response_format) is None:
            raise ValueError(
                "the response format holds no JSON schema: give type json_schema with json_schema.schema, "
                "or a schema key"
            )
    else:
        schema = json.loads(Path(schema_path).read_text(encoding="utf-8"))
        if not isinstance(schema, dict):
            raise ValueError("the schema file must hold a JSON object")
        response_format = response_format_for(schema)
    user = Path(user_path).read_text(encoding="utf-8")
    if "{question}" not in user:
        raise ValueError("the user template has no {question} placeholder")
    return Template(
        system=Path(system_path).read_text(encoding="utf-8"),
        user=user,
        response_format=response_format,
        max_tokens=max_tokens,
        temperature=temperature,
    )


def item_context(item: dict[str, Any], base: Path, context_dir: Path | str | None = None) -> str:
    if isinstance(item.get("context"), str):
        return item["context"]
    if item.get("context_file"):
        return (base / item["context_file"]).read_text(encoding="utf-8")
    if context_dir:
        candidate = Path(context_dir) / f"{item['id']}{CONTEXT_SUFFIX}"
        if candidate.is_file():
            return candidate.read_text(encoding="utf-8")
    return ""


def context_problems(items: list[dict[str, Any]], base: Path) -> list[str]:
    return [
        f"item {item['id']}: context_file {item['context_file']!r} does not exist"
        for item in items
        if item.get("context_file") and not (base / item["context_file"]).is_file()
    ]


def chat_url(base_url: str) -> str:
    return base_url.rstrip("/") + "/chat/completions"


def api_headers(api_key_env: str | None) -> dict[str, str]:
    key = os.environ.get(api_key_env) if api_key_env else None
    return {"Authorization": f"Bearer {key}"} if key else {}


def post_json(url: str, payload: dict[str, Any], timeout: float, headers: dict[str, str] | None = None) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **(headers or {})},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:ERROR_BODY_CHARS]
        raise RuntimeError(f"HTTP {exc.code}: {body}") from exc


def reply_from_response(body: dict[str, Any], wall_s: float) -> dict[str, Any]:
    choices = body.get("choices") if isinstance(body, dict) else None
    choice = choices[0] if isinstance(choices, list) and choices else {}
    message = choice.get("message") if isinstance(choice.get("message"), dict) else {}
    return {
        "content": message.get("content"),
        "reasoning_content": message.get("reasoning_content"),
        "finish_reason": choice.get("finish_reason"),
        "usage": body.get("usage"),
        "timings": body.get("timings"),
        "wall_s": round(wall_s, 3),
    }


def http_reply(
    item_id: str,
    url: str,
    payload: dict[str, Any],
    timeout: float,
    *,
    headers: dict[str, str] | None = None,
    meta: dict[str, Any] | None = None,
    post: Post = post_json,
    clock: Callable[[], float] = time.perf_counter,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "id": item_id,
        **(meta or {}),
        "schema": response_schema(payload.get("response_format")),
        "max_tokens": payload.get("max_tokens"),
    }
    started = clock()
    try:
        body = post(url, payload, timeout, headers or {})
    except REQUEST_ERRORS as exc:
        return {
            **record,
            "error_stage": ERROR_STAGE_LLM,
            "error": f"{type(exc).__name__}: {exc}",
            "wall_s": round(clock() - started, 3),
        }
    return {**record, **reply_from_response(body, clock() - started)}


def reply_line(index: int, total: int, reply: dict[str, Any]) -> str:
    return f"[{index:3}/{total}] {reply['id']} {reply.get('error') or reply.get('finish_reason')}"


def run_template_probe(
    items: list[dict[str, Any]],
    template: Template,
    *,
    model: str,
    url: str,
    timeout: float,
    base: Path,
    context_dir: Path | str | None = None,
    warmup: str | None = None,
    headers: dict[str, str] | None = None,
    post: Post = post_json,
    progress: Callable[[str], None] = print,
) -> dict[str, dict[str, Any]]:
    if warmup:
        progress(f"[info] warmup (not scored): {warmup}")
        http_reply("warmup", url, template.payload(model, warmup), timeout, headers=headers, post=post)
    replies = {}
    for index, item in enumerate(items, 1):
        payload = template.payload(model, item["question"], item_context(item, base, context_dir))
        replies[item["id"]] = http_reply(item["id"], url, payload, timeout, headers=headers, post=post)
        progress(reply_line(index, len(items), replies[item["id"]]))
    return replies


def prepared_question(request: dict[str, Any]) -> str:
    if isinstance(request.get("question"), str):
        return request["question"]
    users = [m.get("content") for m in request["payload"]["messages"] if isinstance(m, dict) and m.get("role") == "user"]
    return users[-1] if users and isinstance(users[-1], str) else ""


def prepared_items(requests: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{**request, "question": prepared_question(request)} for request in requests]


def run_prepared_probe(
    requests: list[dict[str, Any]],
    *,
    url: str,
    timeout: float,
    model: str | None = None,
    headers: dict[str, str] | None = None,
    post: Post = post_json,
    progress: Callable[[str], None] = print,
) -> dict[str, dict[str, Any]]:
    replies = {}
    for index, request in enumerate(requests, 1):
        payload = {**request["payload"], **({"model": model} if model else {})}
        meta = request.get("meta") if isinstance(request.get("meta"), dict) else {}
        kept = {name: meta[name] for name in META_FIELDS if name in meta}
        replies[request["id"]] = http_reply(request["id"], url, payload, timeout, headers=headers, meta=kept, post=post)
        progress(reply_line(index, len(requests), replies[request["id"]]))
    return replies


def probe_job(items: Iterable[dict[str, Any]], warmup: str | None = None) -> dict[str, Any]:
    return {
        "items": [{key: item[key] for key in JOB_ITEM_FIELDS if key in item} for item in items],
        "warmup": warmup,
    }


def read_reply_lines(lines: Iterable[str]) -> dict[str, dict[str, Any]]:
    replies = {}
    for line in lines:
        try:
            reply = json.loads(line)
        except ValueError:
            continue
        if isinstance(reply, dict) and reply.get("id"):
            replies[reply["id"]] = reply
    return replies


def split_command(text: str) -> list[str]:
    stripped = text.strip()
    if stripped.startswith("["):
        command = json.loads(stripped)
        if not isinstance(command, list) or not command or not all(isinstance(part, str) for part in command):
            raise ValueError("a command given as JSON must be a non-empty list of strings")
        return command
    command = shlex.split(stripped)
    if not command:
        raise ValueError("the command is empty")
    return command


def same_value(found: Any, wanted: Any) -> bool:
    return found == wanted and isinstance(found, bool) == isinstance(wanted, bool)


def field_text(value: Any) -> str | None:
    if value is None:
        return None
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


def missing_field_patterns(patterns: dict[str, list[str]], data: dict[str, Any]) -> dict[str, list[str]]:
    missing = {}
    for name, field_patterns in patterns.items():
        text = field_text(data.get(name))
        misses = [
            pattern
            for pattern in field_patterns
            if text is None or not compile_pattern(pattern).search(normalize_answer(text))
        ]
        if misses:
            missing[name] = misses
    return missing


def expected_head(item: dict[str, Any]) -> dict[str, Any]:
    return {"expected": item.get("expected")}


def expected_scores(item: dict[str, Any], reply: dict[str, Any]) -> dict[str, Any]:
    expected = item.get("expected")
    patterns = item.get("patterns")
    if reply.get("error_stage") == ERROR_STAGE_RETRIEVAL:
        return {
            "json_valid": None,
            "failure": FAILURE_RETRIEVAL,
            "violations": [],
            "expected_correct": None,
            "patterns_correct": None,
            "missing_patterns": None,
        }
    data, failure, violations = check_reply(reply)
    valid = failure is None
    found = data if valid and data is not None else {}
    missing = missing_field_patterns(patterns, found) if patterns else None
    return {
        "json_valid": valid,
        "failure": failure,
        "violations": violations,
        "expected_correct": valid and all(same_value(found.get(k), v) for k, v in expected.items())
        if expected
        else None,
        "patterns_correct": valid and not missing if patterns else None,
        "missing_patterns": missing,
    }


def no_counts(_records: list[dict[str, Any]]) -> dict[str, Any]:
    return {}


@dataclass(frozen=True)
class ContractProfile:
    kind: str = REPORT_KIND
    schema_version: int = SCHEMA_VERSION
    head: Callable[[dict[str, Any]], dict[str, Any]] = expected_head
    scores: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]] = expected_scores
    rate_fields: tuple[str, ...] = ("json_valid", "expected_correct", "patterns_correct")
    counts: Callable[[list[dict[str, Any]]], dict[str, Any]] = no_counts
    categories: tuple[str, ...] | None = None


DEFAULT_PROFILE = ContractProfile()


def reply_record(
    item: dict[str, Any], reply: dict[str, Any], profile: ContractProfile = DEFAULT_PROFILE
) -> dict[str, Any]:
    return {
        "id": item["id"],
        "category": item.get("category"),
        "question": item["question"],
        **profile.head(item),
        **profile.scores(item, reply),
        "error": reply.get("error"),
        "finish_reason": reply.get("finish_reason"),
        "thought_first": thought_first(reply),
        "labels": list(reply.get("labels") or []),
        "retrieved_titles": list(reply.get("retrieved_titles") or []),
        **reply_timings(reply),
        "content": reply.get("content"),
        "reasoning_chars": len(reply.get("reasoning_content") or ""),
    }


def probe_records(
    items: list[dict[str, Any]],
    replies: dict[str, dict[str, Any]],
    profile: ContractProfile = DEFAULT_PROFILE,
) -> list[dict[str, Any]]:
    return [reply_record(item, replies[item["id"]], profile) for item in items if item["id"] in replies]


def _rates(records: list[dict[str, Any]], profile: ContractProfile) -> dict[str, Any]:
    return {
        "replies": len(records),
        **{name: rate([r[name] for r in records]) for name in profile.rate_fields},
    }


def summary_categories(records: list[dict[str, Any]], profile: ContractProfile) -> list[str]:
    if profile.categories is not None:
        return [category for category in profile.categories if any(r["category"] == category for r in records)]
    return list(dict.fromkeys(r["category"] for r in records if isinstance(r.get("category"), str)))


def contract_summary(records: list[dict[str, Any]], profile: ContractProfile = DEFAULT_PROFILE) -> dict[str, Any]:
    return {
        **_rates(records, profile),
        "failures": dict(Counter(r["failure"] for r in records if r["failure"])),
        "thought_first": sum(1 for r in records if r["thought_first"]),
        "truncated": sum(1 for r in records if r["finish_reason"] == LENGTH_FINISH_REASON),
        **profile.counts(records),
        "wall_s": stats([r["wall_s"] for r in records]),
        "prompt_tokens": stats([r["prompt_tokens"] for r in records]),
        "completion_tokens": stats([r["completion_tokens"] for r in records]),
        "prompt_tps": throughput(records, "prompt_n", "prompt_ms"),
        "generation_tps": throughput(records, "predicted_n", "predicted_ms"),
        "by_category": {
            category: _rates([r for r in records if r["category"] == category], profile)
            for category in summary_categories(records, profile)
        },
    }


def build_contract_report(
    *,
    label: str,
    run: dict[str, Any],
    model: dict[str, Any],
    llama_server: dict[str, Any] | None,
    records: list[dict[str, Any]],
    profile: ContractProfile = DEFAULT_PROFILE,
) -> dict[str, Any]:
    return {
        "kind": profile.kind,
        "schema_version": profile.schema_version,
        "label": label,
        "run": run,
        "model": model,
        "llama_server": llama_server,
        "summary": contract_summary(records, profile),
        "replies": records,
    }


def answered(records: list[dict[str, Any]]) -> bool:
    return any(record["failure"] != FAILURE_REQUEST for record in records)
