import contextvars
import threading

current_generation_stop: contextvars.ContextVar[threading.Event | None] = contextvars.ContextVar(
    "current_generation_stop", default=None
)


class GenerationTimedOut(TimeoutError):
    def __init__(self, seconds: float) -> None:
        super().__init__(
            "The model took too long to respond: it did not finish its answer "
            f"within {seconds:.0f}s, so this request was stopped. Try a shorter "
            "question, or ask an administrator "
            "to raise REACT_TIMEOUT_SECONDS. On a CPU-only deployment a long "
            "answer can take many minutes."
        )
        self.seconds = seconds


class GenerationStopped(RuntimeError):
    pass


def generation_stop_event() -> threading.Event | None:
    return current_generation_stop.get()
