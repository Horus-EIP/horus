from __future__ import annotations

import http.client
import json
import logging
import math
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from core import embedding_setup, embeddings_client
from core.embeddings_client import (
    BATCH_SIZE,
    RETRY_SECONDS,
    SHORTEST_PROBE_SECONDS,
    TIMEOUT_SECONDS,
    EmbeddingsClient,
    EmbeddingsError,
    EmbeddingsRefused,
    EmbeddingsUnavailable,
    WrongSize,
)

MODEL_LOADERS = ("fastembed", "onnxruntime")
NATIVE = 768


def vector_for(text: str, dimensions: int) -> list[float]:
    return [float(len(text)), 1.0] + [0.0] * (dimensions - 2)


def unit_vector_for(text: str, dimensions: int) -> list[float]:
    vector = vector_for(text, dimensions)
    length = math.sqrt(sum(value * value for value in vector))
    return [value / length for value in vector]


def vectors(body: dict, native: int = NATIVE) -> tuple[int, dict]:
    dimensions = body.get("dimensions", native)
    return 200, {
        "data": [
            {"index": index, "embedding": vector_for(text, dimensions)}
            for index, text in enumerate(body["input"])
        ]
    }


class Handler(BaseHTTPRequestHandler):
    server: FakeServer

    def do_POST(self) -> None:
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.server.requests.append((self.path, body))
        status, payload = self.server.answer(body)
        raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *args) -> None:
        pass


class FakeServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self):
        super().__init__(("127.0.0.1", 0), Handler)
        self.requests: list[tuple[str, dict]] = []
        self.answer = vectors

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}/v1"

    @property
    def texts(self) -> list[list[str]]:
        return [body["input"] for _, body in self.requests]

    @property
    def sizes_asked(self) -> list[int | None]:
        return [body.get("dimensions") for _, body in self.requests]


@pytest.fixture
def server():
    running = FakeServer()
    thread = threading.Thread(target=running.serve_forever, kwargs={"poll_interval": 0.05})
    thread.daemon = True
    thread.start()
    yield running
    running.shutdown()
    running.server_close()


def closed_port_url() -> str:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    return f"http://127.0.0.1:{port}/v1"


def failing_with(error: Exception):
    def open_url(request, timeout):
        raise error

    return open_url


