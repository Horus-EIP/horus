import importlib.util
import json
import threading
import urllib.error
import urllib.request
from pathlib import Path

from llm_mock.server import MockServer
from llm_mock.settings import Settings

REPO = Path(__file__).resolve().parents[2]
MAS_PROMPTS = REPO / "src" / "services" / "mas" / "tasks" / "prompts.py"

ROSTER = (
    (
        "id-general",
        "General-Assistant",
        "General-purpose RAG assistant. Default fallback when no specialised agent matches the demand.",
        "general",
    ),
    (
        "id-finance",
        "Finance-Analyst",
        "Financial analysis specialist. Grounded in the Q4 2025 Financial Report and the Expense Policy.",
        "analyst",
    ),
    (
        "id-compliance",
        "Compliance-Officer",
        "Policy and compliance reviewer. Grounded in the Compliance Guidelines and the IT Security Policy.",
        "analyst",
    ),
    (
        "id-hr",
        "HR-Assistant",
        "HR specialist. Grounded in the Employee Handbook and the Expense Policy.",
        "general",
    ),
    (
        "id-researcher",
        "Researcher",
        "Multi-source researcher. Pulls and synthesises information across the knowledge store.",
        "researcher",
    ),
)


def mas_prompts():
    spec = importlib.util.spec_from_file_location("mas_prompts", MAS_PROMPTS)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def route_schema(names) -> dict:
    return {
        "type": "object",
        "properties": {
            "route": {"type": "string", "enum": ["SINGLE_AGENT", "COMPLEX_TASK"]},
            "agent": {"type": "string", "enum": sorted(set(names))},
        },
        "required": ["route", "agent"],
        "additionalProperties": False,
    }


def route_body(question: str, roster=ROSTER) -> dict:
    lines = "\n".join(
        f"- {name}: {description}" if description else f"- {name}"
        for _, name, description, _ in sorted(roster, key=lambda agent: (agent[1], agent[2]))
    )
    messages = [
        {
            "role": "system",
            "content": (
                "You route requests inside a multi-agent assistant. Reply with JSON only.\n"
                "route: SINGLE_AGENT for almost every request, including any question "
                "about one topic, however it is phrased.\n"
                "route: COMPLEX_TASK only when the request asks two or more separate things "
                "that belong to different agents' domains.\n"
                "agent: the agent whose domain best fits the request, or its first part.\n"
                f"Agents:\n{lines}"
            ),
        },
        {"role": "user", "content": question[:2000]},
    ]
    return structured_body(messages, "task_route", route_schema(a[1] for a in roster), 32)


def answer_schema(labels) -> dict:
    properties = {
        "status": {"type": "string", "enum": ["ok", "not_found"]},
        "answer": {"type": "string"},
    }
    required = ["status", "answer"]
    if labels:
        properties["sources"] = {"type": "array", "items": {"type": "string", "enum": list(labels)}}
        required.append("sources")
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def answer_body(context: str, request: str, labels=("S1",), stream=True) -> dict:
    messages = [
        {
            "role": "system",
            "content": "You are FinCorp's Finance Analyst.\n\n---\n\nYou answer "
            "one request from the passages you are given.",
        },
        {
            "role": "user",
            "content": f"Passages:\n{context or '(no passages)'}\n\nRequest: {request}",
        },
    ]
    body = structured_body(messages, "agent_answer", answer_schema(labels), 1024)
    body["stream"] = stream
    if stream:
        body["stream_options"] = {"include_usage": True}
    return body


def structured_body(messages, name: str, schema: dict, max_tokens: int) -> dict:
    return {
        "model": "qwen3-4b",
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0.0,
        "stream": False,
        "response_format": {
            "type": "json_schema",
            "json_schema": {"name": name, "strict": True, "schema": schema},
        },
    }


def text_body(messages, max_tokens: int = 256) -> dict:
    return {
        "model": "qwen3-4b",
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0.0,
        "stream": False,
    }


class Running:
    def __init__(self, settings: Settings):
        self.slept: list[float] = []
        self.server = MockServer(("127.0.0.1", 0), settings, sleep=self.slept.append)
        self.thread = threading.Thread(target=self.server.serve_forever, args=(0.05,), daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def request(self, method: str, path: str, body=None, headers=None):
        data = body if body is None or isinstance(body, bytes) else json.dumps(body).encode()
        request = urllib.request.Request(
            self.url + path,
            data=data,
            method=method,
            headers={"Content-Type": "application/json", **(headers or {})},
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, response.headers, response.read()
        except urllib.error.HTTPError as error:
            return error.code, error.headers, error.read()

    def complete(self, body: dict, purpose: str | None = None) -> dict:
        headers = {"X-Horus-Purpose": purpose} if purpose else {}
        status, _, raw = self.request("POST", "/v1/chat/completions", body, headers)
        assert status == 200, raw
        return json.loads(raw)

    def content(self, body: dict, purpose: str | None = None) -> str:
        return self.complete(body, purpose)["choices"][0]["message"]["content"]

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()


def sse_events(raw: bytes) -> list[str]:
    text = raw.decode("utf-8")
    assert text.endswith("\n\n")
    events = text[:-2].split("\n\n")
    assert all(event.startswith("data: ") and "\n" not in event for event in events)
    return [event[len("data: ") :] for event in events]
