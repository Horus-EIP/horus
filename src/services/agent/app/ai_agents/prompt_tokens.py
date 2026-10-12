from __future__ import annotations

import logging
import os
from enum import Enum

logger = logging.getLogger(__name__)

DEFAULT_PROMPT_TOKEN_BUDGET = 4096
CONSERVATIVE_CHARS_PER_TOKEN = 3


class TokenSource(str, Enum):
    USAGE = "usage"
    TOKENIZER = "tokenizer"
    ESTIMATE = "estimate"


def estimate_tokens(text: str) -> int:
    return -(-len(text) // CONSERVATIVE_CHARS_PER_TOKEN)


def prompt_token_budget() -> int:
    raw = os.getenv("AGENT_PROMPT_TOKEN_BUDGET", "").strip()
    try:
        budget = int(raw)
    except ValueError:
        return DEFAULT_PROMPT_TOKEN_BUDGET
    return budget if budget > 0 else DEFAULT_PROMPT_TOKEN_BUDGET


def record_prompt_tokens(call: str, tokens: int, source: TokenSource) -> bool:
    budget = prompt_token_budget()
    over_budget = tokens > budget
    try:
        from core.metrics import llm_prompt_tokens, llm_prompts_over_budget_total
    except ImportError:
        pass
    else:
        llm_prompt_tokens.labels(call=call, source=source.value).observe(max(0, tokens))
        if over_budget:
            llm_prompts_over_budget_total.labels(call=call).inc()
    logger.info(
        "LLM prompt tokens: call=%s prompt_tokens=%d source=%s budget=%d",
        call,
        tokens,
        source.value,
        budget,
    )
    if over_budget:
        logger.warning(
            "LLM prompt over its token budget: call=%s prompt_tokens=%d budget=%d",
            call,
            tokens,
            budget,
        )
    return over_budget