class TestClient:
    def test_the_request_names_the_model_the_size_and_the_texts(self, server):
        EmbeddingsClient(server.url + "/", "horus-mock", 4).embed(["a", "bb"])

        assert server.requests == [
            (
                "/v1/embeddings",
                {
                    "model": "horus-mock",
                    "input": ["a", "bb"],
                    "encoding_format": "float",
                    "dimensions": 4,
                },
            )
        ]

    def test_vectors_come_back_at_unit_length_in_the_order_of_the_texts(self, server):
        def reversed_vectors(body):
            status, answer = vectors(body)
            return status, {"data": answer["data"][::-1]}

        server.answer = reversed_vectors

        got = EmbeddingsClient(server.url, "m", 4).embed(["a", "bbb"])

        assert got == [unit_vector_for("a", 4), unit_vector_for("bbb", 4)]

    def test_texts_go_in_batches_small_enough_for_every_server(self, server):
        texts = [f"text {n}" for n in range(2 * BATCH_SIZE + 1)]

        got = EmbeddingsClient(server.url, "m", 4).embed(texts)

        assert BATCH_SIZE <= 32
        assert [len(batch) for batch in server.texts] == [BATCH_SIZE, BATCH_SIZE, 1]
        assert got == [unit_vector_for(text, 4) for text in texts]

    def test_no_text_sends_no_request(self, server):
        assert EmbeddingsClient(server.url, "m", 4).embed([]) == []
        assert server.requests == []

    def test_a_zero_vector_is_returned_as_it_is(self, server):
        server.answer = lambda body: (200, {"data": [{"index": 0, "embedding": [0, 0, 0]}]})

        assert EmbeddingsClient(server.url, "m", 3).embed(["x"]) == [[0.0, 0.0, 0.0]]

    def test_the_size_is_the_one_asked_for(self):
        assert EmbeddingsClient("http://embeddings/v1", "m", 768).embedding_size == 768

    @pytest.mark.parametrize(
        ("answer", "error", "message"),
        [
            (
                (500, {"error": {"message": "The mock model server failed."}}),
                EmbeddingsRefused,
                "answered HTTP 500: The mock model server failed.",
            ),
            ((400, b"not json"), EmbeddingsRefused, "answered HTTP 400: Bad Request"),
            ((200, b"not json"), EmbeddingsError, "did not answer JSON"),
            ((200, {"vectors": []}), EmbeddingsError, "without a list of indexed embeddings"),
            (
                (200, ["not", "an", "object"]),
                EmbeddingsError,
                "without a list of indexed embeddings",
            ),
            (
                (200, {"data": [{"embedding": [1.0, 0.0]}]}),
                EmbeddingsError,
                "without a list of indexed embeddings",
            ),
            (
                (200, {"data": [{"index": 0, "embedding": [1.0, 0.0]}]}),
                EmbeddingsError,
                "returned 1 embeddings for 2 texts",
            ),
            (
                (
                    200,
                    {
                        "data": [
                            {"index": 0, "embedding": [1.0, 0.0]},
                            {"index": 0, "embedding": [1.0, 0.0]},
                        ]
                    },
                ),
                EmbeddingsError,
                "returned 2 embeddings for 2 texts",
            ),
            (
                (
                    200,
                    {
                        "data": [
                            {"index": 0, "embedding": [1.0]},
                            {"index": 1, "embedding": [1.0, 0.0]},
                        ]
                    },
                ),
                WrongSize,
                "returned a vector of 1 values for the model m, but this service needs 2",
            ),
            (
                (
                    200,
                    {
                        "data": [
                            {"index": 0, "embedding": "1,0"},
                            {"index": 1, "embedding": [1.0, 0.0]},
                        ]
                    },
                ),
                WrongSize,
                "returned a vector of None values",
            ),
            (
                (
                    200,
                    {
                        "data": [
                            {"index": 0, "embedding": [1.0, "x"]},
                            {"index": 1, "embedding": [1.0, 0.0]},
                        ]
                    },
                ),
                EmbeddingsError,
                "not all numbers",
            ),
        ],
    )
    def test_a_bad_answer_is_a_clear_error(self, server, answer, error, message):
        server.answer = lambda body: answer

        with pytest.raises(error, match=message) as raised:
            EmbeddingsClient(server.url, "m", 2).embed(["a", "b"])

        assert not isinstance(raised.value, EmbeddingsUnavailable)

    @pytest.mark.parametrize("status", [502, 503, 504])
    def test_a_server_that_is_not_ready_is_unavailable(self, server, status):
        server.answer = lambda body: (status, {"error": {"message": "loading"}})

        with pytest.raises(EmbeddingsUnavailable, match=f"HTTP {status}: loading"):
            EmbeddingsClient(server.url, "m", 2).embed(["a"])

    def test_a_server_that_is_not_there_is_unavailable(self):
        with pytest.raises(EmbeddingsUnavailable, match="Could not reach"):
            EmbeddingsClient(closed_port_url(), "m", 2).embed(["a"])

    @pytest.mark.parametrize(
        "broken",
        [
            http.client.IncompleteRead(b'{"data"'),
            http.client.BadStatusLine("garbage"),
            http.client.RemoteDisconnected("closed"),
        ],
    )
    def test_an_answer_broken_off_is_unavailable(self, broken):
        client = EmbeddingsClient("http://embeddings/v1", "m", 2, open_url=failing_with(broken))

        with pytest.raises(EmbeddingsUnavailable, match="Could not reach"):
            client.embed(["a"])

    def test_an_address_with_a_bad_port_is_a_clear_error(self):
        client = EmbeddingsClient(
            "http://embeddings:port/v1",
            "m",
            2,
            open_url=failing_with(http.client.InvalidURL("nonnumeric port")),
        )

        with pytest.raises(EmbeddingsError, match="is not a valid address") as raised:
            client.embed(["a"])

        assert not isinstance(raised.value, EmbeddingsUnavailable)


