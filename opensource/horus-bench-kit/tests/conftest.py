# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

import horus_bench_kit
from horus_bench_kit.shell import Shell
from horus_bench_kit.testset import file_sha256

KIT_ROOT = Path(__file__).resolve().parents[1]
GIB = 2**30
HOST_FACTS = {
    "cpu_model": ("Example CPU 8C", "/proc/cpuinfo"),
    "physical_cores": (8, "/proc/cpuinfo"),
    "avx2": (True, "/proc/cpuinfo"),
    "ram_total_bytes": (16 * GIB, "/proc/meminfo"),
    "disk_type": ("NVMe SSD", "lsblk"),
}
EXAMPLES = KIT_ROOT / "examples"
HARBOUR_DOCUMENTS = {
    "north-pier.md": (
        "# North pier\n\n"
        "Fourteen lanterns hang on the north pier and are lit at dusk.\n"
        "Mooring costs $12 per night for boats under 8 m.\n"
    ),
    "ferry-timetable.md": (
        "# Ferry timetable\n\n"
        "| Crossing | Fare |\n"
        "|---|---|\n"
        "| Island run | $6/adult |\n"
        "| Lighthouse run | $9/adult |\n\n"
        "The first ferry leaves at 06:40.\n"
    ),
    "harbour-rules.md": (
        "# Harbour rules\n\n"
        "The harbour master is Odile Brandt. Swimming inside the harbour wall is not allowed.\n"
        "Inside the wall, boats keep below 4 knots.\n"
    ),
}


@pytest.fixture
def examples() -> Path:
    return EXAMPLES


@pytest.fixture
def make_item():
    def factory(**overrides: Any) -> dict[str, Any]:
        item = {
            "id": "t-01",
            "category": "lookup",
            "difficulty": "easy",
            "question": "How many lanterns hang on the north pier?",
            "expected_answer": "Fourteen (14) lanterns.",
            "expected_source": "north-pier.md",
            "answer_patterns": [r"\b(?:14|fourteen)\b"],
        }
        item.update(overrides)
        return item

    return factory


@pytest.fixture
def corpus(tmp_path) -> Path:
    root = tmp_path / "corpus"
    root.mkdir()
    for name, text in HARBOUR_DOCUMENTS.items():
        (root / name).write_text(text, encoding="utf-8", newline="\n")
    return root


@pytest.fixture
def documents() -> dict[str, str]:
    return dict(HARBOUR_DOCUMENTS)


