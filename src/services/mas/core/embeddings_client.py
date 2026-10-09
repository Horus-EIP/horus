import http.client
import json
import math
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Sequence

BATCH_SIZE = 32
TIMEOUT_SECONDS = 60.0
RETRY_SECONDS = 2.0
SHORTEST_PROBE_SECONDS = 1.0
UNAVAILABLE_STATUSES = frozenset({502, 503, 504})


class EmbeddingsError(RuntimeError):
    pass


class EmbeddingsUnavailable(EmbeddingsError):
    pass


class EmbeddingsRefused(EmbeddingsError):
    pass


class WrongSize(EmbeddingsError):
    pass


def unit(vector: Sequence[float]) -> list[float]:
    values = [float(value) for value in vector]
    length = math.sqrt(sum(value * value for value in values))
    return [value / length for value in values] if length else values


def server_message(error: urllib.error.HTTPError) -> str:
    try:
        return str(json.loads(error.read().decode("utf-8"))["error"]["message"])
    except (OSError, http.client.HTTPException, ValueError, KeyError, TypeError):
        return str(error.reason)


class EmbeddingsClient:
    def __init__(
        self,
        base_url: str,
        model: str,
        dimensions: int,
        open_url: Callable = urllib.request.urlopen,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.url = base_url.rstrip("/") + "/embeddings"
        self.model = model
        self.dimensions = dimensions
        self.open_url = open_url
        self.clock = clock
        self.sleep = sleep
        self.send_dimensions = True

    @property
    def embedding_size(self) -> int:
        return self.dimensions

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        texts = list(texts)
        vectors: list[list[float]] = []
        for start in range(0, len(texts), BATCH_SIZE):
            vectors.extend(self.embed_batch(texts[start:start + BATCH_SIZE]))
        return vectors

    def wait_until_ready(self, deadline: float) -> EmbeddingsRefused | None:
        while True:
            timeout = min(TIMEOUT_SECONDS, max(deadline - self.clock(), SHORTEST_PROBE_SECONDS))
            try:
                self.agree_on_the_size(timeout)
                return None
            except EmbeddingsUnavailable:
                if self.clock() >= deadline:
                    raise
            except EmbeddingsRefused as refused:
                self.send_dimensions = True
                return refused
            self.sleep(RETRY_SECONDS)

    def agree_on_the_size(self, timeout: float) -> None:
        try:
            self.embed_batch(["ready"], send_dimensions=False, timeout=timeout)
            self.send_dimensions = False
        except WrongSize:
            self.embed_batch(["ready"], send_dimensions=True, timeout=timeout)
            self.send_dimensions = True

    def embed_batch(
        self,
        texts: list[str],
        send_dimensions: bool | None = None,
        timeout: float = TIMEOUT_SECONDS,
    ) -> list[list[float]]:
        body: dict = {"model": self.model, "input": texts, "encoding_format": "float"}
        if self.send_dimensions if send_dimensions is None else send_dimensions:
            body["dimensions"] = self.dimensions
        answer = self.post(body, timeout)
        try:
            items = sorted(answer["data"], key=lambda item: item["index"])
            indexes = [item["index"] for item in items]
            vectors = [item["embedding"] for item in items]
        except (KeyError, TypeError) as error:
            raise EmbeddingsError(f"{self.url} answered without a list of indexed embeddings") from error
        if indexes != list(range(len(texts))):
            raise EmbeddingsError(f"{self.url} returned {len(items)} embeddings for {len(texts)} texts")
        for vector in vectors:
            size = len(vector) if isinstance(vector, list) else None
            if size != self.dimensions:
                raise WrongSize(
                    f"{self.url} returned a vector of {size} values for the model {self.model}, "
                    f"but this service needs {self.dimensions}"
                )
        try:
            return [unit(vector) for vector in vectors]
        except (TypeError, ValueError) as error:
            raise EmbeddingsError(f"{self.url} returned a vector that is not all numbers") from error

    def post(self, body: dict, timeout: float = TIMEOUT_SECONDS) -> dict:
        request = urllib.request.Request(
            self.url,
            json.dumps(body).encode("utf-8"),
            {"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with self.open_url(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            problem = EmbeddingsUnavailable if error.code in UNAVAILABLE_STATUSES else EmbeddingsRefused
            raise problem(f"{self.url} answered HTTP {error.code}: {server_message(error)}") from error
        except http.client.InvalidURL as error:
            raise EmbeddingsError(f"{self.url} is not a valid address: {error}") from error
        except (OSError, http.client.HTTPException) as error:
            reason = getattr(error, "reason", None) or error
            raise EmbeddingsUnavailable(f"Could not reach {self.url}: {reason}") from error
        except ValueError as error:
            raise EmbeddingsError(f"{self.url} did not answer JSON") from error
