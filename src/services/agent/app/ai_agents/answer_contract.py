from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from ai_agents.decision_making_agent import (
    DEGENERATE_OUTPUT_FALLBACK,
    _is_degenerate_output,
    _max_context_chars,
    _normalize_model_text,
)
from ai_agents.knowledge_store_client import format_passage

logger = logging.getLogger(__name__)

ANSWER_SCHEMA_NAME = "agent_answer"
SOURCE_LABEL_PREFIX = "S"
CONTEXT_TRUNCATED_MARK = "\n…[retrieved content truncated]"
NOT_IN_DOCUMENTS_ANSWER = "The documents don't contain this information."
UNREADABLE_ANSWER = (
    "The model's answer could not be read, so this request was not answered."
)

REASON_NOT_IN_DOCUMENTS = "not_in_documents"
REASON_INVALID_OUTPUT = "invalid_output"
REASON_DEGENERATE_OUTPUT = "degenerate_output"
REASON_RETRIEVAL_ERROR = "retrieval_error"


class AnswerStatus(str, Enum):
    OK = "ok"
    NOT_FOUND = "not_found"
    FAILED = "failed"


MODEL_STATUSES = (AnswerStatus.OK, AnswerStatus.NOT_FOUND)

_LENIENT_STATUSES = {
    "ok": AnswerStatus.OK,
    "found": AnswerStatus.OK,
    "answered": AnswerStatus.OK,
    "success": AnswerStatus.OK,
    "not_found": AnswerStatus.NOT_FOUND,
    "notfound": AnswerStatus.NOT_FOUND,
    "not_in_documents": AnswerStatus.NOT_FOUND,
    "missing": AnswerStatus.NOT_FOUND,
    "none": AnswerStatus.NOT_FOUND,
}

_REFUSAL = re.compile(
    "|".join(
        (
            r"\b(?:does|do)(?: not|n't) (?:contain|include|have|mention|provide) "
            r"(?:this|that|the requested|any|enough) information\b",
            r"\b(?:is|are)(?: not|n't) covered in the (?:current|retrieved|provided)\b",
            r"\bno (?:relevant )?information (?:about|on|regarding)\b",
            r"\bi(?: cannot| can't| am unable to|'m unable to) (?:answer|find|provide|determine)\b",
            r"^(?:i'm|i am) sorry\b",
        )
    )
)
_FENCED_JSON = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)
_TRAILING_COMMA = re.compile(r",\s*([}\]])")
_ANSWER_FIELD_START = re.compile(r'"answer"\s*:\s*"')
_JSON_ESCAPES = {
    '"': '"',
    "\\": "\\",
    "/": "/",
    "b": "\b",
    "f": "\f",
    "n": "\n",
    "r": "\r",
    "t": "\t",
}
_UNICODE_ESCAPE_LENGTH = 6
_HIGH_SURROGATES = range(0xD800, 0xDC00)


@dataclass
class AgentAnswer:
    status: AnswerStatus
    answer: str
    sources: list[dict[str, Any]] = field(default_factory=list)
    reason: str | None = None

    @classmethod
    def ok(cls, answer: str, sources: Iterable[dict[str, Any]] = ()) -> AgentAnswer:
        return cls(AnswerStatus.OK, answer, [dict(source) for source in sources])

    @classmethod
    def not_found(cls, answer: str = NOT_IN_DOCUMENTS_ANSWER) -> AgentAnswer:
        return cls(AnswerStatus.NOT_FOUND, answer, [], REASON_NOT_IN_DOCUMENTS)

    @classmethod
    def failed(cls, reason: str, answer: str) -> AgentAnswer:
        return cls(AnswerStatus.FAILED, answer, [], reason)

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "answer": self.answer,
            "sources": [dict(source) for source in self.sources],
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AgentAnswer:
        sources = data.get("sources") or []
        return cls(
            AnswerStatus(data.get("status") or AnswerStatus.OK.value),
            _as_text(data.get("answer")),
            [dict(source) for source in sources if isinstance(source, dict)],
            data.get("reason") or None,
        )


def answer_of(result: Any) -> AgentAnswer:
    if isinstance(result, AgentAnswer):
        return result
    if isinstance(result, dict):
        contract = result.get("agent_answer")
        if isinstance(contract, dict):
            return AgentAnswer.from_dict(contract)
        return AgentAnswer.ok(_as_text(result.get("response")))
    return AgentAnswer.ok(_as_text(result))


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    return value if isinstance(value, str) else str(value)


def looks_like_refusal(text: str) -> bool:
    return _REFUSAL.search(text.lower().replace("\u2019", "'")) is not None