@pytest.fixture
def make_testset(corpus):
    def factory(items: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
        return {
            "version": "1.0.0",
            "corpus_dir": "corpus",
            "corpus": {name: file_sha256(corpus / name) for name in HARBOUR_DOCUMENTS},
            "items": items,
            **extra,
        }

    return factory


@pytest.fixture
def write_testset(tmp_path, make_testset):
    def factory(items: list[dict[str, Any]], name: str = "harbour.json", **extra: Any) -> Path:
        path = tmp_path / name
        path.write_text(json.dumps(make_testset(items, **extra)), encoding="utf-8")
        return path

    return factory


@pytest.fixture(params=["D:\\Projects\\someone\\x", "/srv/someone/x"])
def host_folder(request) -> str:
    return request.param


@pytest.fixture
def host_folder_leaks(host_folder) -> Callable[[str], list[str]]:
    parts = [part for part in re.split(r"[\\/:]+", host_folder) if len(part) > 1]

    def leaks(text: str) -> list[str]:
        return [part for part in parts if part in text]

    return leaks


def question_of(body: dict[str, Any]) -> str:
    return body["messages"][-1]["content"].rsplit("Question: ", 1)[-1]


class FakeOpenAI:
    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []
        self.answer: Callable[[dict[str, Any]], str] = lambda _body: "The documents do not say."
        self.status = 200
        self.delay = 0.0
        self.stream_error: dict[str, Any] | None = None
        self.model = "fake-model-1"
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler_for(self))
        self.server.daemon_threads = True

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}/v1"

    def completion(self, text: str) -> dict[str, Any]:
        return {
            "model": self.model,
            "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 40, "completion_tokens": len(text.split())},
        }

    def chunks(self, text: str, include_usage: bool) -> list[dict[str, Any]]:
        chunks: list[dict[str, Any]] = [
            {"model": self.model, "choices": [{"index": 0, "delta": {"role": "assistant"}}]},
            {"model": self.model, "choices": [{"index": 0, "delta": {"reasoning_content": "Reading."}}]},
        ]
        if self.stream_error:
            return [*chunks, {"error": self.stream_error}]
        middle = len(text) // 2
        chunks += [
            {"model": self.model, "choices": [{"index": 0, "delta": {"content": piece}}]}
            for piece in (text[:middle], text[middle:])
            if piece
        ]
        chunks.append({"model": self.model, "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]})
        if include_usage:
            usage = {"prompt_tokens": 40, "completion_tokens": len(text.split())}
            chunks.append({"model": self.model, "choices": [], "usage": usage})
        return chunks


def handler_for(fake: FakeOpenAI) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args: Any) -> None:
            return None

        def send(self, status: int, content_type: str, data: bytes) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self) -> None:
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            fake.requests.append({"path": self.path, "headers": dict(self.headers), "body": body})
            time.sleep(fake.delay)
            try:
                if fake.status != 200:
                    error = {"error": {"message": "the model is not loaded", "code": fake.status}}
                    self.send(fake.status, "application/json", json.dumps(error).encode("utf-8"))
                elif body.get("stream"):
                    include_usage = bool((body.get("stream_options") or {}).get("include_usage"))
                    chunks = fake.chunks(fake.answer(body), include_usage)
                    lines = [f"data: {json.dumps(chunk)}\n\n" for chunk in chunks]
                    data = "".join([": keep-alive\n\n", *lines, "data: [DONE]\n\n"]).encode("utf-8")
                    self.send(200, "text/event-stream", data)
                else:
                    reply = fake.completion(fake.answer(body))
                    self.send(200, "application/json", json.dumps(reply).encode("utf-8"))
            except OSError:
                pass

    return Handler


