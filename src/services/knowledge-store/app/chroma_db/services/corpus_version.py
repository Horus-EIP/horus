import threading
import uuid
from datetime import UTC, datetime


class CorpusVersion:
    def __init__(self) -> None:
        self._process_id = uuid.uuid4().hex[:12]
        self._changes = 0
        self._changed_at = datetime.now(UTC).isoformat()
        self._lock = threading.Lock()

    def bump(self) -> None:
        with self._lock:
            self._changes += 1
            self._changed_at = datetime.now(UTC).isoformat()

    def current(self) -> dict[str, str]:
        with self._lock:
            return {
                "version": f"{self._process_id}-{self._changes}",
                "changed_at": self._changed_at,
            }


_this_process = CorpusVersion()


def bump_corpus_version() -> None:
    _this_process.bump()


def current_corpus_version() -> dict[str, str]:
    return _this_process.current()