def source_label(index: int) -> str:
    return f"{SOURCE_LABEL_PREFIX}{index}"


def _text_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _page_or_none(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def source_record(passage: dict[str, Any]) -> dict[str, Any]:
    return {
        "doc_id": _text_or_none(passage.get("doc_id")),
        "chunk_id": _text_or_none(passage.get("chunk_id")),
        "title": _text_or_none(passage.get("title")),
        "page": _page_or_none(passage.get("page")),
    }


class SourceCatalog:
    def __init__(self) -> None:
        self._records: dict[str, dict[str, Any]] = {}
        self._labels_by_chunk: dict[str, str] = {}

    def __len__(self) -> int:
        return len(self._records)

    @property
    def labels(self) -> list[str]:
        return list(self._records)

    @property
    def next_label(self) -> str:
        return source_label(len(self._records) + 1)

    def add(self, passage: dict[str, Any]) -> str:
        label = self.next_label
        record = source_record(passage)
        self._records[label] = record
        if record["chunk_id"]:
            self._labels_by_chunk.setdefault(record["chunk_id"], label)
        return label

    def add_attached_files(self, files: Iterable[dict[str, Any]]) -> None:
        for attached in files:
            self.add({"doc_id": attached.get("doc_id"), "title": attached.get("filename")})

    def format_passages(self, passages: Iterable[Any], budget: int) -> str:
        blocks: list[str] = []
        used = 0
        for passage in passages:
            if not isinstance(passage, dict):
                continue
            block = format_passage(passage, label=self.next_label)
            room = budget - used - (2 if blocks else 0)
            if len(block) > room:
                if blocks:
                    break
                block = block[: max(room, 0)] + CONTEXT_TRUNCATED_MARK
            self.add(passage)
            used += len(block) + (2 if blocks else 0)
            blocks.append(block)
        return "\n\n".join(blocks)

    def cite(self, cited: Any) -> list[dict[str, Any]]:
        if isinstance(cited, (str, dict)):
            cited = [cited]
        if not isinstance(cited, list):
            return []
        sources: list[dict[str, Any]] = []
        seen: set[str] = set()
        dropped: list[Any] = []
        for item in cited:
            label = self._label_for(item)
            if label is None:
                dropped.append(item)
                continue
            if label in seen:
                continue
            seen.add(label)
            sources.append(dict(self._records[label]))
        if dropped:
            logger.info("Dropped %d cited source(s) that were not retrieved: %r", len(dropped), dropped)
        return sources

    def _label_for(self, item: Any) -> str | None:
        if isinstance(item, dict):
            item = item.get("label") or item.get("chunk_id") or item.get("id")
        if not isinstance(item, str):
            return None
        key = item.strip().strip("[]").strip()
        if key.upper() in self._records:
            return key.upper()
        return self._labels_by_chunk.get(key)


def answer_schema(labels: Sequence[str]) -> dict[str, Any]:
    properties: dict[str, Any] = {
        "status": {"type": "string", "enum": [status.value for status in MODEL_STATUSES]},
        "answer": {"type": "string"},
    }
    required = ["status", "answer"]
    if labels:
        properties["sources"] = {
            "type": "array",
            "items": {"type": "string", "enum": list(labels)},
        }
        required.append("sources")
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def answer_response_format(labels: Sequence[str]) -> dict[str, Any]:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": ANSWER_SCHEMA_NAME,
            "strict": True,
            "schema": answer_schema(labels),
        },
    }


def _answer_rules(with_sources: bool) -> str:
    shape = (
        '{"status": "ok", "answer": "...", "sources": ["S1"]}'
        if with_sources
        else '{"status": "ok", "answer": "..."}'
    )
    lines = [
        "You answer one request from the passages you are given.",
        f"Reply with one JSON object and nothing else, keys in this order: {shape}",
        'status: "ok" when the passages contain what the request asks for, '
        '"not_found" when they do not.',
        'answer: for "ok", a short answer to that request only, in your own words, '
        'in Markdown; for "not_found", one sentence saying the documents do not '
        "contain it.",
    ]
    if with_sources:
        lines.append(
            'sources: the labels of the passages your answer uses, such as "S1"; '
            '[] for "not_found".'
        )
    lines.append(
        "Use only the passages. Never invent a fact. State each figure once and "
        "never correct yourself: no 'wait', 'no', 'actually' or 'correction'."
    )
    return "\n".join(lines)


def _capped_context(context: str) -> str:
    cap = _max_context_chars()
    if len(context) > cap:
        return context[:cap] + CONTEXT_TRUNCATED_MARK
    return context


