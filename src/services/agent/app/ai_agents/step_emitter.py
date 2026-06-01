"""Thought-process step emitter.

Pipeline helpers (retrieval, reasoning, react) call :func:`emit_step` at
phase boundaries. The consumer binds a per-task emitter on
:data:`agent_server.profiles.current_step_emitter` that POSTs each step
to MAS over HTTP for live UI rendering. When nothing is bound (e.g. unit
tests calling the pipeline directly), :func:`emit_step` is a no-op so
existing call sites stay non-invasive.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)


def emit_step(
    step_type: str,
    title: str,
    detail: str = "",
    **metadata: Any,
) -> None:
    """Fire a single step event through the bound emitter, if any.

    Args:
        step_type: Coarse phase label (``retrieval.start``, ``retrieval.results``,
            ``reasoning.start``, ``reasoning.done``, ``tool.invoke``, ``error``).
        title: One-line human-readable label rendered as the card row.
        detail: Optional longer description shown when the row is expanded.
        **metadata: Free-form structured payload (e.g. retrieved chunks).
    """
    try:
        from agent_server.profiles import current_step_emitter

        emitter = current_step_emitter.get()
    except Exception:
        emitter = None
    if emitter is None:
        return

    event: dict[str, Any] = {
        "step_type": step_type,
        "title": title,
        "detail": detail,
        "timestamp": datetime.now(UTC).isoformat(),
    }
    if metadata:
        event["metadata"] = metadata

    try:
        emitter(event)
    except Exception:  # never let a step send break the pipeline
        logger.debug("Step emitter failed for %s", step_type, exc_info=True)
