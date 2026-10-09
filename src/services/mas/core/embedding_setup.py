"""Sentence-embedding model (MiniLM) for similarity-based skill matching.

Mirrors the lazy-load + background-preload pattern used in ``llm_setup.py``
so HTTP can bind quickly while the model loads off the request path. The
embedder is far smaller than Qwen3-4B (~90 MB) and runs comfortably on CPU,
so we always pin it to CPU to keep GPU memory available for the generative
LLM that genuinely needs it.
"""

import os
import threading
import time

import numpy as np

from core.embeddings_client import EmbeddingsClient
from core.logger import get_logger

logger = get_logger("embedding_setup")

EMBED_MODEL_ID = "sentence-transformers/all-MiniLM-L6-v2"
EMBED_THREADS_ENV = "MAS_EMBED_THREADS"
SHARED_THREADS_ENV = "LLM_TORCH_INTRAOP_THREADS"
EMBED_URL_ENV = "MAS_EMBED_URL"
EMBED_MODEL_ENV = "MAS_EMBED_MODEL"
SERVER_DIMENSIONS = 384
STARTUP_WAIT_SECONDS = 60.0
_started_at = time.monotonic()

_embedder = None
_embedder_load_lock = threading.Lock()


def embed_threads() -> int | None:
    for name in (EMBED_THREADS_ENV, SHARED_THREADS_ENV):
        raw = os.environ.get(name, "").strip()
        if not raw:
            continue
        try:
            threads = int(raw)
        except ValueError:
            logger.warning("Ignoring %s=%r: not a whole number of threads", name, raw)
            continue
        if threads > 0:
            return threads
    return None


def _connect_to_embeddings_server(url: str) -> EmbeddingsClient:
    model = os.environ.get(EMBED_MODEL_ENV, "").strip() or EMBED_MODEL_ID
    client = EmbeddingsClient(url, model, SERVER_DIMENSIONS)
    logger.info(
        "Embeddings come from %s with the model %s, %d values per vector: "
        "no embedding model is loaded in MAS",
        url,
        model,
        SERVER_DIMENSIONS,
    )
    refused = client.wait_until_ready(_started_at + STARTUP_WAIT_SECONDS)
    if refused:
        logger.warning(
            "The embeddings server is up but refused a test request, so skill matching "
            "and the router's embedding stage fail until it answers: %s",
            refused,
        )
    return client


def _load_embedder():
    url = os.environ.get(EMBED_URL_ENV, "").strip()
    if url:
        return _connect_to_embeddings_server(url)
    from fastembed import TextEmbedding

    threads = embed_threads()
    logger.info(
        "Loading sentence-embedding model %s with FastEmbed on CPU (threads=%s)",
        EMBED_MODEL_ID,
        threads or "onnxruntime default",
    )
    model = TextEmbedding(EMBED_MODEL_ID, threads=threads, cuda=False)
    logger.info("Sentence-embedding model ready: dim=%d", model.embedding_size)
    return model


def _ensure_embedder_loaded() -> None:
    global _embedder
    if os.environ.get("TEST_MODE") == "1":
        return
    if _embedder is not None:
        return
    with _embedder_load_lock:
        if _embedder is not None:
            return
        _embedder = _load_embedder()


def start_embedding_preload_background_thread() -> None:
    """Preload the embedder off the main thread so HTTP binds quickly."""
    if os.environ.get("TEST_MODE") == "1":
        return

    def _worker() -> None:
        try:
            logger.info("Background thread: preloading sentence-embedding model...")
            _ensure_embedder_loaded()
            logger.info("Background thread: sentence-embedding preload finished.")
            # Best-effort cache warm: avoids a cold first /tasks/suggest-skills call.
            try:
                from core.skill_cache import warm_skill_cache

                warm_skill_cache()
            except Exception:
                logger.exception("Skill-cache warm failed during embedding preload.")
            try:
                from tasks.router import warm_router_examples

                warm_router_examples()
            except Exception:
                logger.exception("Router examples warm failed during embedding preload.")
        except Exception:
            logger.exception(
                "Background embedder preload failed; first suggest call will retry."
            )

    threading.Thread(
        target=_worker, name="mas-embedder-preload", daemon=True
    ).start()


def embed_texts(texts: list[str]) -> np.ndarray:
    """Return an ``(N, D)`` float32 matrix of L2-normalised embeddings."""
    _ensure_embedder_loaded()
    if _embedder is None:
        raise RuntimeError(
            "Embedding model is not loaded. Check container logs for load errors."
        )
    vectors = list(_embedder.embed(list(texts)))
    if not vectors:
        return np.empty((0, _embedder.embedding_size), dtype=np.float32)
    return np.stack(vectors).astype(np.float32, copy=False)


def embed_text(text: str) -> np.ndarray:
    """Return a single ``(D,)`` normalised embedding vector."""
    return embed_texts([text])[0]
