import os
os.environ.setdefault("POSTHOG_DISABLED", "true")
os.environ.setdefault("CHROMA_TELEMETRY_ENABLED", "0")
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")

from sentence_transformers import SentenceTransformer
from pathlib import Path
import chromadb
from chromadb.config import Settings

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

chroma_client = chromadb.PersistentClient(
    path=str(Path(__file__).parent.parent.parent / "chroma_data"),
    settings=Settings(anonymized_telemetry=False)
)

MODEL_NAME = "BAAI/bge-base-en-v1.5"

model = SentenceTransformer(MODEL_NAME)

BGE_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "

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