@pytest.fixture
def fake_openai():
    fake = FakeOpenAI()
    thread = threading.Thread(target=fake.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    yield fake
    fake.server.shutdown()
    fake.server.server_close()


@pytest.fixture
def example_answers() -> Callable[..., Callable[[dict[str, Any]], str]]:
    testset = json.loads((EXAMPLES / "testset.json").read_text(encoding="utf-8"))
    expected = {item["question"]: item["expected_answer"] for item in testset["items"]}

    def factory(**wrong: str) -> Callable[[dict[str, Any]], str]:
        by_id = {item["question"]: wrong.get(item["id"].replace("-", "_")) for item in testset["items"]}

        def answer(body: dict[str, Any]) -> str:
            question = question_of(body)
            return by_id.get(question) or expected.get(question, "I don't know.")

        return answer

    return factory


class RecordingShell(Shell):
    def __init__(self, temp: Path | None = None) -> None:
        self.calls: list[list[str]] = []
        self.inputs: list[str | None] = []
        self.host_paths: list[Path | None] = []
        self.temp = temp

    def text(self, argv: list[str]) -> str | None:
        if argv[:1] == ["git"]:
            return "abc1234\n"
        return None

    def run_text(self, argv, timeout=60.0):
        self.calls.append(list(argv))
        return self.text(list(argv))

    def run(self, argv):
        self.calls.append(list(argv))
        return 0

    def run_captured(self, argv):
        self.calls.append(list(argv))
        return 0, ""

    def run_and_echo(self, argv, stdin_text=None):
        self.calls.append(list(argv))
        self.inputs.append(stdin_text)
        return 0, []

    def docker_output(self, argv, timeout=60.0):
        self.calls.append(["docker", *argv])
        return ""

    def sleep(self, seconds):
        return None

    def temp_dir(self):
        return self.temp or Path(".")

    def collect_host(self, disk_path=None):
        self.host_paths.append(disk_path)
        return dict(HOST_FACTS)

    def docker_facts(self):
        return {"mem_total_bytes": 16 * GIB, "root_dir": "/var/lib/docker"}


def run_module(module: str, *args: str, stdin: str | None = None) -> subprocess.CompletedProcess:
    source = Path(horus_bench_kit.__file__).resolve().parents[1]
    environment = {**os.environ, "PYTHONPATH": str(source), "PYTHONDONTWRITEBYTECODE": "1"}
    return subprocess.run(
        [sys.executable, "-m", module, *args],
        input=stdin,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=environment,
    )


def gguf(gguf_id, file, quant, *, default=True, publisher="model author", size=900_000_000, sha="c3"):
    return {
        "id": gguf_id,
        "file": file,
        "quant": quant,
        "repo": "example/models-GGUF",
        "revision": "1" * 40,
        "upstream_file": file.replace("-", "_"),
        "publisher": publisher,
        "size_bytes": size,
        "sha256": sha * 32,
        "default": default,
    }


def candidate(candidate_id, name, role, ggufs, *, licence="Apache-2.0", since=None, flags=()):
    return {
        "id": candidate_id,
        "role": role,
        "name": name,
        "model_repo": f"example/{name}",
        "model_revision": "2" * 40,
        "licence": licence,
        "licence_statement": "Model card metadata: license apache-2.0.",
        "licence_flags": list(flags),
        "architecture": "ExampleForCausalLM",
        "gguf_architecture": "example",
        "llama_cpp": {"since_build": since, "since_pr": None, "evidence": "Supported since long ago."},
        "parameters": 1_000_000_000,
        "active_parameters": None,
        "size_note": "Small dense model.",
        "context_length": 32768,
        "thinking_default": "none",
        "thinking_evidence": "No thinking mode.",
        "notes": [],
        "ggufs": ggufs,
    }


def make_catalog():
    return {
        "version": "1.0.0",
        "looked_up": "2026-10-08",
        "llama_cpp": {
            "pinned_build": "b11382",
            "server_image": "ghcr.io/ggml-org/llama.cpp:server-b11382",
            "bench_image": "ghcr.io/ggml-org/llama.cpp:full-b11382",
        },
        "licences_allowed": ["Apache-2.0", "MIT"],
        "llama_bench": {
            "prompts": "512",
            "generations": "128",
            "depths": "0",
            "cache_types_k": "f16",
            "cache_types_v": "f16",
            "threads": "4",
            "repetitions": 3,
        },
        "candidates": [
            candidate(
                "alpha-1b",
                "Alpha-1B",
                "baseline",
                [
                    gguf("alpha-1b-q4km", "alpha-1b-Q4_K_M.gguf", "Q4_K_M", publisher="community", sha="a1"),
                    gguf("alpha-1b-q5km", "alpha-1b-Q5_K_M.gguf", "Q5_K_M", default=False, publisher="community", sha="a2"),
                ],
            ),
            candidate(
                "beta-2b",
                "Beta-2B",
                "candidate",
                [gguf("beta-2b-q4km", "beta-2b-Q4_K_M.gguf", "Q4_K_M", sha="b1")],
                licence="MIT",
                since=9000,
                flags=["The licence is only in the card metadata."],
            ),
            candidate(
                "gamma-3b",
                "Gamma-3B",
                "candidate",
                [
                    gguf("gamma-3b-q4km", "gamma-3b-Q4_K_M.gguf", "Q4_K_M", sha="c1"),
                    gguf("gamma-3b-q8", "gamma-3b-Q8_0.gguf", "Q8_0", default=False, sha="c2"),
                ],
            ),
        ],
    }


@pytest.fixture
def catalog():
    return make_catalog()
