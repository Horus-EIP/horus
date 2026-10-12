# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import asyncio
import json
import os
import time
import urllib.error
import urllib.request
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from horus_bench_kit.target import MODE_CHAT, STATUS_ERROR, STATUS_OK, STATUS_TIMEOUT, Outcome

SYSTEM_PROMPT = (
    "You answer questions about a set of documents. Use only the context you are given. "
    "If the context does not hold the answer, say so instead of guessing."
)
DEFAULT_API_KEY_ENV = "OPENAI_API_KEY"
ERROR_BODY_CHARS = 300
MAX_CONTEXT_CHARS = 200_000
TIMING_SOURCE = "http"


class ServerReplyError(ValueError):
    pass


@dataclass
class Reply:
    answer: str
    ttft_s: float | None
    usage: dict[str, Any] | None
    model: str | None


@dataclass
class OpenAITarget:
    base_url: str
    model: str
    api_key_env: str = DEFAULT_API_KEY_ENV
    system_prompt: str = SYSTEM_PROMPT
    max_tokens: int = 512
    temperature: float = 0.0
    timeout: float = 600.0
    stream: bool = True
    stream_usage: bool = True
    name: str = "openai"

    @property
    def endpoint(self) -> str:
        return self.base_url.rstrip("/") + "/chat/completions"

    def messages(self, question: str, files: Sequence[Path] = ()) -> list[dict[str, str]]:
        context = "\n\n".join(Path(path).read_text(encoding="utf-8") for path in files)[:MAX_CONTEXT_CHARS]
        user = f"Context:\n{context}\n\nQuestion: {question}" if context else question
        return [{"role": "system", "content": self.system_prompt}, {"role": "user", "content": user}]

    def payload(self, question: str, files: Sequence[Path] = ()) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": self.messages(question, files),
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "stream": self.stream,
        }
        if self.stream and self.stream_usage:
            body["stream_options"] = {"include_usage": True}
        return body

    def request(self, payload: dict[str, Any]) -> urllib.request.Request:
        headers = {"Content-Type": "application/json"}
        key = os.environ.get(self.api_key_env)
        if key:
            headers["Authorization"] = f"Bearer {key}"
        return urllib.request.Request(
            self.endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )

    def ask_blocking(self, question: str, files: Sequence[Path] = ()) -> Outcome:
        outcome: Outcome = {"mode": MODE_CHAT, "status": STATUS_ERROR, "timing_source": TIMING_SOURCE}
        started = time.perf_counter()
        try:
            with urllib.request.urlopen(self.request(self.payload(question, files)), timeout=self.timeout) as response:
                if self.stream:
                    reply = read_stream(response, started)
                else:
                    reply = read_body(json.loads(response.read().decode("utf-8")))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:ERROR_BODY_CHARS]
            outcome["error"] = f"HTTP {exc.code}: {detail}"
            return outcome
        except (urllib.error.URLError, OSError, ValueError) as exc:
            outcome["error"] = f"{type(exc).__name__}: {exc}"
            if timed_out(exc):
                outcome["status"] = STATUS_TIMEOUT
            return outcome
        outcome.update(
            status=STATUS_OK,
            error=None,
            answer=reply.answer,
            ttft_s=reply.ttft_s,
            total_s=round(time.perf_counter() - started, 3),
            usage=reply.usage,
            models=[reply.model] if reply.model else [],
        )
        return outcome

    async def ask(self, question: str, *, item_id: str, files: Sequence[Path] = ()) -> Outcome:
        return await asyncio.to_thread(self.ask_blocking, question, files)


def timed_out(exc: BaseException) -> bool:
    reason = getattr(exc, "reason", None)
    return isinstance(exc, TimeoutError) or isinstance(reason, TimeoutError)


def unexpected(what: str, value: Any) -> ServerReplyError:
    return ServerReplyError(f"unexpected {what}: {json.dumps(value, ensure_ascii=False)[:ERROR_BODY_CHARS]}")


def is_object_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(entry, dict) for entry in value)


def text_or_none(value: Any) -> bool:
    return value is None or isinstance(value, str)


def read_body(body: Any) -> Reply:
    if not isinstance(body, dict):
        raise unexpected("reply", body)
    if body.get("error"):
        raise ServerReplyError(f"server error: {json.dumps(body['error'])[:ERROR_BODY_CHARS]}")
    choices = body.get("choices") or [{}]
    if not is_object_list(choices):
        raise unexpected("choices", choices)
    message = choices[0].get("message") or {}
    if not isinstance(message, dict) or not text_or_none(message.get("content")):
        raise unexpected("message", message)
    return Reply(message.get("content") or "", None, body.get("usage"), body.get("model"))


def read_stream(lines: Iterable[bytes], started: float) -> Reply:
    parts: list[str] = []
    ttft = usage = model = None
    streamed = False
    for raw in lines:
        line = raw.decode("utf-8").strip()
        if not line.startswith("data:"):
            continue
        streamed = True
        data = line[5:].strip()
        if data == "[DONE]":
            break
        chunk = json.loads(data)
        if not isinstance(chunk, dict):
            raise unexpected("stream chunk", chunk)
        if chunk.get("error"):
            raise ServerReplyError(f"server error: {json.dumps(chunk['error'])[:ERROR_BODY_CHARS]}")
        model = chunk.get("model") or model
        usage = chunk.get("usage") or usage
        choices = chunk.get("choices") or []
        deltas = [choice.get("delta") or {} for choice in choices] if is_object_list(choices) else None
        if deltas is None or not is_object_list(deltas) or not all(text_or_none(d.get("content")) for d in deltas):
            raise unexpected("stream chunk", chunk)
        for delta in deltas:
            if ttft is None and (delta.get("content") or delta.get("reasoning_content")):
                ttft = round(time.perf_counter() - started, 3)
            if delta.get("content"):
                parts.append(delta["content"])
    if not streamed:
        raise ServerReplyError("the reply has no 'data:' lines: the server did not stream it; try --no-stream")
    return Reply("".join(parts), ttft, usage, model)