def answer_prompt(request: str, context: str, labels: Sequence[str]) -> tuple[str, str]:
    passages = _capped_context(context or "").strip() or "(no passages)"
    user_content = (
        f"Request: {request}\n\n"
        f"Passages:\n{passages}\n\n"
        f"Answer this request with the JSON object: {request}"
    )
    return _answer_rules(bool(labels)), user_content


def _strict_object(raw: str) -> dict[str, Any] | None:
    try:
        value = json.loads(raw.strip())
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def _lenient_object(raw: str) -> dict[str, Any] | None:
    text = raw.strip()
    fenced = _FENCED_JSON.search(text)
    if fenced:
        text = fenced.group(1).strip()
    start = text.find("{")
    if start < 0:
        return None
    decoder = json.JSONDecoder(strict=False)
    body = text[start:]
    for candidate in (body, _TRAILING_COMMA.sub(r"\1", body)):
        try:
            value, _end = decoder.raw_decode(candidate)
        except ValueError:
            continue
        return value if isinstance(value, dict) else None
    return None


def _model_status(value: Any, strict: bool) -> AnswerStatus | None:
    if not isinstance(value, str):
        return None
    if strict:
        return next((status for status in MODEL_STATUSES if status.value == value), None)
    key = re.sub(r"[\s-]+", "_", value.strip().lower())
    return _LENIENT_STATUSES.get(key)


def _unreadable(raw: str) -> AgentAnswer:
    if _is_degenerate_output(_normalize_model_text(raw)):
        return AgentAnswer.failed(REASON_DEGENERATE_OUTPUT, DEGENERATE_OUTPUT_FALLBACK)
    return AgentAnswer.failed(REASON_INVALID_OUTPUT, UNREADABLE_ANSWER)


def parse_answer(raw: str, catalog: SourceCatalog, *, strict: bool) -> AgentAnswer:
    raw = raw if isinstance(raw, str) else ""
    data = _strict_object(raw) if strict else _lenient_object(raw)
    if data is None:
        return _unreadable(raw)
    status = _model_status(data.get("status"), strict)
    answer = data.get("answer")
    if status is None or not isinstance(answer, str):
        return _unreadable(raw)
    answer = _normalize_model_text(answer).strip()
    if _is_degenerate_output(answer):
        return AgentAnswer.failed(REASON_DEGENERATE_OUTPUT, DEGENERATE_OUTPUT_FALLBACK)
    if status is AnswerStatus.NOT_FOUND:
        return AgentAnswer.not_found(answer or NOT_IN_DOCUMENTS_ANSWER)
    if not answer:
        return AgentAnswer.failed(REASON_INVALID_OUTPUT, UNREADABLE_ANSWER)
    sources = catalog.cite(data.get("sources"))
    if not sources and looks_like_refusal(answer):
        return AgentAnswer.not_found(answer)
    return AgentAnswer.ok(answer, sources)


class AnswerFieldStream:
    def __init__(self) -> None:
        self._raw = ""
        self._cursor: int | None = None
        self._closed = False

    def feed(self, piece: str) -> str:
        if self._closed or not piece:
            return ""
        self._raw += piece
        if self._cursor is None:
            start = _ANSWER_FIELD_START.search(self._raw)
            if start is None:
                return ""
            self._cursor = start.end()
        return self._decode()

    def _decode(self) -> str:
        raw = self._raw
        index = self._cursor or 0
        decoded: list[str] = []
        while index < len(raw):
            char = raw[index]
            if char == '"':
                self._closed = True
                index += 1
                break
            if char != "\\":
                decoded.append(char)
                index += 1
                continue
            if index + 1 >= len(raw):
                break
            code = raw[index + 1]
            if code != "u":
                decoded.append(_JSON_ESCAPES.get(code, code))
                index += 2
                continue
            escape = self._unicode_escape(raw, index)
            if escape is None:
                break
            text, length = escape
            decoded.append(text)
            index += length
        self._cursor = index
        return "".join(decoded)

    @staticmethod
    def _unicode_escape(raw: str, index: int) -> tuple[str, int] | None:
        end = index + _UNICODE_ESCAPE_LENGTH
        if end > len(raw):
            return None
        try:
            unit = int(raw[index + 2 : end], 16)
        except ValueError:
            return raw[index:end], _UNICODE_ESCAPE_LENGTH
        length = _UNICODE_ESCAPE_LENGTH
        if unit in _HIGH_SURROGATES:
            if end + _UNICODE_ESCAPE_LENGTH > len(raw):
                return None
            if raw[end : end + 2] == "\\u":
                length = 2 * _UNICODE_ESCAPE_LENGTH
        try:
            return json.loads(f'"{raw[index : index + length]}"'), length
        except ValueError:
            return raw[index : index + length], length
