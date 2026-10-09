import json
import math
import re

from llm_mock.call import Call

PIECE = re.compile(r"\s*\S+")
WORDS_PER_CHUNK = 3
OWNER = "horus-mock"


def tokens_in(chars: int) -> int:
    return math.ceil(chars / 4)


def usage(call: Call, content: str) -> dict:
    prompt = tokens_in(call.prompt_chars)
    completion_tokens = tokens_in(len(content))
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt + completion_tokens,
    }


def completion_id(call: Call) -> str:
    return f"chatcmpl-mock-{call.digest[:24]}"


def completion(call: Call, model: str, content: str) -> dict:
    return {
        "id": completion_id(call),
        "object": "chat.completion",
        "created": 0,
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": usage(call, content),
    }


def pieces(content: str) -> list[str]:
    words = PIECE.findall(content)
    chunks = ["".join(words[at:at + WORDS_PER_CHUNK]) for at in range(0, len(words), WORDS_PER_CHUNK)]
    rest = content[sum(len(word) for word in words):]
    if rest:
        chunks.append(rest)
    return chunks


def stream_events(call: Call, model: str, content: str) -> list[bytes]:
    base = {"id": completion_id(call), "object": "chat.completion.chunk", "created": 0,
            "model": model}
    events = [_chunk(base, {"role": "assistant", "content": ""}, None)]
    events += [_chunk(base, {"content": piece}, None) for piece in pieces(content)]
    events.append(_chunk(base, {}, "stop"))
    if call.include_usage:
        events.append({**base, "choices": [], "usage": usage(call, content)})
    return [sse(event) for event in events] + [b"data: [DONE]\n\n"]


def _chunk(base: dict, delta: dict, finish_reason: str | None) -> dict:
    return {**base, "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}]}


def sse(event: dict) -> bytes:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n".encode("utf-8")


def models(model: str) -> dict:
    return {
        "object": "list",
        "data": [{"id": model, "object": "model", "created": 0, "owned_by": OWNER}],
    }


def error_body(message: str, status: int) -> dict:
    kind = "server_error" if status >= 500 else "invalid_request_error"
    return {"error": {"message": message, "type": kind, "code": status}}
