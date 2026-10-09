import json
import os
import threading
import urllib.request
from dataclasses import dataclass

from core.llm_setup import _vllm_base_url, _vllm_model_name, llm_server_backend
from core.logger import get_logger

logger = get_logger("ai_mode")

MOCK = "mock"
LOCAL = "local"
UNKNOWN = "unknown"
MOCK_OWNER = "horus-mock"
IN_PROCESS = "in-process"
PROBE_TIMEOUT_SECONDS = 5.0


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


def probe() -> AiMode:
    if not llm_server_backend():
        return AiMode(LOCAL, os.getenv("LLM_MODEL_ID") or None, IN_PROCESS)
    url = _vllm_base_url().rstrip("/") + "/models"
    try:
        with urllib.request.urlopen(url, timeout=PROBE_TIMEOUT_SECONDS) as response:
            listed = json.loads(response.read().decode("utf-8"))["data"]
        served = listed[0]
        owner = served.get("owned_by")
        model = served.get("id")
    except (OSError, ValueError, KeyError, IndexError, TypeError, AttributeError) as exc:
        logger.warning("Could not ask the model server what it serves", url=url, error=str(exc))
        return AiMode(UNKNOWN, None, None)
    mode = MOCK if owner == MOCK_OWNER else LOCAL
    return AiMode(mode, str(model) if model else _vllm_model_name(), str(owner) if owner else None)


def current() -> AiMode:
    global _mode
    with _lock:
        if _mode is None or _mode.mode == UNKNOWN:
            _mode = probe()
            if _mode.mode == MOCK:
                logger.warning(
                    "Mock AI mode: the model server is llm-mock, so every answer is "
                    "simulated from the documents, not written by a language model",
                    model=_mode.model,
                )
        return _mode


def provider() -> str | None:
    return current().provider


def reset() -> None:
    global _mode
    with _lock:
        _mode = None


def start_probe_background_thread() -> threading.Thread:
    thread = threading.Thread(target=current, name="ai-mode-probe", daemon=True)
    thread.start()
    return thread
