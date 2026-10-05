import os

os.environ.setdefault("POSTHOG_DISABLED", "true")
os.environ.setdefault("CHROMA_TELEMETRY_ENABLED", "0")
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")

from pathlib import Path

import chromadb
from chromadb.config import Settings
from sentence_transformers import SentenceTransformer

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

CHROMA_DATA_DIR = Path(__file__).parent.parent.parent / "chroma_data"

chroma_client = chromadb.PersistentClient(
    path=str(CHROMA_DATA_DIR),
    settings=Settings(anonymized_telemetry=False)
)

MODEL_NAME = "BAAI/bge-base-en-v1.5"

# Device selection for the BGE embedder. Default "auto" keeps the historical
# behaviour (SentenceTransformer picks CUDA when available). Set
# KNOWLEDGE_STORE_EMBED_DEVICE=cpu to keep the embedder OFF the shared 8 GB GPU
# so it stops competing with the agent's 4B model and paging it out under load
# (see scripts/perf/benchmark-pipeline.py contention scenario).
_EMBED_DEVICE = os.getenv("KNOWLEDGE_STORE_EMBED_DEVICE", "auto").strip().lower()
if _EMBED_DEVICE in ("", "auto"):
    model = SentenceTransformer(MODEL_NAME)
else:
    model = SentenceTransformer(MODEL_NAME, device=_EMBED_DEVICE)

# Log the resolved device so a silent CPU/GPU fallback is visible at startup.
try:
    _resolved_device = str(next(model.parameters()).device)
except Exception:
    _resolved_device = "unknown"
print(
    f"[knowledge-store] BGE embedder '{MODEL_NAME}' loaded on device="
    f"{_resolved_device} (KNOWLEDGE_STORE_EMBED_DEVICE={_EMBED_DEVICE})",
    flush=True,
)

BGE_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "

@timed_embedding
def get_embedding(text: str, is_query: bool = False) -> list[float]:
    if is_query:
        text = BGE_QUERY_PREFIX + text
    return model.encode(text, normalize_embeddings=True).tolist()

COLLECTION_NAME = "knowledge_collection"

try:
    knowledge_collection = chroma_client.get_collection(name=COLLECTION_NAME)
except Exception:
    knowledge_collection = chroma_client.create_collection(
        name=COLLECTION_NAME,
        metadata={"embedding_model": MODEL_NAME, "dimensions": 768}
    )
