import hashlib
import math
from collections import Counter
from dataclasses import dataclass
from itertools import pairwise

from llm_mock.call import BadRequest
from llm_mock.completions import tokens_in
from llm_mock.words import words

DEFAULT_DIMENSIONS = 768
MAX_DIMENSIONS = 8192
MAX_INPUTS = 2048
EMPTY_FEATURE = "empty:"


@dataclass(frozen=True)
class EmbeddingRequest:
    texts: tuple[str, ...]
    dimensions: int
    model: str

    @classmethod
    def from_body(cls, body: object) -> "EmbeddingRequest":
        if not isinstance(body, dict):
            raise BadRequest("the request body must be a JSON object")
        raw = body.get("input")
        texts = [raw] if isinstance(raw, str) else raw
        if not isinstance(texts, list) or not texts:
            raise BadRequest("input must be a string or a non-empty list of strings")
        if not all(isinstance(text, str) for text in texts):
            raise BadRequest("every input must be a string")
        if len(texts) > MAX_INPUTS:
            raise BadRequest(f"at most {MAX_INPUTS} inputs per request")
        if body.get("encoding_format", "float") != "float":
            raise BadRequest("only encoding_format float is served")
        dimensions = body.get("dimensions", DEFAULT_DIMENSIONS)
        if isinstance(dimensions, bool) or not isinstance(dimensions, int) or not (
            1 <= dimensions <= MAX_DIMENSIONS
        ):
            raise BadRequest(f"dimensions must be a whole number from 1 to {MAX_DIMENSIONS}")
        return cls(tuple(texts), dimensions, str(body.get("model") or ""))


def features(text: str) -> Counter:
    tokens = words(text)
    counted = Counter(f"w:{token}" for token in tokens)
    counted.update(f"p:{first} {second}" for first, second in pairwise(tokens))
    return counted


def slot(feature: str, dimensions: int) -> tuple[int, float]:
    digest = hashlib.sha256(feature.encode("utf-8")).digest()
    position = int.from_bytes(digest[:8], "big") % dimensions
    return position, 1.0 if digest[8] & 1 else -1.0


def embed(text: str, dimensions: int) -> list[float]:
    vector = [0.0] * dimensions
    counted = features(text) or Counter({EMPTY_FEATURE: 1})
    for feature, count in sorted(counted.items()):
        position, sign = slot(feature, dimensions)
        vector[position] += sign * (1.0 + math.log(count))
    length = math.sqrt(sum(value * value for value in vector))
    if length == 0.0:
        position, sign = slot(EMPTY_FEATURE, dimensions)
        vector[position], length = sign, 1.0
    return [value / length for value in vector]


def response(request: EmbeddingRequest, model: str) -> dict:
    tokens = sum(tokens_in(len(text)) for text in request.texts)
    return {
        "object": "list",
        "data": [
            {"object": "embedding", "index": index, "embedding": embed(text, request.dimensions)}
            for index, text in enumerate(request.texts)
        ],
        "model": request.model or model,
        "usage": {"prompt_tokens": tokens, "total_tokens": tokens},
    }
