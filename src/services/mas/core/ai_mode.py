import json
import os
import threading
import urllib.request
from dataclasses import dataclass

from core.embedding_setup import EMBED_MODEL_ID, EMBED_URL_ENV, server_model
from core.llm_setup import _vllm_base_url, _vllm_model_name, llm_server_backend
from core.logger import get_logger

logger = get_logger("ai_mode")

MOCK = "mock"
LOCAL = "local"
UNKNOWN = "unknown"
MOCK_OWNER = "horus-mock"
IN_PROCESS = "in-process"
PROBE_TIMEOUT_SECONDS = 5.0
SPACY_ENV = "HORUS_SPACY"
MONITORING_ENV = "HORUS_MONITORING"
TRACES_OFF_ENV = "OTEL_SDK_DISABLED"
OFF_VALUES = frozenset({"0", "false", "no", "off"})
TRUE_VALUES = frozenset({"1", "true", "yes"})
ON = "on"
OFF = "off"


@dataclass(frozen=True)
class AiMode:
    mode: str
    model: str | None
    server: str | None

    @property
    def provider(self) -> str | None:
        return None if self.mode == UNKNOWN else self.mode

    def as_dict(self) -> dict:
        return {
            "mode": self.mode,
            "model": self.model,
            "server": self.server,
            "simulated": self.mode == MOCK,
        }


_mode: AiMode | None = None
_lock = threading.Lock()
_embeddings: str | None = None
_embeddings_lock = threading.Lock()


def served_by(base_url: str) -> tuple[str | None, str | None] | None:
    url = base_url.rstrip("/") + "/models"
    try:
        with urllib.request.urlopen(url, timeout=PROBE_TIMEOUT_SECONDS) as response:
            listed = json.loads(response.read().decode("utf-8"))["data"]
        served = listed[0]
        owner = served.get("owned_by")
        model = served.get("id")
    except (OSError, ValueError, KeyError, IndexError, TypeError, AttributeError) as exc:
        logger.warning("Could not ask the model server what it serves", url=url, error=str(exc))
        return None
    return (str(owner) if owner else None), (str(model) if model else None)


def probe() -> AiMode:
    if not llm_server_backend():
        return AiMode(LOCAL, os.getenv("LLM_MODEL_ID") or None, IN_PROCESS)
    served = served_by(_vllm_base_url())
    if served is None:
        return AiMode(UNKNOWN, None, None)
    owner, model = served
    mode = MOCK if owner == MOCK_OWNER else LOCAL
    return AiMode(mode, model or _vllm_model_name(), owner)


def switched_off(name: str) -> bool:
    return os.getenv(name, "").split("#", 1)[0].strip().strip("\"'").lower() in OFF_VALUES


def embeddings() -> str | None:
    global _embeddings
    url = os.getenv(EMBED_URL_ENV, "").strip()
    if not url:
        return EMBED_MODEL_ID
    with _embeddings_lock:
        if _embeddings is None:
            served = served_by(url)
            if served is not None:
                owner, _ = served
                _embeddings = MOCK if owner == MOCK_OWNER else server_model()
        return _embeddings


def models_in_use() -> dict:
    return {
        "embeddings": embeddings(),
        "spacy": OFF if switched_off(SPACY_ENV) else ON,
        "monitoring": OFF if switched_off(MONITORING_ENV) else ON,
    }


def mock_warning() -> str:
    faked = "answers MAS's model calls"
    if embeddings() == MOCK:
        faked += " and computes its embeddings from the words of each text"
    message = (f"Mock AI mode: llm-mock {faked}, so routing, plans and answers are simulated, "
               "not produced by a model")
    if os.getenv(TRACES_OFF_ENV, "").strip().lower() in TRUE_VALUES:
        message += "; monitoring is off, so MAS exports no trace"
    return message


def current() -> AiMode:
    global _mode
    with _lock:
        if _mode is None or _mode.mode == UNKNOWN:
            _mode = probe()
            if _mode.mode == MOCK:
                logger.warning(mock_warning(), model=_mode.model)
        return _mode


def provider() -> str | None:
    return current().provider


def reset() -> None:
    global _mode, _embeddings
    with _lock:
        _mode = None
    with _embeddings_lock:
        _embeddings = None


def start_probe_background_thread() -> threading.Thread:
    thread = threading.Thread(target=current, name="ai-mode-probe", daemon=True)
    thread.start()
    return thread
