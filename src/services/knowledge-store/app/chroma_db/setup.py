import os

os.environ.setdefault("POSTHOG_DISABLED", "true")
os.environ.setdefault("CHROMA_TELEMETRY_ENABLED", "0")
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")

import time
from collections.abc import Iterable, Sequence
from importlib import metadata
from pathlib import Path

import chromadb
from chromadb.config import Settings

from app.chroma_db.embeddings_client import EmbeddingsClient
from app.core.logging import get_logger
from app.core.metrics import timed_embedding

try:
    import posthog  # type: ignore

    if hasattr(posthog, "capture"):
        _original_capture = posthog.capture

        def _safe_capture(*args, **kwargs):
            try:
                return _original_capture(*args, **kwargs)
            except TypeError:
                try:
                    return _original_capture(args[0]) if args else None
                except Exception:
                    return None

        posthog.capture = _safe_capture  # type: ignore[attr-defined]
except Exception:
    pass

logger = get_logger("Embedder")

CHROMA_DATA_DIR = Path(__file__).parent.parent.parent / "chroma_data"

chroma_client = chromadb.PersistentClient(
    path=str(CHROMA_DATA_DIR),
    settings=Settings(anonymized_telemetry=False)
)

FASTEMBED_MODEL = "BAAI/bge-base-en-v1.5"
FASTEMBED_RUNTIME = "fastembed"
HTTP_RUNTIME = "http"
EMBED_DIMENSIONS = 768
CUDA_PROVIDER = "CUDAExecutionProvider"
STARTUP_WAIT_SECONDS = 60.0
EMBED_URL = os.getenv("KNOWLEDGE_STORE_EMBED_URL", "").strip()


def installed_version(distribution: str) -> str:
    try:
        return metadata.version(distribution)
    except metadata.PackageNotFoundError:
        return "unknown"


if EMBED_URL:
    MODEL_NAME = os.getenv("KNOWLEDGE_STORE_EMBED_MODEL", "").strip() or FASTEMBED_MODEL
    EMBED_RUNTIME = HTTP_RUNTIME
    EMBED_RUNTIME_VERSION = ""
    EMBED_MODEL = f"{HTTP_RUNTIME}:{MODEL_NAME}:{EMBED_DIMENSIONS}"
else:
    MODEL_NAME = FASTEMBED_MODEL
    EMBED_RUNTIME = FASTEMBED_RUNTIME
    EMBED_RUNTIME_VERSION = installed_version(EMBED_RUNTIME)
    EMBED_MODEL = f"{EMBED_RUNTIME}-{EMBED_RUNTIME_VERSION}:{MODEL_NAME}"

COLLECTION_METADATA = {
    "embedding_model": MODEL_NAME,
    "embed_model": EMBED_MODEL,
    "embedding_runtime": EMBED_RUNTIME,
    "embedding_runtime_version": EMBED_RUNTIME_VERSION,
    "dimensions": EMBED_DIMENSIONS,
}

BGE_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "
QUERY_PREFIX = "" if EMBED_URL else BGE_QUERY_PREFIX


def wants_cuda(requested: str, available_providers: Sequence[str]) -> bool:
    device = (requested or "").strip().lower()
    cuda_available = CUDA_PROVIDER in available_providers
    if device in ("", "auto"):
        return cuda_available
    if not device.startswith("cuda"):
        return False
    if not cuda_available:
        logger.warning(
            "KNOWLEDGE_STORE_EMBED_DEVICE=%s, but this onnxruntime has no %s; embedding on CPU",
            requested, CUDA_PROVIDER,
        )
    return cuda_available


def embed_threads(raw: str | None) -> int | None:
    try:
        threads = int((raw or "").strip())
    except ValueError:
        return None
    return threads if threads > 0 else None


def load_fastembed():
    import onnxruntime
    from fastembed import TextEmbedding

    device = os.getenv("KNOWLEDGE_STORE_EMBED_DEVICE", "auto")
    use_cuda = wants_cuda(device, onnxruntime.get_available_providers())
    threads = embed_threads(os.getenv("KNOWLEDGE_STORE_EMBED_THREADS"))
    loaded = TextEmbedding(MODEL_NAME, threads=threads, cuda=use_cuda)
    logger.info(
        "BGE embedder %s loaded with %s %s on %s (KNOWLEDGE_STORE_EMBED_DEVICE=%s, threads=%s)",
        MODEL_NAME, EMBED_RUNTIME, EMBED_RUNTIME_VERSION, "cuda" if use_cuda else "cpu",
        device, threads or "onnxruntime default",
    )
    return loaded


def connect_to_embeddings_server() -> EmbeddingsClient:
    client = EmbeddingsClient(EMBED_URL, MODEL_NAME, EMBED_DIMENSIONS)
    logger.info(
        "Embeddings come from %s with the model %s, %d values per vector: "
        "no embedding model is loaded in this service",
        EMBED_URL, MODEL_NAME, EMBED_DIMENSIONS,
    )
    refused = client.wait_until_ready(time.monotonic() + STARTUP_WAIT_SECONDS)
    if refused:
        logger.warning(
            "The embeddings server is up but refused a test request, so search and "
            "uploads fail until it answers: %s", refused,
        )
    return client


model = connect_to_embeddings_server() if EMBED_URL else load_fastembed()


def _vectors(texts: Iterable[str]) -> list[list[float]]:
    return [
        vector if isinstance(vector, list) else vector.tolist()
        for vector in model.embed(list(texts))
    ]


@timed_embedding
def get_embedding(text: str, is_query: bool = False) -> list[float]:
    if is_query:
        text = QUERY_PREFIX + text
    return _vectors([text])[0]


@timed_embedding
def get_embeddings(texts: list[str]) -> list[list[float]]:
    return _vectors(texts)


COLLECTION_NAME = "knowledge_collection"

try:
    knowledge_collection = chroma_client.get_collection(name=COLLECTION_NAME)
except Exception:
    knowledge_collection = chroma_client.create_collection(
        name=COLLECTION_NAME,
        metadata=dict(COLLECTION_METADATA),
    )
