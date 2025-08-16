import os
os.environ.setdefault("POSTHOG_DISABLED", "true")
os.environ.setdefault("CHROMA_TELEMETRY_ENABLED", "0")
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")

from sentence_transformers import SentenceTransformer
import chromadb
from chromadb.config import Settings

try:
    import posthog  # type: ignore

    if hasattr(posthog, "capture"):
        _original_capture = posthog.capture

        def _safe_capture(*args, **kwargs):
            try:
                return _original_capture(*args, **kwargs)
            except TypeError as e:
                if args:
                    try:
                        return _original_capture(args[0])
                    except Exception:
                        return None
                return None

        posthog.capture = _safe_capture  # type: ignore[attr-defined]
except Exception:
    pass

chroma_client = chromadb.PersistentClient(
    path="chroma_data",
    settings=Settings(anonymized_telemetry=False)
)

model = SentenceTransformer("paraphrase-MiniLM-L6-v2")

COLLECTION_NAME = "knowledge_collection"

try:
    knowledge_collection = chroma_client.get_collection(name=COLLECTION_NAME)
except Exception:
    knowledge_collection = chroma_client.create_collection(name=COLLECTION_NAME)