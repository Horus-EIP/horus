"""Sentence-embedding model (MiniLM) for similarity-based skill matching.

Mirrors the lazy-load + background-preload pattern used in ``llm_setup.py``
so HTTP can bind quickly while the model loads off the request path. The
embedder is far smaller than Qwen3-4B (~90 MB) and runs comfortably on CPU,
so we always pin it to CPU to keep GPU memory available for the generative
LLM that genuinely needs it.
"""

import os
import threading
from pathlib import Path

import numpy as np

from core.logger import get_logger

logger = get_logger("embedding_setup")

BASE_DIR = Path(__file__).resolve().parent.parent
EMBED_MODEL_ID = "sentence-transformers/all-MiniLM-L6-v2"
EMBED_MODEL_DIR = BASE_DIR / "models/all-MiniLM-L6-v2"

_embedder = None
_embedder_load_lock = threading.Lock()


def _resolve_model_path() -> str:
    """Prefer the baked-in local copy; fall back to the HF id (network at runtime)."""
    if EMBED_MODEL_DIR.exists() and any(EMBED_MODEL_DIR.iterdir()):
        return str(EMBED_MODEL_DIR)
    return EMBED_MODEL_ID


def _load_embedder():
    from sentence_transformers import SentenceTransformer

    path = _resolve_model_path()
    logger.info("Loading sentence-embedding model from %s on CPU", path)
    model = SentenceTransformer(path, device="cpu")
    logger.info(
        "Sentence-embedding model ready: dim=%d, max_seq_len=%s",
        model.get_sentence_embedding_dimension(),
        getattr(model, "max_seq_length", "?"),
    )
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
    vecs = _embedder.encode(
        texts,
        convert_to_numpy=True,
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    return vecs.astype(np.float32, copy=False)


def embed_text(text: str) -> np.ndarray:
    """Return a single ``(D,)`` normalised embedding vector."""
    return embed_texts([text])[0]
