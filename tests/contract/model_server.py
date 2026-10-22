import importlib.util
import json
import threading
import time
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from llm_mock.server import MockServer
from llm_mock.settings import Settings

REQUESTS = Path(__file__).resolve().parent / "requests"
SERVICES = Path(__file__).resolve().parents[2] / "src" / "services"
MAS_PROMPTS = SERVICES / "mas" / "tasks" / "prompts.py"
EMBEDDINGS_CLIENT = SERVICES / "mas" / "core" / "embeddings_client.py"
TIMEOUT_SECONDS = 900
START_WAIT_SECONDS = 60.0


def recorded(name: str) -> list[dict]:
    return json.loads((REQUESTS / name).read_text(encoding="utf-8"))


EMBEDDING_REQUESTS = {
    "mas": recorded("mas_embeddings.json"),
    "knowledge_store": recorded("knowledge_store.json"),
}


def embeddings_client_module():
    spec = importlib.util.spec_from_file_location("horus_embeddings_client", EMBEDDINGS_CLIENT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


EmbeddingsClient = embeddings_client_module().EmbeddingsClient


class Embeddings:
    def __init__(self, url: str, entries: list[dict], model: str | None = None):
        self.model = model
        self.client = EmbeddingsClient(
            url, model or entries[0]["body"]["model"], entries[0]["size"]
        )
        refused = self.client.wait_until_ready(time.monotonic() + START_WAIT_SECONDS)
        if refused:
            raise refused

    def vectors(self, entry: dict) -> list[list[float]]:
        body = dict(entry["body"])
        if self.model:
            body["model"] = self.model
        body.pop("dimensions", None)
        if self.client.send_dimensions:
            body["dimensions"] = entry["size"]
        answer = self.client.post(body, TIMEOUT_SECONDS)
        items = sorted(answer["data"], key=lambda item: item["index"])
        assert [item["index"] for item in items] == list(range(len(body["input"]))), answer
        return [item["embedding"] for item in items]


class EmbeddingsServers:
    def __init__(self, locate: Callable[[str], tuple[str, str | None]]):
        self.locate = locate
        self.connected: dict[str, Embeddings] = {}

    def __call__(self, service: str) -> Embeddings:
        if service not in self.connected:
            url, model = self.locate(service)
            self.connected[service] = Embeddings(url, EMBEDDING_REQUESTS[service], model)
        return self.connected[service]


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
        data = line[len("data:") :].strip()
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