class TestWaitingAtStart:
    def test_the_client_waits_while_the_server_is_not_up(self, server):
        answers = [(503, {}), (503, {})]
        server.answer = lambda body: answers.pop(0) if answers else vectors(body, native=2)
        slept: list[float] = []

        refused = EmbeddingsClient(
            server.url, "m", 2, clock=lambda: 0.0, sleep=slept.append
        ).wait_until_ready(10.0)

        assert refused is None
        assert slept == [RETRY_SECONDS, RETRY_SECONDS]
        assert server.texts == [["ready"]] * 3

    def test_the_client_gives_up_at_the_deadline(self, server):
        server.answer = lambda body: (503, {})
        ticks = iter(range(0, 100, 2))
        slept: list[float] = []
        client = EmbeddingsClient(
            server.url, "m", 2, clock=lambda: float(next(ticks)), sleep=slept.append
        )

        with pytest.raises(EmbeddingsUnavailable):
            client.wait_until_ready(10.0)

        assert slept == [RETRY_SECONDS] * 2

    def test_a_server_that_serves_the_size_unasked_is_never_sent_one(self, server):
        server.answer = lambda body: vectors(body, native=4)
        client = EmbeddingsClient(server.url, "m", 4)

        client.wait_until_ready(10.0)
        client.embed(["a"])

        assert server.sizes_asked == [None, None]

    def test_a_server_of_another_size_is_asked_for_the_size_from_then_on(self, server):
        client = EmbeddingsClient(server.url, "m", 384)

        client.wait_until_ready(10.0)
        got = client.embed(["a"])

        assert server.sizes_asked == [None, 384, 384]
        assert len(got[0]) == 384

    def test_a_server_that_ignores_the_size_stops_the_start_with_a_clear_error(self, server):
        server.answer = lambda body: vectors({**body, "dimensions": NATIVE})
        slept: list[float] = []

        with pytest.raises(WrongSize, match="768 values .* needs 384"):
            EmbeddingsClient(server.url, "m", 384, sleep=slept.append).wait_until_ready(10.0)

        assert slept == []

    def test_a_server_that_is_up_but_refuses_does_not_stop_the_start(self, server):
        server.answer = lambda body: (500, {"error": {"message": "Simulated model server failure"}})
        slept: list[float] = []
        client = EmbeddingsClient(server.url, "m", 2, sleep=slept.append)

        refused = client.wait_until_ready(10.0)

        assert isinstance(refused, EmbeddingsRefused)
        assert "Simulated model server failure" in str(refused)
        assert slept == []
        assert client.send_dimensions is True

    @pytest.mark.parametrize(
        ("left", "timeout"),
        [
            (0.3, SHORTEST_PROBE_SECONDS),
            (5.0, 5.0),
            (600.0, TIMEOUT_SECONDS),
        ],
    )
    def test_a_probe_never_waits_much_past_the_deadline(self, left, timeout):
        seen: list[float] = []

        def open_url(request, timeout):
            seen.append(timeout)
            raise ConnectionRefusedError("refused")

        ticks = iter([100.0, 100.0 + left + 1])
        client = EmbeddingsClient(
            "http://embeddings/v1",
            "m",
            2,
            open_url=open_url,
            clock=lambda: next(ticks),
            sleep=lambda seconds: None,
        )

        with pytest.raises(EmbeddingsUnavailable):
            client.wait_until_ready(100.0 + left)

        assert seen == [timeout]


class FastEmbedBlocker:
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] in MODEL_LOADERS:
            raise ImportError(f"{name} must not be imported when an embeddings URL is set")
        return None


@pytest.fixture
def without_fastembed(monkeypatch):
    for name in MODEL_LOADERS:
        monkeypatch.delitem(sys.modules, name, raising=False)
    monkeypatch.setattr(sys, "meta_path", [FastEmbedBlocker(), *sys.meta_path])


