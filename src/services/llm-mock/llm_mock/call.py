import hashlib
import json
from dataclasses import dataclass, field


class BadRequest(ValueError):
    pass


@dataclass(frozen=True)
class Call:
    messages: tuple[dict, ...]
    purpose: str = ""
    schema_name: str = ""
    schema: dict = field(default_factory=dict)
    model: str = ""
    stream: bool = False
    include_usage: bool = False
    digest: str = ""

    @classmethod
    def from_request(cls, body: object, purpose: str = "") -> "Call":
        if not isinstance(body, dict):
            raise BadRequest("the request body must be a JSON object")
        messages = body.get("messages")
        if not isinstance(messages, list) or not messages:
            raise BadRequest("messages must be a non-empty list")
        if not all(isinstance(message, dict) for message in messages):
            raise BadRequest("each message must be an object")
        schema_name, schema = _json_schema(body.get("response_format"))
        options = body.get("stream_options")
        canonical = json.dumps([purpose.strip(), body], sort_keys=True, ensure_ascii=False)
        return cls(
            messages=tuple(messages),
            purpose=purpose.strip(),
            schema_name=schema_name,
            schema=schema,
            model=str(body.get("model") or ""),
            stream=bool(body.get("stream")),
            include_usage=isinstance(options, dict) and bool(options.get("include_usage")),
            digest=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        )

    @property
    def structured(self) -> bool:
        return bool(self.schema_name)

    def text_of(self, role: str) -> str:
        texts = [content_text(m.get("content")) for m in self.messages if m.get("role") == role]
        return texts[-1] if texts else ""

    @property
    def system(self) -> str:
        return self.text_of("system")

    @property
    def user(self) -> str:
        return self.text_of("user")

    @property
    def prompt_chars(self) -> int:
        return sum(len(content_text(message.get("content"))) for message in self.messages)


def content_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            str(part.get("text", "")) for part in content
            if isinstance(part, dict) and part.get("type") == "text"
        )
    return ""


def _json_schema(response_format: object) -> tuple[str, dict]:
    if not isinstance(response_format, dict) or response_format.get("type") != "json_schema":
        return "", {}
    spec = response_format.get("json_schema")
    if not isinstance(spec, dict):
        raise BadRequest("response_format.json_schema must be an object")
    schema = spec.get("schema")
    return str(spec.get("name") or "unnamed"), schema if isinstance(schema, dict) else {}
