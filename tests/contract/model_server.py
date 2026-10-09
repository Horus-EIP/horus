import json
import threading
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from llm_mock.server import MockServer
from llm_mock.settings import Settings

REQUESTS = Path(__file__).resolve().parent / "requests"
MAS_PROMPTS = Path(__file__).resolve().parents[2] / "src" / "services" / "mas" / "tasks" / "prompts.py"
TIMEOUT_SECONDS = 900


def recorded(name: str) -> list[dict]:
    return json.loads((REQUESTS / name).read_text(encoding="utf-8"))


@dataclass
class ModelServer:
    url: str
    model: str | None = None

    def content(self, entry: dict) -> str:
        body = dict(entry["body"])
        if self.model:
            body["model"] = self.model
        request = urllib.request.Request(
            self.url.rstrip("/") + "/chat/completions",
            json.dumps(body).encode("utf-8"),
            {"Content-Type": "application/json", "X-Horus-Purpose": entry["purpose"]},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            raw = response.read().decode("utf-8")
        if not body.get("stream"):
            return json.loads(raw)["choices"][0]["message"].get("content") or ""
        return "".join(streamed_text(raw))


def streamed_text(raw: str):
    for line in raw.splitlines():
        if not line.startswith("data:"):
            continue
        data = line[len("data:"):].strip()
        if data == "[DONE]":
            return
        chunk = json.loads(data)
        if chunk.get("error"):
            raise RuntimeError(f"the server stopped the stream: {chunk['error']}")
        choices = chunk.get("choices") or []
        if choices:
            yield (choices[0].get("delta") or {}).get("content") or ""


class RunningMock:
    def __init__(self):
        self.server = MockServer(("127.0.0.1", 0), Settings(latency_ms=0), sleep=lambda _s: None)
        self.thread = threading.Thread(target=self.server.serve_forever, args=(0.05,), daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/v1"

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()