@pytest.fixture
def embeddings_url(monkeypatch, server):
    monkeypatch.setenv(embedding_setup.EMBED_URL_ENV, server.url)
    monkeypatch.setenv(embedding_setup.EMBED_MODEL_ENV, "horus-mock")
    monkeypatch.setattr(embedding_setup, "_started_at", time.monotonic())
    return server.url


class TestTheSetting:
    def test_with_a_url_mas_loads_no_model_and_asks_the_server_for_384_values(
        self, server, embeddings_url, without_fastembed
    ):
        embedder = embedding_setup._load_embedder()

        assert isinstance(embedder, EmbeddingsClient)
        assert embedder.embedding_size == 384
        assert not any(name in sys.modules for name in MODEL_LOADERS)
        assert [body for _, body in server.requests] == [
            {"model": "horus-mock", "input": ["ready"], "encoding_format": "float"},
            {
                "model": "horus-mock",
                "input": ["ready"],
                "encoding_format": "float",
                "dimensions": 384,
            },
        ]

    def test_without_a_model_name_the_server_is_asked_for_minilm(
        self, monkeypatch, server, embeddings_url, without_fastembed
    ):
        monkeypatch.delenv(embedding_setup.EMBED_MODEL_ENV)

        embedding_setup._load_embedder()

        assert server.requests[0][1]["model"] == embedding_setup.EMBED_MODEL_ID

    def test_the_skill_matcher_and_the_router_get_unit_rows_from_the_server(
        self, monkeypatch, server, embeddings_url, without_fastembed
    ):
        monkeypatch.setattr(embedding_setup, "_embedder", embedding_setup._load_embedder())

        rows = embedding_setup.embed_texts(["finance", "leave policy"])

        assert rows.dtype == np.float32
        assert rows.shape == (2, 384)
        np.testing.assert_allclose(np.linalg.norm(rows, axis=1), [1.0, 1.0], rtol=1e-6)
        assert server.texts[2:] == [["finance", "leave policy"]]
        assert server.sizes_asked[2:] == [384]
        assert embedding_setup.embed_texts([]).shape == (0, 384)

    def test_the_start_waits_for_the_server(
        self, monkeypatch, server, embeddings_url, without_fastembed
    ):
        answers = [(503, {})]
        server.answer = lambda body: answers.pop(0) if answers else vectors(body)
        monkeypatch.setattr(embeddings_client, "RETRY_SECONDS", 0.0)

        embedding_setup._load_embedder()

        assert server.texts == [["ready"]] * 3

    def test_after_the_start_an_absent_server_fails_at_once(
        self, monkeypatch, server, embeddings_url, without_fastembed
    ):
        server.answer = lambda body: (503, {})
        monkeypatch.setattr(
            embedding_setup,
            "_started_at",
            time.monotonic() - embedding_setup.STARTUP_WAIT_SECONDS - 1,
        )

        with pytest.raises(EmbeddingsUnavailable):
            embedding_setup._load_embedder()

        assert server.texts == [["ready"]]

    def test_a_server_that_refuses_lets_mas_start_and_says_so(
        self, server, embeddings_url, without_fastembed, caplog
    ):
        server.answer = lambda body: (500, {"error": {"message": "Simulated model server failure"}})

        with caplog.at_level(logging.WARNING):
            embedder = embedding_setup._load_embedder()

        warnings = [
            r.getMessage() for r in caplog.records if "refused a test request" in r.getMessage()
        ]
        assert warnings and "Simulated model server failure" in warnings[0]
        with pytest.raises(EmbeddingsRefused):
            embedder.embed(["finance"])

    def test_without_a_url_fastembed_loads_as_before(self, monkeypatch):
        monkeypatch.delenv(embedding_setup.EMBED_URL_ENV, raising=False)
        fake_fastembed = MagicMock()

        with patch.dict("sys.modules", {"fastembed": fake_fastembed}):
            model = embedding_setup._load_embedder()

        assert model is fake_fastembed.TextEmbedding.return_value
        fake_fastembed.TextEmbedding.assert_called_once()
